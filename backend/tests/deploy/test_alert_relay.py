"""The alert relay (#53): credentials, closed incidents, size cap, shape, and what is dispatched.
No network: the GitHub call is replaced by a recorder."""

import base64
import json
import logging
import threading
import urllib.error
import urllib.request
from collections.abc import Mapping
from http.server import ThreadingHTTPServer
from typing import Any

import pytest

from tests.deploy.support import load_script

relay = load_script("deploy/alert-relay/relay.py", "alert_relay")

CONFIG = relay.Config(
    username="cloud-monitoring",
    password="relay-test-password",
    repository="owner/supplier-iscan",
    token="github-test-token",
)
GOOD_AUTH = "Basic " + base64.b64encode(b"cloud-monitoring:relay-test-password").decode()


def notification(state: str = "open", **incident: Any) -> dict[str, Any]:
    fields = {
        "incident_id": "0.abc123XYZ",
        "policy_name": "iscan-dev profile-run failure rate",
        "state": state,
        "started_at": 1_794_477_600,
        "url": "https://console.cloud.google.com/monitoring/alerting/incidents/0.abc123XYZ?project=p",
        "summary": "free text that must never be forwarded",
    }
    fields.update(incident)
    return {"version": "1.2", "incident": fields}


class Recorder:
    def __init__(self, status: int = 204) -> None:
        self.calls: list[Mapping[str, str]] = []
        self.status = status

    def __call__(self, inputs: Mapping[str, str]) -> int:
        self.calls.append(dict(inputs))
        return self.status


def post(
    body: bytes,
    auth: str | None = GOOD_AUTH,
    length: str | None = None,
    recorder: Recorder | None = None,
) -> tuple[Any, Recorder]:
    recorder = recorder or Recorder()
    outcome = relay.handle(
        auth,
        str(len(body)) if length is None else length,
        lambda n: body[:n],
        CONFIG,
        recorder,
    )
    return outcome, recorder


def encode(payload: Any) -> bytes:
    return json.dumps(payload).encode()


def test_open_incident_dispatches_the_five_inputs_only() -> None:
    outcome, recorder = post(encode(notification()))

    assert outcome.status == 204
    assert recorder.calls == [
        {
            "incident_id": "0.abc123XYZ",
            "policy_name": "iscan-dev profile-run failure rate",
            "environment": "dev",
            "started_at": "2026-11-12T10:00:00Z",
            "console_url": "https://console.cloud.google.com/monitoring/alerting/incidents/0.abc123XYZ?project=p",
        }
    ]


@pytest.mark.parametrize(
    "auth",
    [
        None,
        "",
        "Bearer relay-test-password",
        "Basic not-base64!!",
        "Basic " + base64.b64encode(b"cloud-monitoring:wrong").decode(),
        "Basic " + base64.b64encode(b"someone:relay-test-password").decode(),
        "Basic " + base64.b64encode(b"cloud-monitoringrelay-test-password").decode(),
    ],
)
def test_missing_or_wrong_credentials_get_401_and_trigger_nothing(auth: str | None) -> None:
    outcome, recorder = post(encode(notification()), auth=auth)

    assert outcome.status == 401
    assert recorder.calls == []


def test_the_body_is_not_read_before_the_credentials_pass() -> None:
    def read(_: int) -> bytes:
        raise AssertionError("body read without credentials")

    outcome = relay.handle(None, "10", read, CONFIG, Recorder())
    assert outcome.status == 401


def test_closed_incident_triggers_nothing() -> None:
    outcome, recorder = post(encode(notification(state="closed")))

    assert outcome.status == 202
    assert recorder.calls == []


@pytest.mark.parametrize("length", [str(relay.MAX_BODY_BYTES + 1), "0", "-5", "", "many"])
def test_a_body_over_the_cap_or_without_a_length_gets_400(length: str) -> None:
    outcome, recorder = post(b"{}", length=length)

    assert outcome.status == 400
    assert recorder.calls == []


@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        b"\xff\xfe",
        encode([1, 2]),
        encode({"incident": "open"}),
        encode({"version": "1.2"}),
        encode(notification(state="acknowledged")),
        encode(notification(incident_id="0.abc; rm -rf /")),
        encode(notification(incident_id="")),
        encode(notification(policy_name="x" * 200)),
        encode(notification(policy_name="$(curl evil)")),
        encode(notification(url="https://evil.example/console")),
        encode(notification(started_at="yesterday")),
        encode(notification(started_at=True)),
        encode(notification(started_at=10**20)),
    ],
)
def test_a_body_of_the_wrong_shape_gets_400(payload: bytes) -> None:
    outcome, recorder = post(payload)

    assert outcome.status == 400
    assert recorder.calls == []


def test_deeply_nested_json_under_the_cap_gets_400(caplog: pytest.LogCaptureFixture) -> None:
    body = b"[" * 60_000
    assert len(body) < relay.MAX_BODY_BYTES

    with caplog.at_level(logging.INFO, logger="alert-relay"):
        outcome, recorder = post(body)

    assert outcome.status == 400
    assert recorder.calls == []
    assert "[[[" not in caplog.text


def test_github_refusal_is_a_502_naming_the_status_only() -> None:
    outcome, _ = post(encode(notification()), recorder=Recorder(status=401))

    assert outcome.status == 502
    assert outcome.note == "GitHub answered 401"


def test_missing_settings_stop_the_relay_naming_them() -> None:
    with pytest.raises(SystemExit) as stopped:
        relay.load_config({"GITHUB_REPOSITORY": "o/r"})
    assert "WEBHOOK_PASSWORD" in str(stopped.value)
    assert "GITHUB_DISPATCH_TOKEN" in str(stopped.value)


def test_server_answers_and_never_logs_credentials_or_body(
    caplog: pytest.LogCaptureFixture,
) -> None:
    recorder = Recorder()
    server = ThreadingHTTPServer(("127.0.0.1", 0), relay.make_handler(CONFIG, recorder))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    statuses = []
    try:
        with caplog.at_level(logging.INFO, logger="alert-relay"):
            for auth in (GOOD_AUTH, "Basic " + base64.b64encode(b"cloud-monitoring:bad").decode()):
                request = urllib.request.Request(  # noqa: S310 - local test server
                    url, data=encode(notification()), method="POST", headers={"Authorization": auth}
                )
                try:
                    with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
                        statuses.append(response.status)
                except urllib.error.HTTPError as error:
                    statuses.append(error.code)
    finally:
        server.shutdown()
        server.server_close()

    assert statuses == [204, 401]
    assert len(recorder.calls) == 1
    logged = caplog.text
    for secret in ("relay-test-password", "github-test-token", GOOD_AUTH, "free text", "abc123XYZ"):
        assert secret not in logged

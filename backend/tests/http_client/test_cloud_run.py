"""Starting the hosted worker job (#200): the token from the metadata server, then `:run`."""

import json

import httpx2
import pytest

from app.http_client import start_worker_job
from app.http_client.cloud_run import START_TIMEOUT_SECONDS

JOB = "projects/p-1/locations/europe-west1/jobs/iscan-worker-dev"
TOKEN = "ya29.secret-token-value"


class CloudRun:
    """Answers the metadata server and the Cloud Run Admin API; records every request."""

    def __init__(self, run_status: int = 200, token_status: int = 200) -> None:
        self.requests: list[httpx2.Request] = []
        self.run_status, self.token_status = run_status, token_status
        self.transport = httpx2.MockTransport(self._handle)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if request.url.host == "metadata.google.internal":
            return httpx2.Response(
                self.token_status, json={"access_token": TOKEN, "expires_in": 3599}
            )
        return httpx2.Response(self.run_status, json={"name": "operations/x"})


def test_start_gets_the_token_then_runs_the_job_once() -> None:
    cloud = CloudRun()

    assert start_worker_job(JOB, transport=cloud.transport) is True

    token, run = cloud.requests
    assert token.method == "GET"
    assert str(token.url) == (
        "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
    )
    assert token.headers["Metadata-Flavor"] == "Google"
    assert run.method == "POST"
    assert str(run.url) == f"https://run.googleapis.com/v2/{JOB}:run"
    assert run.headers["Authorization"] == f"Bearer {TOKEN}"
    assert json.loads(run.content) == {}
    assert START_TIMEOUT_SECONDS == 5


@pytest.mark.parametrize("cloud", [CloudRun(run_status=403), CloudRun(token_status=500)])
def test_a_refused_start_is_a_warning_without_the_token(
    cloud: CloudRun, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("INFO"):
        assert start_worker_job(JOB, transport=cloud.transport) is False

    assert "Worker job not started: HTTP" in caplog.text
    assert TOKEN not in caplog.text and "Bearer" not in caplog.text


def test_a_network_failure_is_a_warning(caplog: pytest.LogCaptureFixture) -> None:
    def fail(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectTimeout("timed out", request=request)

    with caplog.at_level("WARNING"):
        assert start_worker_job(JOB, transport=httpx2.MockTransport(fail)) is False

    assert "Worker job not started (ConnectTimeout)" in caplog.text


def test_a_name_that_is_not_a_job_resource_is_never_sent() -> None:
    cloud = CloudRun()

    assert start_worker_job("https://example.com/x", transport=cloud.transport) is False
    assert cloud.requests == []

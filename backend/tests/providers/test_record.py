"""The re-record command, run against a mock transport instead of a live API."""

import json
from pathlib import Path
from typing import Any

import pytest

from app.providers.catalogue import load_catalogue
from tests.providers.record import main, record
from tests.providers.replay import RECORDINGS
from tests.providers.support import SENTINEL_KEY

CONFIG_ID = "claude-sonnet"


def _serving(body: Any) -> Any:
    def transport(library: Any) -> Any:
        return library.MockTransport(lambda request: library.Response(200, json=body))

    return transport


def test_a_recording_is_the_provider_answer_with_the_usage_the_adapter_read(tmp_path: Path) -> None:
    spec = load_catalogue().by_id[CONFIG_ID]
    existing = json.loads((RECORDINGS / f"{CONFIG_ID}.structuring.json").read_text())

    path = record(spec, "structuring", SENTINEL_KEY, _serving(existing["body"]), directory=tmp_path)

    written = json.loads(path.read_text())
    assert written["body"] == existing["body"] and written["status"] == 200
    assert written["expected_usage"] == existing["expected_usage"]
    assert written["origin"] == "recorded from the live API" and written["recorded_at"]
    assert SENTINEL_KEY not in path.read_text()


def test_a_recording_that_holds_the_key_or_an_email_address_is_refused(tmp_path: Path) -> None:
    spec = load_catalogue().by_id[CONFIG_ID]
    body = json.loads((RECORDINGS / f"{CONFIG_ID}.structuring.json").read_text())["body"]
    body["id"] = "someone@example.org"

    with pytest.raises(SystemExit, match="email"):
        record(spec, "structuring", SENTINEL_KEY, _serving(body), directory=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_the_command_refuses_an_unapproved_configuration_and_a_missing_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("PROVIDER_CONFIG_FILE", raising=False)

    assert main(["--config", CONFIG_ID]) == 2  # the shipped example is disabled
    assert "not approved" in capsys.readouterr().err
    assert main(["--config", "unknown"]) == 2

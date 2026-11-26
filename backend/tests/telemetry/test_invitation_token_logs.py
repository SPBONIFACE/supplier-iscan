"""The invitation token, sent in a POST body, reaches no log record, span or event (#131)."""

import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tests.factories import create_invitation, create_organisation
from tests.telemetry.conftest import Recording

MARKER = "QSENT-INVITATION-TOKEN-MARKER"
PASSWORD = "a long enough password for any test setting"


def test_the_token_marker_is_in_no_log_record_span_or_event(
    client: TestClient,
    engine: Engine,
    recording: Recording,
    caplog: pytest.LogCaptureFixture,
) -> None:
    organisation_id = create_organisation(engine)
    valid = create_invitation(engine, organisation_id)
    other = create_invitation(engine, organisation_id)
    # A real token cannot hold the marker: the marker rides in a malformed value, in an unknown
    # token, and next to a real token (which is replaced by it below to keep the test honest).
    with caplog.at_level(logging.DEBUG):
        caplog.set_level(logging.DEBUG, logger="uvicorn.access")
        client.post("/invitations/check", json={"token": MARKER})  # unknown
        client.post("/invitations/check", json={"token": MARKER * 20})  # malformed, oversized
        client.post("/invitations/check", json={"token": f"{MARKER} !/?#%"})  # wrong characters
        client.post("/invitations/check", json={"token": valid.token, "extra": MARKER})  # 422
        client.post("/invitations/accept", json={"token": MARKER, "password": PASSWORD})
        client.post("/invitations/accept", json={"token": MARKER * 20, "password": PASSWORD})
        client.post("/invitations/accept", json={"token": MARKER, "password": "short"})  # 422
        client.post("/invitations/accept", json={"token": 123, "password": MARKER})  # 422
        # Valid: the token of the invitation itself is the marker in what follows.
        assert client.post("/invitations/check", json={"token": other.token}).status_code == 200
        assert (
            client.post(
                "/invitations/accept", json={"token": other.token, "password": PASSWORD}
            ).status_code
            == 200
        )

    seen = "\n".join(
        [recording.everything(), caplog.text, *(r.getMessage() for r in caplog.records)]
    )
    for secret in (MARKER, other.token, valid.token, PASSWORD):
        assert secret not in seen
    # The log is not empty: the requests were observed, the token was not.
    assert "POST /invitations/check" in seen and "POST /invitations/accept" in seen

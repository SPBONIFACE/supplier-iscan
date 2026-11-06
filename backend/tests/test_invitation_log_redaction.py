"""Invitation tokens never reach the access log (they are credentials; issue #9)."""

import logging

import pytest

from app.invitations.log_redaction import (
    ACCESS_LOGGER,
    REDACTED,
    RedactInvitationTokens,
    install_access_log_redaction,
    redact_invitation_token,
)
from tests.support import make_client

TOKEN = "Zm9vYmFyLXNlY3JldC10b2tlbi12YWx1ZS0xMjM0NTY3OA"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (f"/invitations/{TOKEN}", f"/invitations/{REDACTED}"),
        (f"/invitations/{TOKEN}/accept", f"/invitations/{REDACTED}/accept"),
        (f"/invitations/{TOKEN}?x=1", f"/invitations/{REDACTED}?x=1"),
        ("/admin/invitations/0b6f1f62-1111-4222-8333-944445555666", None),
        ("/auth/login", None),
    ],
)
def test_only_the_token_segment_is_redacted(path: str, expected: str | None) -> None:
    assert redact_invitation_token(path) == (expected or path)


def test_access_log_lines_do_not_contain_the_token(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_client(database_check=lambda: True)  # creating the application installs the filter
    logger = logging.getLogger(ACCESS_LOGGER)
    # The telemetry set-up switches uvicorn's access log off (#51); the filter stays as defence
    # in depth, so the test turns the logger back on.
    monkeypatch.setattr(logger, "disabled", False)

    with caplog.at_level(logging.INFO, logger=ACCESS_LOGGER):
        # The call uvicorn makes for each request.
        logger.info(
            '%s - "%s %s HTTP/%s" %d',
            "127.0.0.1:5000",
            "POST",
            f"/invitations/{TOKEN}/accept",
            "1.1",
            200,
        )

    assert TOKEN not in caplog.text
    assert f"/invitations/{REDACTED}/accept" in caplog.text


def test_the_filter_is_installed_once() -> None:
    install_access_log_redaction()
    install_access_log_redaction()

    filters = logging.getLogger(ACCESS_LOGGER).filters
    assert sum(isinstance(f, RedactInvitationTokens) for f in filters) == 1

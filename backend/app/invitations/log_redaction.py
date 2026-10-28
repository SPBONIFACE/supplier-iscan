"""Keep invitation tokens out of the server's access log.

The contract puts the token in the path (`/invitations/{token}`), and uvicorn's access log writes
every request path. A token is a credential until it is used or expires, so the path segment is
replaced by `[redacted]` before the line is written.
"""

import logging
import re

ACCESS_LOGGER = "uvicorn.access"
REDACTED = "[redacted]"

_TOKEN_IN_PATH = re.compile(r"^(/invitations/)[^/?#]+")


def redact_invitation_token(path: str) -> str:
    return _TOKEN_IN_PATH.sub(rf"\g<1>{REDACTED}", path)


class RedactInvitationTokens(logging.Filter):
    """Rewrites the arguments of access-log records; the record itself is always kept."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                redact_invitation_token(arg) if isinstance(arg, str) else arg for arg in record.args
            )
        return True


def install_access_log_redaction() -> None:
    logger = logging.getLogger(ACCESS_LOGGER)
    if not any(isinstance(existing, RedactInvitationTokens) for existing in logger.filters):
        logger.addFilter(RedactInvitationTokens())

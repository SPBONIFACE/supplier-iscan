"""Classify an exception raised inside a vendor SDK call into a failure kind and HTTP status.

The five SDKs raise different classes, but they share two shapes: an HTTP status on the exception
(`status_code` on the Anthropic, OpenAI, Perplexity and Mistral SDKs, `code` on google-genai), and
transport errors of the underlying HTTP client (timeouts, connection failures). Transport errors
are recognised by class name, so that this module imports no HTTP library (#15 policy).

Only the class and the status are read: never the message, which can quote the request or the
response body.
"""

from pydantic import ValidationError

from app.providers.errors import FailureKind

_TIMEOUT_CLASS_NAMES = frozenset(
    {
        "APITimeoutError",
        "TimeoutException",
        "ConnectTimeout",
        "ReadTimeout",
        "WriteTimeout",
        "PoolTimeout",
    }
)
_CONNECTION_CLASS_NAMES = frozenset(
    {
        "APIConnectionError",
        "TransportError",
        "NetworkError",
        "ConnectError",
        "ReadError",
        "WriteError",
        "RemoteProtocolError",
        "ProtocolError",
        "NoResponseError",
        "ProxyError",
    }
)
_INVALID_RESPONSE_CLASS_NAMES = frozenset(
    {
        "APIResponseValidationError",
        "ResponseValidationError",
        "JSONDecodeError",
        "DecodingError",
        "UnknownApiResponseError",
    }
)


def _status_code(error: Exception) -> int | None:
    for attribute in ("status_code", "code"):
        value = getattr(error, attribute, None)
        if isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 599:
            return value
    return None


def _kind_for_status(status: int) -> FailureKind:
    if status in (401, 403):
        return "authentication"
    if status == 408:
        return "timeout"
    if status == 429:
        return "rate_limited"
    if status >= 500:
        return "unavailable"
    return "rejected"


def classify_failure(error: Exception) -> tuple[FailureKind, int | None]:
    names = {cls.__name__ for cls in type(error).__mro__}
    if names & _TIMEOUT_CLASS_NAMES or isinstance(error, TimeoutError):
        return "timeout", None
    status = _status_code(error)
    if status is not None:
        return _kind_for_status(status), status
    if names & _CONNECTION_CLASS_NAMES or isinstance(error, ConnectionError):
        return "connection", None
    if names & _INVALID_RESPONSE_CLASS_NAMES or isinstance(error, ValidationError | ValueError):
        return "invalid_response", None
    return "unexpected", None

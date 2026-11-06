"""Classify an exception raised inside a vendor SDK call into a failure kind and HTTP status.

The five SDKs raise different classes, but they share two shapes: an HTTP status on the exception
(`status_code` on the Anthropic, OpenAI, Perplexity and Mistral SDKs, `code` on google-genai), and
transport errors of the underlying HTTP client (timeouts, connection failures). Transport errors
are recognised by class name, so that this module imports no HTTP library (#15 policy).

`classify_failure` reads only the class and the status. The provider's own error type and message
are read separately by `provider_error_detail`, for the log of a rejected call only (#125).
"""

import json
import re

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


def validation_detail(error: Exception) -> str:
    """Where a pydantic validation failed, for the log: the field path, the rule that failed and
    the type received, for up to five errors. Never the message or the input, which can quote the
    response (#122). Empty for any other exception."""
    if not isinstance(error, ValidationError):
        return ""
    parts = []
    for item in error.errors(include_url=False, include_context=False, include_input=True)[:5]:
        path = ".".join(str(step) for step in item["loc"]) or "<root>"
        received = type(item.get("input")).__name__
        parts.append(f"{path} rule={item['type']} received={received}")
    return "; ".join(parts)


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


_MAX_DETAIL = 400
_BLANKS = re.compile(r"\s+")


def _clean(value: object) -> str:
    return _BLANKS.sub(" ", value).strip()[:_MAX_DETAIL] if isinstance(value, str) else ""


def provider_error_detail(error: Exception) -> str:
    """The provider's own error type and message of an HTTP error, for the log (#125).

    These describe the request (for example `invalid_request_error`, "output_config.format.schema:
    ... not supported"), never its content: the providers do not echo prompts. Read from the
    parsed body the SDKs keep on the exception (Anthropic and OpenAI `error.type` and
    `error.message`; Perplexity the same; Mistral `detail` or `message`; Google `status` and
    `message`), whitespace collapsed and cut at 400 characters. Empty for a transport failure or
    when the provider sent nothing readable. Only called for an exception with an HTTP status.
    """
    if _status_code(error) is None:
        return ""
    body = getattr(error, "body", None) or getattr(error, "details", None)
    if isinstance(body, str | bytes):
        try:
            body = json.loads(body)
        except ValueError:
            body = None
    body = body if isinstance(body, dict) else {}
    nested = body.get("error")
    source = nested if isinstance(nested, dict) else body
    kind = (
        _clean(source.get("type"))
        or _clean(source.get("status"))
        or _clean(getattr(error, "status", None))
        or _clean(source.get("code"))
    )
    message = (
        _clean(source.get("message"))
        or _clean(source.get("detail"))
        or _clean(getattr(error, "message", None))
    )
    parts = []
    if kind:
        parts.append(f"provider_error_type={kind}")
    if message:
        parts.append(f"provider_error_message={message!r}")
    return " ".join(parts)

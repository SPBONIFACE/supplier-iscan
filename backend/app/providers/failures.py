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


_MAX_MESSAGE = 200
_WINDOW = 16
_BLANKS = re.compile(r"\s+")
_SAFE_TYPE = re.compile(r"[A-Za-z0-9_.\-]{1,60}")
_PLACEHOLDER = "[removed]"
# Applied in this order. Quoted spans first (the content a provider echoes is usually quoted); an
# unterminated opening quote removes the rest of the message.
_REDACTIONS = (
    re.compile(r"(?<!\w)'[^']*(?:'|$)|\"[^\"]*(?:\"|$)|`[^`]*(?:`|$)"),
    re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),  # email
    re.compile(r"(?:https?|ftp)://\S+|www\.\S+"),  # URL
    re.compile(r"\+?\d[\d\s().-]{6,}\d"),  # phone-like and long digit runs
    re.compile(r"\b(?:sk|pk|rk|xai|pplx|gsk|ghp|AIza|AKIA|Bearer)[-_ ]?[A-Za-z0-9_\-]{4,}"),
    re.compile(r"\b[A-Fa-f0-9]{16,}\b"),  # hex
    re.compile(r"[A-Za-z0-9+/_=-]{24,}"),  # base64-like and other long tokens
)
WITHHELD = "provider_error_message=<withheld>"


def _normal(text: str) -> str:
    return _BLANKS.sub(" ", text).casefold()


def _safe_type(value: object) -> str:
    """An error type is an identifier (`invalid_request_error`, `INVALID_ARGUMENT`); anything else
    is not logged."""
    return value if isinstance(value, str) and _SAFE_TYPE.fullmatch(value) else ""


def sanitise_message(message: object, request_texts: tuple[str, ...] = ()) -> str:
    """A provider error message made safe to log (#125), or "" when nothing safe remains.

    Quoted spans, emails, URLs, phone-like and long digit runs, and key-like tokens are removed; if
    what remains still shares a run of 16 characters with the request's own text (prompt, system,
    data), the whole message is dropped. The result is cut at 200 characters.
    """
    if not isinstance(message, str):
        return ""
    cleaned = message[:2000]
    for pattern in _REDACTIONS:
        cleaned = pattern.sub(_PLACEHOLDER, cleaned)
    cleaned = _normal(cleaned).strip()
    haystack = "\n".join(_normal(text) for text in request_texts if text)
    if haystack and any(
        cleaned[i : i + _WINDOW] in haystack for i in range(max(len(cleaned) - _WINDOW + 1, 0))
    ):
        return ""
    return cleaned[:_MAX_MESSAGE]


def provider_error_detail(error: Exception, request_texts: tuple[str, ...] = ()) -> str:
    """The provider's own error type and a sanitised message of an HTTP error, for the log (#125).

    Read from the parsed body the SDKs keep on the exception (Anthropic, OpenAI and Perplexity
    `error.type` and `error.message`; Mistral `detail` or `message`; Google `status` and
    `message`). The type is logged only if it is a plain identifier; the message only after
    `sanitise_message` (a message that may echo the request is replaced by a fixed note). Empty
    for a transport failure. The caller logs the HTTP status.
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
        _safe_type(source.get("type"))
        or _safe_type(source.get("status"))
        or _safe_type(getattr(error, "status", None))
        or _safe_type(str(source.get("code") or ""))
    )
    raw = source.get("message") or source.get("detail") or getattr(error, "message", None)
    parts = []
    if kind:
        parts.append(f"provider_error_type={kind}")
    if isinstance(raw, str) and raw.strip():
        message = sanitise_message(raw, request_texts)
        parts.append(f"provider_error_message={message!r}" if message else WITHHELD)
    return " ".join(parts)

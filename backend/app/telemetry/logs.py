"""JSON logs on standard output, with the trace and span ids of the current span (#51).

A log entry has a fixed set of fields: `timestamp`, `level`, `service`, `logger`, `message`,
`trace_id`, `span_id`, and for an exception `error_type` and `error_stack` (the frames: file, line,
function). Never the text of an exception, which an SDK can fill with the request, and never
extra attributes: what is written is the message that our own code chose.

SDK debug logging stays off (QA note of #11). The environment variables that switch it on are
removed before the SDKs are imported, and whatever their loggers emit below WARNING is dropped by a
filter on the handler (the HTTP clients log the address of every request at INFO). Nothing below
INFO is written, from any logger.
"""

import json
import logging
import os
import sys
import traceback
from datetime import UTC, datetime
from typing import Any, TextIO

from opentelemetry import trace

# Switches that make an SDK log its requests (prompts included) at DEBUG.
SDK_LOG_VARIABLES = (
    "ANTHROPIC_LOG",
    "OPENAI_LOG",
    "PERPLEXITY_LOG",
    "MISTRAL_LOG",
    "MISTRAL_DEBUG",
    "GOOGLE_GENAI_LOG",
    "GENAI_LOG",
    "HTTPX_LOG_LEVEL",
)
# Loggers of the provider SDKs and of the HTTP stack under them.
QUIET_LOGGERS = frozenset(
    {
        "anthropic",
        "openai",
        "perplexity",
        "perplexityai",
        "mistralai",
        "google",
        "google_genai",
        "httpx",
        "httpx2",
        "httpcore",
        "urllib3",
        "requests",
    }
)
UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")
_HANDLER_NAME = "supplier-iscan-json"


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self._service = service

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "service": self._service,
            "logger": record.name,
            "message": record.getMessage(),
        }
        context = trace.get_current_span().get_span_context()
        if context.is_valid:
            entry["trace_id"] = format(context.trace_id, "032x")
            entry["span_id"] = format(context.span_id, "016x")
        if record.exc_info and record.exc_info[0] is not None:
            entry["error_type"] = record.exc_info[0].__name__
            entry["error_stack"] = [
                f"{frame.filename}:{frame.lineno} {frame.name}"
                for frame in traceback.extract_tb(record.exc_info[2])
            ]
        return json.dumps(entry, ensure_ascii=False)


class _SdkFilter(logging.Filter):
    """Drops what the SDK and HTTP loggers say below WARNING."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.WARNING or record.name.split(".")[0] not in QUIET_LOGGERS


def configure_logging(service: str, stream: TextIO | None = None) -> None:
    """Write the application's logs, and uvicorn's, as JSON to the stream (stderr by default).
    Safe to call again: the handler is replaced, not added twice."""
    for variable in SDK_LOG_VARIABLES:
        os.environ.pop(variable, None)
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.set_name(_HANDLER_NAME)
    handler.setLevel(logging.INFO)
    handler.setFormatter(JsonFormatter(service))
    handler.addFilter(_SdkFilter())
    root = logging.getLogger()
    for existing in list(root.handlers):
        if existing.get_name() == _HANDLER_NAME:
            root.removeHandler(existing)
    root.addHandler(handler)
    if root.level == logging.NOTSET or root.level > logging.INFO:
        root.setLevel(logging.INFO)
    # Plain uvicorn gives its own loggers their own handlers and does not propagate: without this
    # the application's loggers would stay mute under it and its lines would not be JSON.
    for name in UVICORN_LOGGERS:
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
    # The SDK loggers a DEBUG level was set on before this ran.
    for name in QUIET_LOGGERS:
        if logging.getLogger(name).level == logging.DEBUG:
            logging.getLogger(name).setLevel(logging.WARNING)

"""Shared error answers (openapi.yaml components/responses): 422 ValidationFailed, 503
ServiceUnavailable. 401 Unauthorized is an HTTPException with a generic `detail`.

No answer ever contains a stack trace, a connection string or a submitted value.
"""

import logging
from collections.abc import Sequence
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import InterfaceError, OperationalError

from app.db import DatabaseUnavailable

logger = logging.getLogger(__name__)

INVALID_REQUEST = "The request is not valid."
SERVICE_UNAVAILABLE = "The service is temporarily unavailable. Please try again in a few minutes."

_MAX_FIELD_NAME_LENGTH = 64


def _field(location: Sequence[Any]) -> str:
    # ("body", "email") -> "email"; ("body",) -> "body"
    parts = [str(part) for part in location if part != "body"]
    return (parts[-1] if parts else "body")[:_MAX_FIELD_NAME_LENGTH]


def _message(field: str, error_type: str) -> str:
    if field == "body":
        return "The request body must be a JSON object."
    label = field.replace("_", " ").capitalize()
    if error_type in {"missing", "string_too_short"}:
        return f"{label} is required."
    if error_type == "string_too_long":
        return f"{label} is too long."
    if error_type == "extra_forbidden":
        return f"{label} is not an accepted field."
    return f"{label} is not valid."


def validation_errors(errors: Sequence[Any]) -> list[dict[str, str]]:
    """Field and message only: pydantic's `input` (the submitted value) is dropped."""
    result: list[dict[str, str]] = []
    for error in errors:
        error_type = str(error.get("type", ""))
        # Malformed JSON: the location is a character position, not a field.
        field = "body" if error_type == "json_invalid" else _field(error.get("loc", ()))
        item = {"field": field, "message": _message(field, error_type)}
        if item not in result:
            result.append(item)
    return result or [{"field": "body", "message": "The request body must be a JSON object."}]


async def _on_validation_error(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, RequestValidationError)  # noqa: S101 - registered for this type
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": INVALID_REQUEST, "errors": validation_errors(error.errors())},
    )


async def _on_database_unavailable(request: Request, error: Exception) -> JSONResponse:
    # The error type only: the message can contain the connection string.
    logger.warning("Database unavailable: %s", type(error).__name__)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": SERVICE_UNAVAILABLE}
    )


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, _on_validation_error)
    for error_type in (DatabaseUnavailable, OperationalError, InterfaceError):
        app.add_exception_handler(error_type, _on_database_unavailable)

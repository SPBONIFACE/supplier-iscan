"""Opt-in diagnostic: the SHAPE of one live provider response, written to a local file (#122).

Called only by `make provider-shape` (`eval/provider_shape.py`); the application never writes it.
The file holds field names, JSON types, string lengths
and list lengths, and nothing else: no text, no URL, no value. It goes to `PROVIDER_SHAPE_DIR`
(default `diagnostics/`, git-ignored). It is meant to be run once on a synthetic public query and
shared, so a response that fails validation can be compared with what the adapter expects.
"""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MAX_ITEMS = 12
_MAX_DEPTH = 12


def describe(value: object, depth: int = 0) -> object:
    """Field names and types of a JSON-like value; strings become `str(<length>)`."""
    if depth > _MAX_DEPTH:
        return "..."
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return f"str({len(value)})"
    if isinstance(value, dict):
        return {str(key): describe(item, depth + 1) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return {
            "list": len(value),
            "items": [describe(item, depth + 1) for item in value[:_MAX_ITEMS]],
        }
    return type(value).__name__


def _as_dict(response: object) -> object:
    convert = getattr(response, "to_dict", None) or getattr(response, "model_dump", None)
    if not callable(convert):
        return response
    try:
        return convert()
    except Exception as error:  # noqa: BLE001 - the diagnostic never breaks the call
        logger.warning("Shape diagnostic could not convert the response (%s)", type(error).__name__)
        return response


def write_shape(provider: str, label: str, response: object, directory: Path) -> Path | None:
    """Write the shape of `response` into `directory`; returns the file, or None."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"{provider}-{label}-{stamp}.json"
    document: dict[str, Any] = {
        "provider": provider,
        "call": label,
        "note": "Shape only: field names, types, string and list lengths. No text, no URL.",
        "shape": describe(_as_dict(response)),
    }
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    except OSError as error:
        logger.warning("Shape diagnostic not written (%s)", type(error).__name__)
        return None
    logger.warning("Shape diagnostic written: %s", path)
    return path

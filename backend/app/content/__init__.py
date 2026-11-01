"""Runtime content files: JSON data loaded at startup and validated against a published schema.

The profile definition (#21) uses this; the country table (#26) and the prompt set (#55) load the
same way. The schemas and the shipped examples live in this directory. A missing, unreadable,
empty, oversized or invalid file raises `ConfigurationError` naming the file and the failing path,
so that startup stops and nothing is partially loaded.
"""

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from app.config import ConfigurationError

CONTENT_DIR = Path(__file__).resolve().parent
MAX_FILE_BYTES = 1_000_000


def load_schema(name: str) -> dict[str, Any]:
    """A published schema shipped in this directory (a bug if it is missing or invalid)."""
    schema: dict[str, Any] = json.loads((CONTENT_DIR / name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return schema


def _path(parts: Any) -> str:
    return "/".join(str(part) for part in parts) or "(document)"


def load_content_file(path: Path, schema_name: str, what: str) -> dict[str, Any]:
    """Read `path`, check it against the schema `schema_name`, return the JSON object.

    `what` names the kind of file in error messages ("Profile definition file").
    """
    label = f"{what} {path}"
    try:
        raw = path.read_bytes()
    except OSError:
        raise ConfigurationError(f"{label} cannot be read") from None
    if len(raw) > MAX_FILE_BYTES:
        raise ConfigurationError(f"{label} is larger than {MAX_FILE_BYTES} bytes")
    if not raw.strip():
        raise ConfigurationError(f"{label} is empty")
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ConfigurationError(f"{label} is not valid JSON ({type(error).__name__})") from None
    validator = Draft202012Validator(load_schema(schema_name))
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.absolute_path))
    if errors:
        first = errors[0]
        raise ConfigurationError(
            f"{label} is not valid at {_path(first.absolute_path)}: {first.message[:200]}"
        )
    if not isinstance(document, dict):  # the schema says object; keeps the type honest
        raise ConfigurationError(f"{label} is not a JSON object")
    return document

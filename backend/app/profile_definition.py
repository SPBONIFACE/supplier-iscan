"""The profile definition: sections and fields of a supplier profile, loaded at startup (#21).

The file named by PROFILE_DEFINITION_FILE is used; without that setting, the example shipped in
`app/content/` is used. It is validated against the published schema
(`app/content/profile-definition.schema.json`), then checked for duplicate identifiers. Any problem
raises `ConfigurationError` naming the file and the failing path, and nothing is kept.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app.config import ConfigurationError
from app.content import CONTENT_DIR, load_content_file

SCHEMA_FILE = "profile-definition.schema.json"
EXAMPLE_FILE = CONTENT_DIR / "profile-definition.example.json"
WHAT = "Profile definition file"

Language = Literal["en", "fr"]
FieldKind = Literal["fact", "assessment", "buyer"]


@dataclass(frozen=True)
class FieldDefinition:
    id: str
    labels: dict[str, str]
    kind: FieldKind
    extraction_hint: str
    certification: bool
    concerns_people: bool


@dataclass(frozen=True)
class SectionDefinition:
    id: str
    labels: dict[str, str]
    fields: tuple[FieldDefinition, ...]


@dataclass(frozen=True)
class ProfileDefinition:
    sections: tuple[SectionDefinition, ...]
    # "sha256:<hex>" of the canonical JSON of the validated content: recorded on each run.
    content_hash: str

    def fields(self) -> tuple[FieldDefinition, ...]:
        return tuple(field for section in self.sections for field in section.fields)


def _content_hash(document: dict[str, Any]) -> str:
    content = {key: value for key, value in document.items() if key != "$comment"}
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def _first_duplicate(ids: list[str]) -> str | None:
    seen: set[str] = set()
    for value in ids:
        if value in seen:
            return value
        seen.add(value)
    return None


def _check_unique(path: Path, sections: list[dict[str, Any]]) -> None:
    label = f"{WHAT} {path}"
    duplicate = _first_duplicate([section["id"] for section in sections])
    if duplicate:
        raise ConfigurationError(
            f"{label} is not valid at sections: duplicate section id {duplicate!r}"
        )
    # A field id is unique across the whole definition: a buyer input is stored by field alone
    # (spec, Data model).
    duplicate = _first_duplicate([f["id"] for section in sections for f in section["fields"]])
    if duplicate:
        raise ConfigurationError(
            f"{label} is not valid at sections: duplicate field id {duplicate!r}"
        )


def load_profile_definition(path: Path | None = None) -> ProfileDefinition:
    """Read and validate the file. Raises ConfigurationError naming the file and the problem."""
    path = path or EXAMPLE_FILE
    document = load_content_file(path, SCHEMA_FILE, WHAT)
    sections = document["sections"]
    _check_unique(path, sections)
    return ProfileDefinition(
        sections=tuple(
            SectionDefinition(
                id=s["id"],
                labels=s["labels"],
                fields=tuple(
                    FieldDefinition(
                        id=f["id"],
                        labels=f["labels"],
                        kind=f["kind"],
                        extraction_hint=f["extraction_hint"],
                        certification=f.get("certification", False),
                        concerns_people=f.get("concerns_people", False),
                    )
                    for f in s["fields"]
                ),
            )
            for s in sections
        ),
        content_hash=_content_hash(document),
    )

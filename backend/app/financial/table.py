"""The financial country table, loaded at startup (spec, Financial evidence guidance; #26).

The file named by COUNTRY_TABLE_FILE is used; without that setting, the example shipped in
`app/content/` (clearly marked as an example, its rows not verified). A configured file is the
complete table and replaces the example: nothing is merged. It is validated against the published
schema (`app/content/country-table.schema.json`), then checked for a duplicate country and for
the four document types in every row. Any problem raises `ConfigurationError` naming the file and
the failing path, and nothing is kept. The real table belongs to the owner; the repository never
reads it from anywhere but the configured path.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from app.config import ConfigurationError
from app.content import CONTENT_DIR, load_content_file

SCHEMA_FILE: Final = "country-table.schema.json"
EXAMPLE_FILE: Final = CONTENT_DIR / "country-table.example.json"
WHAT: Final = "Country table file"
DOCUMENT_TYPES: Final = ("income_statement", "balance_sheet", "notes", "audit_report")


@dataclass(frozen=True)
class CountryRow:
    country: str
    registry_name: str
    registry_url: str
    last_checked: str  # YYYY-MM-DD
    access: dict[str, str]  # document type -> access status of the table


@dataclass(frozen=True)
class CountryTable:
    countries: dict[str, CountryRow]
    example: bool
    # "sha256:<hex>" of the canonical JSON of the validated content.
    content_hash: str

    def row(self, country: str | None) -> CountryRow | None:
        return self.countries.get((country or "").strip().upper())


def _content_hash(document: dict[str, Any]) -> str:
    content = {key: value for key, value in document.items() if key != "$comment"}
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def load_country_table(path: Path | None = None) -> CountryTable:
    """Read and validate the file. Raises ConfigurationError naming the file and the problem."""
    path = path or EXAMPLE_FILE
    document = load_content_file(path, SCHEMA_FILE, WHAT)
    label = f"{WHAT} {path}"
    countries: dict[str, CountryRow] = {}
    for index, entry in enumerate(document["countries"]):
        code = entry["country"]
        if code in countries:
            raise ConfigurationError(
                f"{label} is not valid at countries/{index}: duplicate country {code!r}"
            )
        types = [item["type"] for item in entry["documents"]]
        if sorted(types) != sorted(DOCUMENT_TYPES):
            raise ConfigurationError(
                f"{label} is not valid at countries/{index}/documents: "
                f"each of {', '.join(DOCUMENT_TYPES)} must appear once"
            )
        countries[code] = CountryRow(
            country=code,
            registry_name=entry["registry_name"],
            registry_url=entry["registry_url"],
            last_checked=entry["last_checked"],
            access={item["type"]: item["access"] for item in entry["documents"]},
        )
    return CountryTable(
        countries=countries,
        example=bool(document.get("example", False)),
        content_hash=_content_hash(document),
    )

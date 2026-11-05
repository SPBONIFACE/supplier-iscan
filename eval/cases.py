"""The reference sets: loading and validation.

Identity cases (#16) and retrieval cases (#20) are loaded from where those issues shipped them;
extraction cases (the three of #23) and the assessment format (#25) live in `eval/cases/`.
An empty or invalid set stops the command with a `CaseSetError` and a clear message.
"""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

CASE_SET_VERSION = "2026-11-05.1"

ROOT = Path(__file__).resolve().parent.parent
EXTRACTION_FILE = ROOT / "eval" / "cases" / "extraction.json"
ASSESSMENT_FILE = ROOT / "eval" / "cases" / "assessment.json"
IDENTITY_DIR = ROOT / "backend" / "tests" / "identity" / "cases"
RETRIEVAL_FILE = ROOT / "backend" / "tests" / "collection" / "cases" / "retrieval_cases.json"


class CaseSetError(Exception):
    """The reference sets cannot be used; the message says which file and why."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceCase(_Model):
    id: str = Field(min_length=1)
    url: str = Field(min_length=1)
    text: str = Field(min_length=1)


class ExtractionCase(_Model):
    id: str = Field(min_length=1)
    description: str
    fields: list[str] = Field(min_length=1)
    sources: list[SourceCase] = Field(min_length=1)
    # field -> accepted values (compared ignoring case), or None: no public evidence.
    expected: dict[str, list[str] | None]
    recorded: list[dict[str, Any]] = Field(default_factory=list)


class FactCase(_Model):
    id: str
    field: str
    value: str
    quote: str


class AssessmentExpected(_Model):
    cited_fact_ids: list[str] = Field(default_factory=list)
    cites_buyer_context: bool = False
    first_evaluation_assumption: bool = False
    no_recommendation: bool = False


class AssessmentCase(_Model):
    id: str = Field(min_length=1)
    description: str
    kind: Literal["statement", "recommendation", "natural_person"]
    facts: list[FactCase]
    buyer_criteria: str = ""
    buyer_context: str | None = None
    expected: AssessmentExpected
    recorded: list[list[dict[str, Any]]] = Field(default_factory=list)


@dataclass(frozen=True)
class CaseSet:
    identity: list[dict[str, Any]]
    extraction: list[ExtractionCase]
    assessment: list[AssessmentCase]
    retrieval: list[dict[str, Any]]
    version: str = CASE_SET_VERSION
    content_hash: str = field(default="")


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        raise CaseSetError(f"Case file {path} cannot be read") from None
    except ValueError:
        raise CaseSetError(f"Case file {path} is not valid JSON") from None


def _cases_of(path: Path, document: Any) -> list[Any]:
    if not isinstance(document, dict) or not isinstance(document.get("cases"), list):
        raise CaseSetError(f"Case file {path} is not valid: a 'cases' list is required")
    return list(document["cases"])


def _validated[T: BaseModel](path: Path, model: type[T], items: list[Any]) -> list[T]:
    out: list[T] = []
    for item in items:
        try:
            out.append(model.model_validate(item))
        except ValidationError as error:
            first = error.errors()[0]
            where = ".".join(str(part) for part in first.get("loc", ())) or "(case)"
            name = item.get("id", "?") if isinstance(item, dict) else "?"
            raise CaseSetError(
                f"Case file {path} is not valid: case {name!r}, {where}: {first.get('msg')}"
            ) from None
    ids = [item.model_dump().get("id") for item in out]
    if len(set(ids)) != len(ids):
        raise CaseSetError(f"Case file {path} is not valid: duplicate case id")
    return out


def _extraction_checks(path: Path, cases: list[ExtractionCase]) -> None:
    for case in cases:
        if set(case.expected) != set(case.fields):
            raise CaseSetError(
                f"Case file {path} is not valid: case {case.id!r}: 'expected' must name "
                "exactly the requested fields"
            )


def _identity(directory: Path) -> list[dict[str, Any]]:
    paths = sorted(directory.glob("*.json"))
    cases = []
    for path in paths:
        document = _read(path)
        steps = document.get("steps") if isinstance(document, dict) else None
        if (
            not isinstance(document, dict)
            or not isinstance(steps, list)
            or not steps
            or not isinstance(document.get("registry", {}).get("candidates"), list)
            or not isinstance(document.get("input", {}).get("name"), str)
        ):
            raise CaseSetError(
                f"Case file {path} is not valid: input.name, registry.candidates and steps"
            )
        cases.append(document)
    return cases


def _retrieval(path: Path) -> list[dict[str, Any]]:
    cases = _cases_of(path, _read(path))
    for case in cases:
        if not isinstance(case, dict) or not all(
            key in case for key in ("id", "legal_name", "lacking", "provider_urls", "pages")
        ):
            raise CaseSetError(
                f"Case file {path} is not valid: each case needs id, legal_name, lacking, "
                "provider_urls and pages"
            )
    return list(cases)


def load_case_set(
    *,
    identity_dir: Path = IDENTITY_DIR,
    extraction_file: Path = EXTRACTION_FILE,
    assessment_file: Path = ASSESSMENT_FILE,
    retrieval_file: Path = RETRIEVAL_FILE,
) -> CaseSet:
    identity = _identity(identity_dir)
    extraction_doc = _read(extraction_file)
    extraction = _validated(
        extraction_file, ExtractionCase, _cases_of(extraction_file, extraction_doc)
    )
    _extraction_checks(extraction_file, extraction)
    assessment_doc = _read(assessment_file)
    assessment = _validated(
        assessment_file, AssessmentCase, _cases_of(assessment_file, assessment_doc)
    )
    retrieval = _retrieval(retrieval_file)
    for name, cases in (
        ("identity", identity),
        ("extraction", extraction),
        ("retrieval", retrieval),
    ):
        if not cases:
            raise CaseSetError(f"The {name} case set is empty: nothing to evaluate")
    digest = hashlib.sha256(
        json.dumps(
            [identity, extraction_doc, assessment_doc, retrieval],
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    return CaseSet(identity, extraction, assessment, retrieval, content_hash=f"sha256:{digest}")

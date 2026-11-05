"""Metrics against the targets of spec § LLM features ("What good looks like"), and the
reviewer rating file. A metric is "pass", "fail", "not rated" or "not implemented", never a
silent pass."""

import csv
from dataclasses import dataclass
from pathlib import Path

from eval.areas import CaseResult

REVIEWER_TARGET = 0.8


@dataclass(frozen=True)
class Metric:
    area: str
    name: str
    target: str
    status: str  # pass | fail | not rated | not implemented | no data
    value: str = ""
    detail: str = ""


def _share(part: int, whole: int) -> float | None:
    return None if whole == 0 else part / whole


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.0f}%"


def _ratio_metric(
    area: str, name: str, target: str, part: int, whole: int, minimum: float
) -> Metric:
    share = _share(part, whole)
    if share is None:
        return Metric(area, name, target, "no data", "n/a", "nothing to measure")
    status = "pass" if share >= minimum else "fail"
    return Metric(area, name, target, status, f"{_percent(share)} ({part}/{whole})")


def _sum(results: list[CaseResult], key: str) -> int:
    return sum(result.counts.get(key, 0) for result in results if result.status == "ok")


def identity_metrics(results: list[CaseResult]) -> list[Metric]:
    return [
        _ratio_metric(
            "identity",
            "right company within 3 exchanges",
            "every confirmed case",
            _sum(results, "right_company"),
            _sum(results, "confirmations"),
            1.0,
        ),
        _ratio_metric(
            "identity",
            "no candidate discarded because of a hint",
            "every case",
            _sum(results, "candidates_kept"),
            sum(1 for result in results if result.status == "ok"),
            1.0,
        ),
    ]


def extraction_metrics(results: list[CaseResult]) -> list[Metric]:
    kept = _sum(results, "kept")
    expected = _sum(results, "expected_found")
    not_found = _sum(results, "expected_not_found")
    invented = _sum(results, "invented")
    return [
        _ratio_metric(
            "extraction",
            "kept quotes found in source",
            "100%",
            _sum(results, "quotes_in_source"),
            kept,
            1.0,
        ),
        _ratio_metric(
            "extraction",
            "accuracy (kept values that are right; a value for a field with no evidence is wrong)",
            ">= 90%",
            _sum(results, "correct"),
            kept,
            0.9,
        ),
        _ratio_metric(
            "extraction",
            "exhaustiveness (fields with evidence that were kept)",
            ">= 70%",
            _sum(results, "expected_found_kept"),
            expected,
            0.7,
        ),
        _ratio_metric(
            "extraction",
            "no value invented for a field with no public evidence",
            "100%",
            not_found - invented,
            not_found,
            1.0,
        ),
    ]


def retrieval_metrics(results: list[CaseResult]) -> list[Metric]:
    return [
        _ratio_metric(
            "retrieval",
            "returned URLs that can be verified",
            "every URL verifiable",
            _sum(results, "verified"),
            _sum(results, "returned"),
            1.0,
        )
    ]


def assessment_metrics(results: list[CaseResult]) -> list[Metric]:
    area = "assessment"
    without_context = _sum(results, "recommendations_without_context")
    return [
        _ratio_metric(
            area,
            "statements cite valid facts or name the missing evidence",
            "100%",
            _sum(results, "cite_valid"),
            _sum(results, "kept"),
            1.0,
        ),
        _ratio_metric(
            area,
            "recommendations without buyer context state the first-evaluation assumption",
            "100%",
            _sum(results, "with_assumption"),
            without_context,
            1.0,
        ),
        _ratio_metric(
            area,
            "no recommendation asserts a buyer situation that was not entered",
            "100%",
            without_context - _sum(results, "claims_unentered_context"),
            without_context,
            1.0,
        ),
        _ratio_metric(
            area,
            "no recommendation for a natural_person identity",
            "100%",
            _sum(results, "natural_person_clean"),
            _sum(results, "natural_person_cases"),
            1.0,
        ),
    ]


def reviewer_metric(path: Path | None) -> Metric:
    """ ">= 80% judged useful by a domain reviewer": from a file filled in by hand; without it,
    or without a single rated row, "not rated"."""
    name, target = "judged useful by a domain reviewer", ">= 80%"
    if path is None or not path.is_file():
        return Metric("assessment", name, target, "not rated", detail="no rating file")
    with path.open(encoding="utf-8", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if (row.get("useful") or "").strip().lower()]
    rated = [row for row in rows if row["useful"].strip().lower() in {"yes", "no"}]
    if not rated:
        return Metric("assessment", name, target, "not rated", detail="the rating file is empty")
    useful = sum(row["useful"].strip().lower() == "yes" for row in rated)
    share = useful / len(rated)
    return Metric(
        "assessment",
        name,
        target,
        "pass" if share >= REVIEWER_TARGET else "fail",
        f"{_percent(share)} ({useful}/{len(rated)})",
    )

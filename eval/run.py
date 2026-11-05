"""One evaluation run: all areas, the metrics, the report (Markdown and JSON)."""

import json
import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.profile_definition import ProfileDefinition
from app.prompts import PromptSet
from app.redaction import RedactionGate
from eval import metrics as metrics_module
from eval.areas import (
    CaseResult,
    Context,
    run_assessment,
    run_extraction,
    run_identity,
    run_retrieval,
)
from eval.backends import FAKE_NOTE, Backend, total_cost
from eval.cases import CaseSet
from eval.metrics import Metric

logger = logging.getLogger(__name__)

AREAS = ("identity", "extraction", "assessment", "retrieval")


@dataclass
class AreaReport:
    area: str
    implemented: bool
    metrics: list[Metric]
    cases: list[CaseResult] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_eur: str = "0"

    @property
    def errors(self) -> int:
        return sum(1 for case in self.cases if case.status == "error")


@dataclass
class Report:
    provider: str
    model_id: str
    config_id: str
    retrieval_config_id: str
    prompt_set_hash: str
    case_set_version: str
    case_set_hash: str
    date: str
    mode: str
    note: str
    areas: list[AreaReport]
    input_tokens: int
    output_tokens: int
    cost_eur: str

    @property
    def errors(self) -> int:
        return sum(area.errors for area in self.areas)

    def metrics(self) -> list[Metric]:
        return [metric for area in self.areas for metric in area.metrics]


def _money(amount: Decimal) -> str:
    return f"{amount:.4f}"


def _run_cases[T](
    items: list[T],
    case_id: Callable[[T], str],
    run: Callable[[T], CaseResult],
) -> list[CaseResult]:
    results = []
    for item in items:
        try:
            results.append(run(item))
        except Exception as error:  # noqa: BLE001 - a provider error marks the case, the rest go on
            # The type only (a message can quote a prompt or a response), plus a short text for
            # our own errors, which never hold case content.
            logger.warning("Case %s: error (%s)", case_id(item), type(error).__name__)
            results.append(CaseResult(case_id(item), "error", error=type(error).__name__))
    return results


def run_evaluation(
    cases: CaseSet,
    backend: Backend,
    prompts: PromptSet,
    gate: RedactionGate,
    definition: ProfileDefinition,
    ratings: Path | None = None,
    now: datetime | None = None,
) -> Report:
    context = Context(backend, prompts, gate, definition)
    areas: list[AreaReport] = []

    def measured(area: str, results: list[CaseResult], build: list[Metric], start: int) -> None:
        entries = backend.sink.entries[start:]
        areas.append(
            AreaReport(
                area,
                True,
                build,
                results,
                input_tokens=sum(e.input_tokens for e in entries),
                output_tokens=sum(e.output_tokens + e.reasoning_tokens for e in entries),
                cost_eur=_money(sum((e.cost for e in entries), Decimal(0))),
            )
        )

    start = len(backend.sink.entries)
    identity = _run_cases(cases.identity, lambda c: c["id"], lambda c: run_identity(c, context))
    measured("identity", identity, metrics_module.identity_metrics(identity), start)
    start = len(backend.sink.entries)
    extraction = _run_cases(cases.extraction, lambda c: c.id, lambda c: run_extraction(c, context))
    measured("extraction", extraction, metrics_module.extraction_metrics(extraction), start)
    start = len(backend.sink.entries)
    assessment = _run_cases(cases.assessment, lambda c: c.id, lambda c: run_assessment(c, context))
    measured(
        "assessment",
        assessment,
        [*metrics_module.assessment_metrics(assessment), metrics_module.reviewer_metric(ratings)],
        start,
    )
    start = len(backend.sink.entries)
    retrieval = _run_cases(cases.retrieval, lambda c: c["id"], lambda c: run_retrieval(c, context))
    measured("retrieval", retrieval, metrics_module.retrieval_metrics(retrieval), start)
    order = {name: index for index, name in enumerate(AREAS)}
    areas.sort(key=lambda area: order[area.area])
    entries = backend.sink.entries
    return Report(
        provider=backend.structuring_config.provider,
        model_id=backend.structuring_config.model_id,
        config_id=backend.structuring_config.id,
        retrieval_config_id=backend.retrieval_config.id,
        prompt_set_hash=prompts.content_hash,
        case_set_version=cases.version,
        case_set_hash=cases.content_hash,
        date=(now or datetime.now(UTC)).isoformat(timespec="seconds"),
        mode="fake" if backend.fake else "live",
        note=FAKE_NOTE if backend.fake else "live run: results describe this configuration",
        areas=areas,
        input_tokens=sum(e.input_tokens for e in entries),
        output_tokens=sum(e.output_tokens + e.reasoning_tokens for e in entries),
        cost_eur=_money(total_cost(backend.sink)),
    )


def to_json(report: Report) -> str:
    def default(value: Any) -> Any:
        raise TypeError(type(value).__name__)

    return json.dumps(asdict(report), indent=2, ensure_ascii=False, default=default) + "\n"


def to_markdown(report: Report) -> str:
    lines = [
        "# LLM evaluation report",
        "",
        f"**{report.note}**",
        "",
        f"- Provider: {report.provider}",
        f"- Model ID: {report.model_id}",
        f"- Configuration id: {report.config_id} (retrieval: {report.retrieval_config_id})",
        f"- Prompt-set hash: {report.prompt_set_hash}",
        f"- Date: {report.date}",
        f"- Case-set version: {report.case_set_version} ({report.case_set_hash})",
        f"- Tokens: {report.input_tokens} in, {report.output_tokens} out",
        f"- Cost: {report.cost_eur} EUR",
        f"- Cases in error: {report.errors}",
    ]
    if report.mode == "fake":
        lines += [
            "",
            "The model answers are recorded: this run proves the plumbing (prompts, schemas, "
            "redaction gate, grounding check, metrics) and says nothing about the quality of "
            "any model. No token is reported by the fake provider, so tokens and cost are 0.",
        ]
    for area in report.areas:
        lines += ["", f"## {area.area.capitalize()}", ""]
        lines += ["| Metric | Target | Result | Status |", "| --- | --- | --- | --- |"]
        for metric in area.metrics:
            result = metric.value or metric.detail
            lines.append(
                f"| {metric.name} | {metric.target} | {result} | **{metric.status.upper()}** |"
            )
        if area.implemented:
            lines += ["", f"Cases: {len(area.cases)}, errors: {area.errors}."]
            for case in area.cases:
                text = case.error and f"ERROR ({case.error})" or "ok"
                note = f" - {'; '.join(case.notes)}" if case.notes else ""
                lines.append(f"- {case.case_id}: {text}{note}")
    return "\n".join(lines) + "\n"


def write_report(report: Report, directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = report.date.replace(":", "").replace("-", "").replace("+0000", "Z")[:16]
    base = directory / f"eval-{report.config_id}-{stamp}"
    markdown, js = base.with_suffix(".md"), base.with_suffix(".json")
    markdown.write_text(to_markdown(report), encoding="utf-8")
    js.write_text(to_json(report), encoding="utf-8")
    return markdown, js

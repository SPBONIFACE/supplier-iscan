"""The evaluation harness (#22): a smoke run on the fake provider and the recorded cases, no
network, no key. It proves the plumbing (cases, prompts, schemas, redaction gate, grounding check,
metrics, report) and says nothing about the quality of any model."""

import json
from pathlib import Path
from typing import Any

import pytest
from eval.__main__ import main
from eval.areas import Context, run_extraction
from eval.backends import Backend, fake_backend, live_backend
from eval.cases import (
    EXTRACTION_FILE,
    AssessmentCase,
    CaseSetError,
    ExtractionCase,
    load_case_set,
)
from eval.metrics import reviewer_metric
from eval.run import Report, run_evaluation, to_json, to_markdown, write_report

from app.config import ConfigurationError
from app.profile_definition import load_profile_definition
from app.prompts import PromptSet, load_prompt_set
from app.providers import Providers, ProvidersNotReady
from app.providers.errors import ProviderCallError
from app.providers.fake import FakeRetrievalAdapter, FakeStructuringAdapter, fake_adapters
from app.redaction import OMISSION, RedactionGate


def _run(backend: Backend | None = None, prompts: PromptSet | None = None) -> Report:
    return run_evaluation(
        load_case_set(),
        backend or fake_backend(),
        prompts or load_prompt_set(),
        RedactionGate(lambda: ()),
        load_profile_definition(),
    )


def _status(report: Report) -> dict[str, str]:
    return {metric.name: metric.status for metric in report.metrics()}


def test_the_smoke_run_measures_every_implemented_area() -> None:
    report = _run()
    assert report.errors == 0
    assert report.mode == "fake" and report.note == "fake provider: plumbing only"
    status = _status(report)
    assert status["right company within 3 exchanges"] == "pass"
    assert status["no candidate discarded because of a hint"] == "pass"
    assert status["kept quotes found in source"] == "pass"
    assert status[next(name for name in status if name.startswith("accuracy"))] == "pass"
    assert status[next(name for name in status if name.startswith("exhaustiveness"))] == "pass"
    # The recorded retrieval set holds an address that cannot be verified: the metric shows it.
    assert status["returned URLs that can be verified"] == "fail"


def test_the_assessment_area_is_measured_and_the_reviewer_metric_is_not_rated() -> None:
    report = _run()
    status = _status(report)
    assessment = [
        value for name, value in status.items() if "recommend" in name or "statements cite" in name
    ]
    assert len(assessment) == 4 and set(assessment) == {"pass"}
    assert status["judged useful by a domain reviewer"] == "not rated"
    area = next(item for item in report.areas if item.area == "assessment")
    assert area.implemented and len(area.cases) == 10 and area.errors == 0


def test_the_buyer_situation_guard_and_fit_cases_are_measured() -> None:
    report = _run()
    status = _status(report)
    assert (
        status["no kept statement contains wording that asserts an unentered buyer situation"]
        == "pass"
    )
    assert status["fit is drafted only when criteria were entered"] == "pass"
    area = next(item for item in report.areas if item.area == "assessment")
    cases = {case.case_id: case for case in area.cases}
    guard = cases["recommendations-unentered-buyer-situation"]
    assert guard.counts["kept"] == 1 and guard.counts["kept_with_forbidden_phrase"] == 0
    assert any("2 statement(s) rejected" in note for note in guard.notes)
    assert cases["fit-with-criteria"].counts["kept"] == 2
    assert (
        cases["fit-without-criteria"].counts["kept"] == 0
        and not cases["fit-without-criteria"].notes
    )


def test_the_report_names_what_it_was_run_with(tmp_path: Path) -> None:
    report = _run()
    markdown, json_file = write_report(report, tmp_path / "reports")
    text = markdown.read_text(encoding="utf-8")
    assert "fake provider: plumbing only" in text
    assert "says nothing about the quality of any model" in text
    document = json.loads(json_file.read_text(encoding="utf-8"))
    assert document["provider"] == "google" and document["model_id"] == "fake-recorded"
    assert document["config_id"] == "fake"
    assert document["prompt_set_hash"] == load_prompt_set().content_hash
    assert document["case_set_version"] and document["date"]
    assert {"input_tokens", "output_tokens", "cost_eur"} <= set(document)
    assert json.loads(to_json(report)) == document and to_markdown(report) == text


def test_the_injected_instruction_is_discarded_by_the_grounding_check() -> None:
    report = _run()
    extraction = next(area for area in report.areas if area.area == "extraction")
    edge = next(case for case in extraction.cases if case.case_id.startswith("edge"))
    assert edge.counts["grounding_discarded"] == 1
    assert edge.counts["invented"] == 0
    negative = next(case for case in extraction.cases if case.case_id == "negative-not-found")
    assert negative.counts["kept"] == 0 and negative.counts["expected_not_found"] == 3


def test_the_three_extraction_cases_and_the_shipped_cases_are_loaded() -> None:
    cases = load_case_set()
    assert [case.id for case in cases.extraction] == [
        "happy-path",
        "negative-not-found",
        "edge-accents-cjk-injection",
    ]
    assert len(cases.identity) == 3 and len(cases.retrieval) == 2
    assert [case.id for case in cases.assessment] == [
        "happy-swot-and-gap",
        "happy-recommendations-first-evaluation",
        "recommendations-with-buyer-context",
        "negative-all-not-found",
        "edge-management-facts",
        "edge-natural-person",
        "edge-injected-quote",
        "recommendations-unentered-buyer-situation",
        "fit-with-criteria",
        "fit-without-criteria",
    ]


def _fake_with(adapter: FakeStructuringAdapter, backend: Backend) -> None:
    def providers(structuring: Any = None, retrieval: Any = None) -> Providers:
        return Providers(
            backend.catalogue,
            backend.environ,
            fake_adapters(
                backend.catalogue,
                structuring=adapter,
                retrieval=FakeRetrievalAdapter(list(retrieval or [])),
            ),
            meter=backend.meter,
        )

    backend.providers = providers  # type: ignore[method-assign]


def test_a_provider_error_marks_the_case_and_the_others_continue() -> None:
    backend = fake_backend()
    error = ProviderCallError(provider="google", config_id="fake", kind="timeout")
    _fake_with(FakeStructuringAdapter([error] * 10), backend)
    report = _run(backend=backend)
    identity = next(area for area in report.areas if area.area == "identity")
    extraction = next(area for area in report.areas if area.area == "extraction")
    retrieval = next(area for area in report.areas if area.area == "retrieval")
    assert [case.status for case in identity.cases] == ["error"] * 3
    assert [case.status for case in extraction.cases] == ["error"] * 3
    # Retrieval uses no structuring answer: it still ran.
    # Assessment: the eight cases that call the model fail; the natural-person case and the fit
    # case with no criteria call none.
    assessment = next(area for area in report.areas if area.area == "assessment")
    assert assessment.errors == 8
    assert retrieval.errors == 0 and report.errors == 14
    assert "ERROR" in to_markdown(report)


def test_only_redacted_text_reaches_the_model() -> None:
    source = json.loads(EXTRACTION_FILE.read_text(encoding="utf-8"))["cases"][0]
    source["sources"][0]["text"] += " Contact: someone@brightwell-components.example"
    adapter = FakeStructuringAdapter([json.dumps(source["recorded"][0])])
    backend = fake_backend()
    _fake_with(adapter, backend)
    case = ExtractionCase.model_validate(source)
    context = Context(
        backend, load_prompt_set(), RedactionGate(lambda: ()), load_profile_definition()
    )
    run_extraction(case, context)
    sent = adapter.calls[0].data.text
    assert "someone@" not in sent and OMISSION in sent


def test_an_invalid_case_set_stops_with_a_message(tmp_path: Path) -> None:
    broken = tmp_path / "extraction.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(CaseSetError, match="is not valid JSON"):
        load_case_set(extraction_file=broken)
    broken.write_text(json.dumps({"cases": [{"id": "x"}]}), encoding="utf-8")
    with pytest.raises(CaseSetError, match="case 'x'"):
        load_case_set(extraction_file=broken)


def test_an_empty_case_set_stops_with_a_message(tmp_path: Path) -> None:
    empty = tmp_path / "extraction.json"
    empty.write_text(json.dumps({"cases": []}), encoding="utf-8")
    with pytest.raises(CaseSetError, match="extraction case set is empty"):
        load_case_set(extraction_file=empty)
    with pytest.raises(CaseSetError, match="identity case set is empty"):
        load_case_set(identity_dir=tmp_path / "none")


def test_the_assessment_case_format_is_validated() -> None:
    good = {
        "id": "no-context",
        "description": "A recommendation without buyer context",
        "kind": "recommendation",
        "facts": [{"id": "f1", "field": "founding_year", "value": "1987", "quote": "founded 1987"}],
        "buyer_context": None,
        "expected": {"cited_fact_ids": ["f1"], "first_evaluation_assumption": True},
    }
    assert AssessmentCase.model_validate(good).expected.first_evaluation_assumption
    with pytest.raises(ValueError, match="kind"):
        AssessmentCase.model_validate({**good, "kind": "poem"})


def test_an_invalid_prompt_set_stops_the_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "prompts.json"
    bad.write_text("{}", encoding="utf-8")
    assert main(["--config", "fake", "--prompts", str(bad), "--out", str(tmp_path)]) == 2
    assert "Prompt set file" in capsys.readouterr().err


def test_a_configuration_that_is_not_approved_stops_the_command() -> None:
    with pytest.raises(ConfigurationError, match="not in the approved list"):
        live_backend("no-such-configuration", {})
    # The shipped list has every configuration disabled and unverified; no key is set either.
    with pytest.raises(ProvidersNotReady):
        live_backend("", {})


def test_the_reviewer_metric_is_computed_from_the_file(tmp_path: Path) -> None:
    ratings = tmp_path / "ratings.csv"
    ratings.write_text(
        "case_id,statement_id,useful,reviewer,comment\n"
        "a,1,yes,R,\na,2,yes,R,\na,3,yes,R,\na,4,yes,R,\na,5,no,R,\n",
        encoding="utf-8",
    )
    assert reviewer_metric(ratings).status == "pass"
    ratings.write_text(ratings.read_text() + "a,6,no,R,\n", encoding="utf-8")
    assert reviewer_metric(ratings).status == "fail"
    ratings.write_text("case_id,statement_id,useful,reviewer,comment\n", encoding="utf-8")
    assert reviewer_metric(ratings).status == "not rated"
    assert reviewer_metric(tmp_path / "missing.csv").status == "not rated"
    assert reviewer_metric(None).status == "not rated"


def test_the_prompt_set_hash_is_the_one_of_the_named_set(tmp_path: Path) -> None:
    source = Path(__file__).parents[2] / "app" / "content" / "prompt-set.example.json"
    named = json.loads(source.read_text(encoding="utf-8"))
    named["prompts"][0]["version"] = "other-1"
    path = tmp_path / "set.json"
    path.write_text(json.dumps(named), encoding="utf-8")
    other = load_prompt_set(path)
    assert _run(prompts=other).prompt_set_hash == other.content_hash
    assert other.content_hash != load_prompt_set().content_hash

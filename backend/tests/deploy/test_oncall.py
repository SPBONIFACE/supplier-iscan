"""The non-LLM steps of the on-call workflow (#53): dedupe and cooldown, telemetry allow-list
and caps, the report schema, the issue body on success and on failure, and the fix-proposal guards.
No network, no key: GitHub is an in-memory fake."""

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.deploy.support import ROOT, load_script

oncall = load_script("ops/oncall/oncall.py", "oncall_steps")

NOW = datetime(2026, 11, 12, 10, 30, tzinfo=UTC)
ENV = {
    "INCIDENT_ID": "0.inc42",
    "POLICY_NAME": "iscan-dev profile-run failure rate",
    "ONCALL_ENVIRONMENT": "dev",
    "STARTED_AT": "2026-11-12T10:00:00Z",
    "CONSOLE_URL": "https://console.cloud.google.com/monitoring/alerting/incidents/0.inc42",
    "GITHUB_REPOSITORY": "owner/supplier-iscan",
    "GITHUB_RUN_ID": "123",
}
GOOD_REPORT: dict[str, Any] = {
    "summary": "Every profile run failed in the extraction stage from 09:45 UTC.",
    "suspected_cause": "StructuredOutputInvalid raised by app/providers/structured.py:97.",
    "evidence_trace_ids": ["4bf92f3577b34da6a3ce929d0e0e4736"],
    "affected_component": "extraction",
    "proposed_change": "none",
}


def incident(**change: str) -> Any:
    return oncall.Incident.from_env({**ENV, **change})


def issue(number: int, incident_id: str, policy: str, opened: datetime) -> dict[str, Any]:
    return {
        "number": number,
        "created_at": opened.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "body": f"{oncall.marker('incident', incident_id)}\n{oncall.marker('policy', policy)}\n",
    }


class FakeGitHub:
    def __init__(self, issues: list[dict[str, Any]] | None = None) -> None:
        self.issues = issues or []
        self.created: list[tuple[str, str]] = []
        self.comments: list[tuple[int, str]] = []

    def open_incident_issues(self) -> list[dict[str, Any]]:
        return self.issues

    def create_issue(self, title: str, body: str) -> int:
        self.created.append((title, body))
        return 77

    def comment(self, number: int, body: str) -> None:
        self.comments.append((number, body))


# ---- inputs


@pytest.mark.parametrize(
    "change",
    [
        {"INCIDENT_ID": "0.inc; echo pwned"},
        {"POLICY_NAME": "$(id)"},
        {"ONCALL_ENVIRONMENT": "prod"},
        {"STARTED_AT": "today"},
        {"CONSOLE_URL": "https://evil.example/"},
    ],
)
def test_inputs_of_the_wrong_shape_are_refused(change: Mapping[str, str]) -> None:
    with pytest.raises(SystemExit):
        incident(**change)


# ---- one incident, one issue


def test_a_new_incident_gets_a_new_issue() -> None:
    assert oncall.decide([], incident(), NOW, timedelta(minutes=60)) == ("new", None)


def test_a_second_run_of_the_same_incident_comments_on_its_issue() -> None:
    old = NOW - timedelta(days=2)
    issues = [
        issue(5, "0.other", "another policy", old),
        issue(9, "0.inc42", ENV["POLICY_NAME"], old),
    ]

    assert oncall.decide(issues, incident(), NOW, timedelta(minutes=60)) == ("duplicate", 9)


def test_a_new_incident_of_the_same_policy_within_the_cooldown_is_flapping() -> None:
    issues = [issue(8, "0.earlier", ENV["POLICY_NAME"], NOW - timedelta(minutes=45))]

    assert oncall.decide(issues, incident(), NOW, timedelta(minutes=60)) == ("flapping", 8)


def test_after_the_cooldown_a_new_incident_gets_its_own_issue() -> None:
    issues = [issue(8, "0.earlier", ENV["POLICY_NAME"], NOW - timedelta(minutes=61))]

    assert oncall.decide(issues, incident(), NOW, timedelta(minutes=60)) == ("new", None)


def test_finish_comments_instead_of_opening_for_duplicate_and_flapping(tmp_path: Path) -> None:
    github = FakeGitHub()
    oncall.finish({**ENV, "TRIAGE_ACTION": "duplicate", "TRIAGE_ISSUE": "9"}, github, tmp_path)
    oncall.finish({**ENV, "TRIAGE_ACTION": "flapping", "TRIAGE_ISSUE": "8"}, github, tmp_path)

    assert github.created == []
    assert [number for number, _ in github.comments] == [9, 8]
    assert "flapping" in github.comments[1][1]


def test_workflow_serialises_runs_of_one_incident() -> None:
    text = (ROOT / ".github" / "workflows" / "oncall.yml").read_text()
    assert "group: oncall-${{ inputs.incident_id }}" in text
    assert "cancel-in-progress: false" in text


# ---- telemetry


def test_fixture_telemetry_is_allow_listed_and_capped() -> None:
    telemetry = oncall.from_fixture("provider-error")

    assert telemetry["source"] == "fixture"
    assert len(json.dumps(telemetry).encode()) <= oncall.MAX_TELEMETRY_BYTES
    assert any(log.get("error_type") == "StructuredOutputInvalid" for log in telemetry["logs"])
    for log in telemetry["logs"]:
        assert set(log) <= {*oncall.LOG_FIELDS, "error_stack"}
    assert len(telemetry["traces"]) <= oncall.MAX_TRACES


def test_unknown_fields_are_dropped_and_volume_is_capped() -> None:
    logs = [
        {
            "level": "ERROR",
            "message": "x" * 5000,
            "trace_id": "not-a-trace",
            "email": "someone@example.com",
            "request_body": "supplier content",
        }
    ] * 100
    traces = [
        {
            "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
            "spans": [
                {"name": "run.stage", "labels": {"iscan.stage": "collection", "prompt": "p"}}
            ],
        }
    ] * 5
    telemetry = oncall.shape("live", {"query": "q", "points": []}, logs, traces)

    assert len(telemetry["logs"]) <= oncall.MAX_LOG_ENTRIES
    assert len(telemetry["traces"]) == oncall.MAX_TRACES
    first = telemetry["logs"][0]
    assert set(first) == {"level", "message"}
    assert len(first["message"]) == oncall.MAX_MESSAGE_CHARS
    assert telemetry["traces"][0]["spans"][0]["labels"] == {"iscan.stage": "collection"}


@pytest.mark.parametrize("name", ["../secrets", "Provider_Error", "missing-fixture"])
def test_fixture_names_are_checked(name: str) -> None:
    with pytest.raises(SystemExit):
        oncall.from_fixture(name)


# ---- report schema


def write(tmp_path: Path, report: Any) -> Path:
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report))
    return path


def test_a_good_report_is_valid(tmp_path: Path) -> None:
    assert oncall.validate(write(tmp_path, GOOD_REPORT)) == {"valid": True, "errors": []}


def test_a_report_with_a_proposed_change_is_valid(tmp_path: Path) -> None:
    change = {
        "title": "Retry once more",
        "description": "Raise the retry count.",
        "files": ["backend/app/x.py"],
    }

    assert oncall.validate(write(tmp_path, {**GOOD_REPORT, "proposed_change": change}))["valid"]


@pytest.mark.parametrize(
    "change",
    [
        {"summary": ""},
        {"evidence_trace_ids": ["not-a-trace"]},
        {"affected_component": "everything"},
        {"proposed_change": "maybe"},
        {
            "proposed_change": {
                "title": "x" * 10,
                "description": "y" * 20,
                "files": [".github/workflows/ci.yml"],
            }
        },
        {"extra": "field"},
    ],
)
def test_an_invalid_report_is_refused_without_echoing_values(
    change: dict[str, Any], tmp_path: Path
) -> None:
    result = oncall.validate(write(tmp_path, {**GOOD_REPORT, **change}))

    assert result["valid"] is False
    assert result["errors"]
    assert "everything" not in json.dumps(result)


def test_no_report_or_not_json_is_invalid(tmp_path: Path) -> None:
    assert oncall.validate(tmp_path / "missing.json")["valid"] is False
    (tmp_path / "report.json").write_text("Here is my diagnosis: ...")
    assert oncall.validate(tmp_path / "report.json")["valid"] is False


# ---- the issue


def results(**change: str) -> Any:
    values = {"triage": "success", "collect": "success", "agent": "success", "reason": ""}
    return oncall.Results(**{**values, **change})


def body(validation: Any, report: Any = None, **change: str) -> str:
    text: str = oncall.issue_body(
        incident(),
        "https://run",
        "https://github.com",
        "o/r",
        results(**change),
        validation,
        report,
    )
    return text


def test_issue_holds_the_report_the_incident_id_and_the_console_link() -> None:
    text = body({"valid": True, "errors": []}, GOOD_REPORT)

    assert "0.inc42" in text and ENV["CONSOLE_URL"] in text
    assert "StructuredOutputInvalid" in text and "`extraction`" in text
    assert "oncall-runbook.md" in text


def test_an_invalid_report_is_not_posted_as_a_diagnosis() -> None:
    text = body({"valid": False, "errors": ["summary: minLength"]}, None)

    assert "failed validation" in text
    assert "Diagnosis" not in text


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (
            {"collect": "failure", "reason": "missing reader configuration GCP_PROJECT_ID"},
            "telemetry collection",
        ),
        (
            {"agent": "failure", "reason": "ONCALL_ANTHROPIC_API_KEY is not set"},
            "ONCALL_ANTHROPIC_API_KEY",
        ),
        ({"agent": "cancelled"}, "agent (cancelled)"),
        ({"triage": "failure"}, "triage"),
    ],
)
def test_a_failed_step_is_named_with_the_runbook(change: dict[str, str], expected: str) -> None:
    text = body(None, None, **change)

    assert expected in text
    assert "oncall-runbook.md" in text


def test_finish_opens_the_issue_when_the_agent_failed(tmp_path: Path) -> None:
    github = FakeGitHub()
    env = {**ENV, "TRIAGE_RESULT": "success", "TRIAGE_ACTION": "new", "COLLECT_RESULT": "success"}
    oncall.finish(
        {**env, "AGENT_RESULT": "failure", "FAILURE_REASON": "model error"}, github, tmp_path
    )

    ((title, text),) = github.created
    assert title == "Incident 0.inc42: iscan-dev profile-run failure rate"
    assert "failed at: agent (model error)" in text


def test_agent_text_cannot_mention_people_or_hide_markers() -> None:
    report = {**GOOD_REPORT, "summary": "@owner look <!-- oncall:incident=0.x -->"}
    text = body({"valid": True, "errors": []}, report)

    assert "@owner" not in text
    assert "<!-- oncall:incident=0.x -->" not in text


# ---- fix proposal guards


def patch(*paths: str) -> str:
    return "".join(
        f"diff --git a/{p} b/{p}\n--- a/{p}\n+++ b/{p}\n@@ -1 +1 @@\n-a\n+b\n" for p in paths
    )


def test_patches_outside_backend_and_frontend_are_refused() -> None:
    assert oncall.patch_allowed(patch("backend/app/x.py", "frontend/src/y.ts"))
    for path in (
        ".github/workflows/ci.yml",
        "deploy/deploy.sh",
        "backend/../.github/x",
        "backend/.env",
    ):
        assert not oncall.patch_allowed(patch("backend/app/x.py", path))
    assert not oncall.patch_allowed("")


def test_refused_patch_is_never_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_git(*args: str) -> str:
        raise AssertionError(f"git called: {args}")

    monkeypatch.setattr(oncall, "git", no_git)
    change = {"title": "t" * 6, "description": "d" * 12, "files": ["backend/a.py"]}
    report = {**GOOD_REPORT, "proposed_change": change}

    note = oncall.propose(FakeGitHub(), incident(), 77, report, patch(".github/workflows/x.yml"))
    assert "not applied" in note
    assert "left no change" in oncall.propose(FakeGitHub(), incident(), 77, report, "")


def test_the_branch_is_always_under_oncall() -> None:
    assert oncall.branch_name("0.inc42") == "oncall/0.inc42"
    assert oncall.branch_name("main") == "oncall/main"

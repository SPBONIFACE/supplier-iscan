"""The non-LLM steps of the on-call workflow (#53, .github/workflows/oncall.yml).

    python3 ops/oncall/oncall.py triage           one incident, one issue; cooldown (flapping)
    python3 ops/oncall/oncall.py collect OUT      telemetry (live, read-only account; or a fixture)
    python3 ops/oncall/oncall.py validate REPORT  check the agent's report (report.schema.json)
    python3 ops/oncall/oncall.py finish           open or update the incident issue; the fix PR

Standard library only, except `validate`, which uses the approved `jsonschema` (run with the
backend's locked environment). Every input comes from environment variables (the workflow
passes its inputs through `env:`, never into a command line). Telemetry keeps allow-listed fields
only and is capped. This script never merges, never deploys and never pushes to main: it pushes
one branch, `oncall/<incident-id>`, and opens a pull request for the owner.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RUNBOOK = "_docs/operations/oncall-runbook.md"
LABEL = "incident"

# Caps on what reaches the agent (and the issue).
MAX_LOG_ENTRIES = 30
MAX_TRACES = 3
MAX_SPANS_PER_TRACE = 40
MAX_MESSAGE_CHARS = 400
MAX_STACK_FRAMES = 15
MAX_TELEMETRY_BYTES = 64 * 1024
MAX_PATCH_BYTES = 100 * 1024
LOOKBACK_MINUTES = 60

LOG_FIELDS = ("timestamp", "level", "service", "logger", "message", "trace_id", "error_type")
SPAN_LABELS = (
    "iscan.stage",
    "iscan.status",
    "iscan.outcome",
    "iscan.dependency",
    "iscan.role",
    "iscan.provider",
    "iscan.model",
    "http.route",
    "http.response.status_code",
    "exception.type",
    "g.co/status/code",
)
INCIDENT_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")
POLICY_NAME = re.compile(r"[A-Za-z0-9 ._:()/-]{1,128}")
CONSOLE_URL = re.compile(r"https://console\.cloud\.google\.com/\S{1,900}")
FIXTURE = re.compile(r"[a-z0-9-]{1,64}")
TRACE_ID = re.compile(r"[0-9a-f]{32}")
ALLOWED_PATCH_ROOTS = ("backend/", "frontend/")

Http = Callable[[str, str, Mapping[str, str], bytes | None], Any]


# ---------------------------------------------------------------- inputs


@dataclass(frozen=True)
class Incident:
    incident_id: str
    policy_name: str
    environment: str
    started_at: str
    console_url: str

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Incident:
        incident_id = env.get("INCIDENT_ID", "").strip()
        policy_name = env.get("POLICY_NAME", "").strip()
        environment = env.get("ONCALL_ENVIRONMENT", "").strip()
        started_at = env.get("STARTED_AT", "").strip()
        console_url = env.get("CONSOLE_URL", "").strip()
        if not INCIDENT_ID.fullmatch(incident_id):
            raise SystemExit("incident_id: letters, digits, '.', '_' or '-' only (at most 128)")
        if not POLICY_NAME.fullmatch(policy_name):
            raise SystemExit("policy_name: letters, digits, spaces and ._:()/- only (at most 128)")
        if environment != "dev":
            raise SystemExit("environment: the on-call agent runs for dev only (#53)")
        try:
            datetime.strptime(started_at, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            raise SystemExit("started_at: a UTC time such as 2026-11-12T10:00:00Z") from None
        if console_url and not CONSOLE_URL.fullmatch(console_url):
            raise SystemExit("console_url: a https://console.cloud.google.com/ address, or empty")
        return cls(incident_id, policy_name, environment, started_at, console_url)

    @property
    def start(self) -> datetime:
        return datetime.strptime(self.started_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def write_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    line = f"{name}={value}\n"
    if path:
        with open(path, "a", encoding="utf-8") as output:
            output.write(line)
    else:
        sys.stdout.write(line)


# ---------------------------------------------------------------- GitHub


def github_http(token: str) -> Http:
    def call(method: str, url: str, headers: Mapping[str, str], body: bytes | None) -> Any:
        request = urllib.request.Request(  # noqa: S310 - https address built from constants
            url,
            data=body,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "iscan-oncall",
                **headers,
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            raw = response.read()
            return json.loads(raw) if raw else None

    return call


class GitHub:
    def __init__(self, repository: str, http: Http) -> None:
        self.base = f"https://api.github.com/repos/{repository}"
        self.http = http

    def _call(self, method: str, path: str, payload: Any = None) -> Any:
        body = None if payload is None else json.dumps(payload).encode()
        headers = {} if body is None else {"Content-Type": "application/json"}
        return self.http(method, f"{self.base}{path}", headers, body)

    def open_incident_issues(self) -> list[dict[str, Any]]:
        found = self._call("GET", f"/issues?labels={LABEL}&state=open&per_page=100")
        return [issue for issue in found or [] if "pull_request" not in issue]

    def create_issue(self, title: str, body: str) -> int:
        issue = self._call("POST", "/issues", {"title": title, "body": body, "labels": [LABEL]})
        return int(issue["number"])

    def comment(self, number: int, body: str) -> None:
        self._call("POST", f"/issues/{number}/comments", {"body": body})

    def open_pull_request(self, title: str, head: str, body: str) -> int:
        pull = self._call(
            "POST", "/pulls", {"title": title, "head": head, "base": "main", "body": body}
        )
        return int(pull["number"])


# ---------------------------------------------------------------- triage


def marker(kind: str, value: str) -> str:
    return f"<!-- oncall:{kind}={value} -->"


def decide(
    issues: Sequence[Mapping[str, Any]],
    incident: Incident,
    now: datetime,
    cooldown: timedelta,
) -> tuple[str, int | None]:
    """("duplicate", n): this incident already has open issue n; ("flapping", n): an issue of the
    same policy opened within the cooldown is still open; ("new", None) otherwise."""
    for issue in issues:
        if marker("incident", incident.incident_id) in (issue.get("body") or ""):
            return "duplicate", int(issue["number"])
    for issue in issues:
        if marker("policy", incident.policy_name) not in (issue.get("body") or ""):
            continue
        opened = datetime.strptime(issue["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        if now - opened <= cooldown:
            return "flapping", int(issue["number"])
    return "new", None


def triage(env: Mapping[str, str], github: GitHub, now: datetime) -> tuple[str, int | None]:
    incident = Incident.from_env(env)
    minutes = int(env.get("COOLDOWN_MINUTES", "").strip() or "60")
    return decide(github.open_incident_issues(), incident, now, timedelta(minutes=minutes))


# ---------------------------------------------------------------- telemetry


def clean_log(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Allow-listed fields of one JSON log line; the message and the stack are capped."""
    kept: dict[str, Any] = {
        key: str(entry[key])[:MAX_MESSAGE_CHARS] for key in LOG_FIELDS if key in entry
    }
    if "trace_id" in kept and not TRACE_ID.fullmatch(kept["trace_id"]):
        del kept["trace_id"]
    stack = entry.get("error_stack")
    if isinstance(stack, list):
        kept["error_stack"] = [str(frame)[:200] for frame in stack[-MAX_STACK_FRAMES:]]
    return kept


def clean_span(span: Mapping[str, Any]) -> dict[str, Any]:
    labels = span.get("labels") or {}
    return {
        "name": str(span.get("name", ""))[:100],
        "duration_ms": span.get("duration_ms"),
        "labels": {key: str(labels[key])[:100] for key in SPAN_LABELS if key in labels},
    }


def cap(telemetry: dict[str, Any]) -> dict[str, Any]:
    """Drop the oldest log entries until the whole fits MAX_TELEMETRY_BYTES."""
    while len(json.dumps(telemetry).encode()) > MAX_TELEMETRY_BYTES and telemetry["logs"]:
        telemetry["logs"].pop()
    return telemetry


def shape(
    source: str, rate: Mapping[str, Any], logs: Sequence[Any], traces: Sequence[Any]
) -> dict[str, Any]:
    return cap(
        {
            "source": source,
            "failure_rate": {
                "query": str(rate.get("query", "")),
                "points": [
                    [str(time), str(value)] for time, value in list(rate.get("points", []))[-60:]
                ],
            },
            "logs": [
                clean_log(entry) for entry in logs[:MAX_LOG_ENTRIES] if isinstance(entry, dict)
            ],
            "traces": [
                {
                    "trace_id": str(trace.get("trace_id", "")),
                    "spans": [clean_span(s) for s in trace.get("spans", [])[:MAX_SPANS_PER_TRACE]],
                }
                for trace in traces[:MAX_TRACES]
                if isinstance(trace, dict) and TRACE_ID.fullmatch(str(trace.get("trace_id", "")))
            ],
        }
    )


def from_fixture(name: str, directory: Path = HERE / "fixtures") -> dict[str, Any]:
    if not FIXTURE.fullmatch(name):
        raise SystemExit("fixture: lower-case letters, digits and '-' only")
    path = directory / f"{name}.json"
    if not path.is_file():
        raise SystemExit(f"fixture {name!r} does not exist in ops/oncall/fixtures")
    data = json.loads(path.read_text())
    return shape("fixture", data["failure_rate"], data["logs"], data["traces"])


def google_http(token: str) -> Http:
    def call(method: str, url: str, headers: Mapping[str, str], body: bytes | None) -> Any:
        request = urllib.request.Request(  # noqa: S310 - Google API addresses built from constants
            url,
            data=body,
            method=method,
            headers={"Authorization": f"Bearer {token}", **headers},
        )
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return json.loads(response.read())

    return call


def rate_query(environment: str) -> str:
    config = json.loads(
        (ROOT / "deploy" / "monitoring" / f"failure-rate.{environment}.json").read_text()
    )
    window, selector = f"{config['window_minutes']}m", config.get("label_selector", "")
    failed = ",".join(filter(None, ['iscan_status="failed"', selector]))
    return (
        f"sum(increase(iscan_runs_finished_total{{{failed}}}[{window}])) / "
        f"sum(increase(iscan_runs_finished_total{{{selector}}}[{window}]))"
    )


def from_cloud(project: str, incident: Incident, http: Http, now: datetime) -> dict[str, Any]:
    """Live telemetry with the read-only account: no LLM is involved here."""
    since = min(incident.start, now) - timedelta(minutes=LOOKBACK_MINUTES)
    query = rate_query(incident.environment)
    params = urllib.parse.urlencode(
        {"query": query, "start": since.timestamp(), "end": now.timestamp(), "step": "60s"}
    )
    prometheus = (
        f"https://monitoring.googleapis.com/v1/projects/{project}/location/global/prometheus"
        f"/api/v1/query_range?{params}"
    )
    result = http("GET", prometheus, {}, None).get("data", {}).get("result", [])
    points = [
        [datetime.fromtimestamp(float(t), UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), value]
        for series in result[:1]
        for t, value in series.get("values", [])
    ]
    env = incident.environment
    log_filter = (
        f'timestamp>="{since.strftime("%Y-%m-%dT%H:%M:%SZ")}" '
        'AND jsonPayload.level=("WARNING" OR "ERROR" OR "CRITICAL") '
        f'AND (resource.labels.service_name="iscan-api-{env}" '
        f'OR resource.labels.worker_pool_name="iscan-worker-{env}")'
    )
    listed = http(
        "POST",
        "https://logging.googleapis.com/v2/entries:list",
        {"Content-Type": "application/json"},
        json.dumps(
            {
                "resourceNames": [f"projects/{project}"],
                "filter": log_filter,
                "orderBy": "timestamp desc",
                "pageSize": MAX_LOG_ENTRIES,
            }
        ).encode(),
    )
    logs = [entry.get("jsonPayload", {}) for entry in listed.get("entries", [])]
    failing = [
        log["trace_id"]
        for log in logs
        if log.get("level") in ("ERROR", "CRITICAL")
        and TRACE_ID.fullmatch(str(log.get("trace_id")))
    ]
    traces = []
    for trace_id in list(dict.fromkeys(failing))[:MAX_TRACES]:
        found = http(
            "GET",
            f"https://cloudtrace.googleapis.com/v1/projects/{project}/traces/{trace_id}",
            {},
            None,
        )
        spans = []
        for span in found.get("spans", []):
            start, end = span.get("startTime"), span.get("endTime")
            duration = None
            if start and end:
                duration = round((_time(end) - _time(start)).total_seconds() * 1000)
            spans.append(
                {"name": span.get("name"), "duration_ms": duration, "labels": span.get("labels")}
            )
        traces.append({"trace_id": trace_id, "spans": spans})
    return shape("live", {"query": query, "points": points}, logs, traces)


def _time(value: str) -> datetime:
    # Cloud Trace gives nanoseconds; Python parses microseconds.
    head, _, fraction = value.rstrip("Z").partition(".")
    return datetime.fromisoformat(f"{head}.{(fraction + '000000')[:6]}+00:00")


def access_token() -> str:
    return subprocess.run(  # noqa: S603
        ["gcloud", "auth", "print-access-token"],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


# ---------------------------------------------------------------- report


def validate(report_path: Path) -> dict[str, Any]:
    """{"valid": bool, "errors": [...]}; the errors name a path and a rule, never the value."""
    import jsonschema  # the approved validator, from the backend's locked environment

    schema = json.loads((HERE / "report.schema.json").read_text())
    try:
        report = json.loads(report_path.read_text())
    except FileNotFoundError:
        return {"valid": False, "errors": ["the agent wrote no report"]}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"valid": False, "errors": ["the report is not JSON"]}
    validator = jsonschema.Draft202012Validator(schema)
    errors = [
        f"{'/'.join(str(part) for part in error.absolute_path) or '(root)'}: {error.validator}"
        for error in validator.iter_errors(report)
    ]
    return {"valid": not errors, "errors": errors[:10]}


PATCH_PATH_LINES = re.compile(
    r"^(?:rename from|rename to|copy from|copy to|--- (?:a/)?|\+\+\+ (?:b/)?)\s*(.+)$"
)


def patch_paths(patch: str) -> list[str]:
    """Every path a git patch names: `diff --git` headers, renames, copies and the ---/+++ lines.
    A header line of an unexpected form is kept whole, so that it fails the path check."""
    paths: list[str] = []
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            parts = line.split(" ")
            if len(parts) != 4 or not parts[2].startswith("a/") or not parts[3].startswith("b/"):
                paths.append(line)
                continue
            paths += [parts[2][2:], parts[3][2:]]
            continue
        match = PATCH_PATH_LINES.match(line)
        if match:
            path = match.group(1).strip().strip('"')
            if path != "/dev/null":
                paths.append(path)
    return paths


def patch_allowed(patch: str) -> bool:
    paths = patch_paths(patch)
    return bool(paths) and all(
        path.startswith(ALLOWED_PATCH_ROOTS) and ".." not in path and not path.endswith(".env")
        for path in paths
    )


def branch_name(incident_id: str) -> str:
    return "oncall/" + re.sub(r"[^A-Za-z0-9._-]", "-", incident_id).strip(".-")[:100]


# ---------------------------------------------------------------- finish


@dataclass(frozen=True)
class Results:
    triage: str  # job results: success, failure, cancelled, skipped
    collect: str
    agent: str
    reason: str  # a known failure reason, set by the workflow (e.g. missing key), or ""


def failed_step(results: Results, validation: Mapping[str, Any] | None) -> str | None:
    if results.triage != "success":
        return f"triage ({results.triage or 'unknown'})"
    if results.collect != "success":
        return "telemetry collection (" + (results.reason or results.collect) + ")"
    if results.agent != "success":
        return "agent (" + (results.reason or results.agent) + ")"
    if validation is None:
        return "report validation (did not run)"
    return None


def header(incident: Incident, run_url: str, server: str, repository: str) -> list[str]:
    runbook = f"{server}/{repository}/blob/main/{RUNBOOK}"
    lines = [
        marker("incident", incident.incident_id),
        marker("policy", incident.policy_name),
        f"**Alert:** {incident.policy_name} ({incident.environment})",
        f"**Incident ID:** `{incident.incident_id}`",
        f"**Started:** {incident.started_at}",
    ]
    if incident.console_url:
        lines.append(f"**Console:** {incident.console_url}")
    lines += [f"**On-call run:** {run_url}", f"**Runbook:** {runbook}", ""]
    return lines


def safe(text: str) -> str:
    """Agent text shown in an issue: no mention of a person, no hidden marker, no raw HTML."""
    return text.replace("@", "@​").replace("<", "&lt;").replace(">", "&gt;")


def render_report(report: Mapping[str, Any]) -> list[str]:
    change = report["proposed_change"]
    lines = [
        "## Diagnosis (on-call agent, schema-validated; to be checked by the owner)",
        "",
        f"**Summary:** {safe(report['summary'])}",
        "",
        f"**Suspected cause:** {safe(report['suspected_cause'])}",
        "",
        f"**Affected component:** `{report['affected_component']}`",
        "",
        "**Evidence (trace IDs):** "
        + (", ".join(f"`{t}`" for t in report["evidence_trace_ids"]) or "none"),
        "",
    ]
    if change == "none":
        lines.append("**Proposed change:** none")
    else:
        lines.append(f"**Proposed change:** {safe(change['title'])}: {safe(change['description'])}")
    return lines


def issue_body(
    incident: Incident,
    run_url: str,
    server: str,
    repository: str,
    results: Results,
    validation: Mapping[str, Any] | None,
    report: Mapping[str, Any] | None,
) -> str:
    lines = header(incident, run_url, server, repository)
    failure = failed_step(results, validation)
    if failure:
        lines += [
            f"**The on-call run failed at: {failure}.** No diagnosis. Handle the alert by hand "
            '(runbook, section "By hand"); the alert email was sent by Cloud Monitoring.',
        ]
    elif validation is not None and not validation.get("valid"):
        lines += [
            "**The agent's report failed validation** against "
            "`ops/oncall/report.schema.json`; it is not posted as a diagnosis. Rules broken: "
            + "; ".join(f"`{e}`" for e in validation.get("errors", [])),
        ]
    elif report is not None:
        lines += render_report(report)
    return "\n".join(lines)


def git(*args: str) -> str:
    return subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
    ).stdout


def propose(
    github: GitHub, incident: Incident, issue: int, report: Mapping[str, Any], patch: str
) -> str:
    """Push the agent's change to oncall/<id> and open a pull request. Never main, never a merge."""
    if not patch.strip():
        return "The report proposes a change, but the agent left no change in the working tree."
    if len(patch.encode()) > MAX_PATCH_BYTES or not patch_allowed(patch):
        return (
            "The proposed change was not applied: it touches files outside backend/ and "
            "frontend/, or is too large."
        )
    branch = branch_name(incident.incident_id)
    if branch in ("main", "oncall/") or not branch.startswith("oncall/"):
        return "The proposed change was not applied: no valid branch name."
    if git("ls-remote", "--heads", "origin", branch).strip():
        return f"Branch `{branch}` already exists: no second pull request."
    change = report["proposed_change"]
    title = safe(change["title"]).replace("\n", " ")
    git("switch", "--create", branch)
    subprocess.run(["git", "apply", "--index", "-"], input=patch, text=True, check=True, cwd=ROOT)  # noqa: S603, S607
    git(
        "-c", "user.name=github-actions[bot]",
        "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
        "commit", "--message", f"fix(oncall): {title} (#{issue})",
    )  # fmt: skip
    git("push", "origin", f"HEAD:refs/heads/{branch}")
    body = "\n".join(
        [
            f"Proposed by the on-call agent for incident `{incident.incident_id}` (#{issue}).",
            "",
            safe(change["description"]),
            "",
            "**Not reviewed by anyone yet.** The agent never merges or deploys: the owner decides.",
            "**CI has not run:** a pull request opened with the workflow token does not start "
            "workflows. The owner starts CI (close and reopen this pull request, or push a commit "
            "to the branch).",
        ]
    )
    number = github.open_pull_request(f"fix(oncall): {title}", branch, body)
    return f"Fix proposal: #{number} (branch `{branch}`)."


def finish(env: Mapping[str, str], github: GitHub, workdir: Path) -> None:
    incident = Incident.from_env(env)
    mode = env.get("TRIAGE_ACTION", "").strip() or "new"
    existing = env.get("TRIAGE_ISSUE", "").strip()
    server = env.get("GITHUB_SERVER_URL", "https://github.com")
    repository = env.get("GITHUB_REPOSITORY", "")
    run_url = f"{server}/{repository}/actions/runs/{env.get('GITHUB_RUN_ID', '')}"
    if mode == "duplicate" and existing:
        github.comment(
            int(existing),
            f"Another on-call run for this incident ({run_url}). The agent was not run again.",
        )
        return
    if mode == "flapping" and existing:
        github.comment(
            int(existing),
            f"New incident `{incident.incident_id}` of the same policy, started "
            f"{incident.started_at}, within the cooldown of this open issue (alert flapping). "
            f"The agent was not run. {run_url}",
        )
        return
    results = Results(
        triage=env.get("TRIAGE_RESULT", ""),
        collect=env.get("COLLECT_RESULT", ""),
        agent=env.get("AGENT_RESULT", ""),
        reason=re.sub(r"[^A-Za-z0-9 _.-]", "", env.get("FAILURE_REASON", ""))[:100],
    )
    validation = _load(workdir / "validation.json")
    report = _load(workdir / "report.json") if validation and validation.get("valid") else None
    body = issue_body(incident, run_url, server, repository, results, validation, report)
    issue = github.create_issue(f"Incident {incident.incident_id}: {incident.policy_name}", body)
    if report is not None and report["proposed_change"] != "none":
        patch_file = workdir / "change.patch"
        patch = patch_file.read_text() if patch_file.is_file() else ""
        try:
            note = propose(github, incident, issue, report, patch)
        except (subprocess.CalledProcessError, urllib.error.URLError) as error:
            note = (
                f"The proposed change could not be pushed ({type(error).__name__}); "
                "see the run log."
            )
        github.comment(issue, note)


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------- command line


def main(argv: Sequence[str]) -> int:
    command = argv[1] if len(argv) > 1 else ""
    env = os.environ
    if command == "triage":
        github = GitHub(env["GITHUB_REPOSITORY"], github_http(env["GITHUB_TOKEN"]))
        action, issue = triage(env, github, datetime.now(UTC))
        write_output("action", action)
        write_output("issue", str(issue or ""))
        return 0
    if command == "collect" and len(argv) == 3:
        incident = Incident.from_env(env)
        fixture = env.get("FIXTURE", "").strip()
        if fixture:
            telemetry = from_fixture(fixture)
        else:
            project = env.get("GCP_PROJECT_ID", "").strip()
            if not project:
                raise SystemExit("missing reader configuration: GCP_PROJECT_ID")
            telemetry = from_cloud(
                project, incident, google_http(access_token()), datetime.now(UTC)
            )
        Path(argv[2]).write_text(json.dumps(telemetry, indent=1))
        write_output("telemetry", base64.b64encode(json.dumps(telemetry).encode()).decode())
        return 0
    if command == "validate" and len(argv) == 3:
        result = validate(Path(argv[2]))
        (Path(argv[2]).parent / "validation.json").write_text(json.dumps(result))
        print("report valid" if result["valid"] else f"report invalid: {result['errors']}")
        return 0
    if command == "finish":
        github = GitHub(env["GITHUB_REPOSITORY"], github_http(env["GITHUB_TOKEN"]))
        finish(env, github, Path(env.get("ONCALL_OUTPUT", "oncall-output")))
        return 0
    print("usage: oncall.py triage | collect OUT | validate REPORT | finish", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))

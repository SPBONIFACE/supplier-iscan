"""Check that the workflows holding deployment credentials are out of reach of a fork (#52).

    python3 deploy/check_workflows.py [WORKFLOW_DIR]

Standard library only; it reads the workflow files as text. Rules:
  - a workflow that asks for `id-token: write` (Google sign-in) must not run on `pull_request`,
    `pull_request_target` or `issue_comment`;
  - when it is started by `workflow_run`, its gating condition must require the triggering event to
    be a `push`, the head repository to be this repository, and the head branch to be `main` (the
    trigger's `branches:` filter only matches a branch NAME, which a fork pull request can copy);
  - when it can be started by `workflow_dispatch`, it must require the main branch.
On-call workflow (`oncall.yml`, #53), outside its comments:
  - it calls no deploy, promote or merge command and never pushes to main;
  - its job `agent` (the LLM) exists and asks for no write permission, `id-token: write` included;
  - its top-level permissions grant no write.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REQUIRED_WORKFLOW_RUN = (
    "github.event.workflow_run.event == 'push'",
    "github.event.workflow_run.head_repository.full_name == github.repository",
    "github.event.workflow_run.head_branch == 'main'",
    "github.event.workflow_run.conclusion == 'success'",
)
FORBIDDEN_TRIGGERS = ("pull_request", "pull_request_target", "issue_comment")
ONCALL = "oncall.yml"
ONCALL_FORBIDDEN = (
    (r"deploy\.sh", "deploy/deploy.sh"),
    (r"gcloud\s+(?:beta\s+)?run\s+(?:deploy|services|jobs|worker-pools)", "a Cloud Run deploy"),
    (r"\bpromote", "a promotion"),
    (r"\bgh\s+pr\s+merge\b|\bgit\s+merge\b|/merges?\b|\bmerge_method\b", "a merge"),
    (r"\bgit\s+push\b[^\n]*\bmain\b", "a push to main"),
)


def triggers(text: str) -> set[str]:
    """The names under the top-level `on:` key."""
    match = re.search(r"^on:\s*\n((?:[ \t]+.*\n|\s*\n)+)", text, flags=re.MULTILINE)
    if not match:
        return set()
    return set(re.findall(r"^  ([a-z_]+):", match.group(1), flags=re.MULTILINE))


def problems(name: str, text: str) -> list[str]:
    if not re.search(r"id-token:\s*write", text):
        return []
    found: list[str] = []
    on = triggers(text)
    for trigger in FORBIDDEN_TRIGGERS:
        if trigger in on:
            found.append(f"{name}: has deployment credentials but runs on {trigger}")
    flat = " ".join(text.split())
    if "workflow_run" in on:
        for needed in REQUIRED_WORKFLOW_RUN:
            if needed not in flat:
                found.append(f"{name}: workflow_run is not gated by `{needed}`")
    if "workflow_dispatch" in on and "github.ref == 'refs/heads/main'" not in flat:
        found.append(f"{name}: workflow_dispatch is not gated by `github.ref == 'refs/heads/main'`")
    if not on & {"workflow_run", "workflow_dispatch"}:
        found.append(f"{name}: has deployment credentials but no known trigger to check")
    return found


def without_comments(text: str) -> str:
    return "\n".join(re.sub(r"(^|\s)#.*$", "", line) for line in text.splitlines())


def block(text: str, key: str, indent: int) -> str | None:
    """The lines under `key:` at the given indentation, up to the next key at that indentation."""
    pad = " " * indent
    match = re.search(
        rf"^{pad}{re.escape(key)}:.*\n((?:(?:{pad}[ \t]+.*)?\n)*)", text, re.MULTILINE
    )
    return None if match is None else match.group(0)


def job_permissions(job: str) -> str:
    """What a job's `permissions:` grants, however it is written: block mapping, flow mapping
    (`{ contents: write }`) or a scalar (`write-all`), as one flat string."""
    found = ""
    for match in re.finditer(
        r"^([ \t]+)permissions\s*:(.*)\n((?:\1[ \t]+.*\n|[ \t]*\n)*)", job, re.M
    ):
        found += " " + match.group(2) + " " + " ".join(match.group(3).split())
    return found


def oncall_problems(name: str, text: str) -> list[str]:
    code = without_comments(text) + "\n"
    found = [
        f"{name}: calls {what}"
        for pattern, what in ONCALL_FORBIDDEN
        if re.search(pattern, code, flags=re.IGNORECASE)
    ]
    jobs = block(code, "jobs", 0) or ""
    agent = block(jobs, "agent", 2)
    if agent is None:
        found.append(f"{name}: has no job `agent`")
    else:
        granted = job_permissions(agent)
        if re.search(r"id-token\s*:\s*write", granted):
            found.append(f"{name}: the agent job asks for id-token: write")
        if re.search(r"write", granted):
            found.append(f"{name}: the agent job asks for a write permission")
    top = block(code, "permissions", 0) or ""
    if re.search(r"write", top):
        found.append(f"{name}: the top-level permissions grant a write")
    return found


def main(argv: list[str]) -> int:
    directory = Path(argv[1]) if len(argv) > 1 else Path(".github/workflows")
    files = sorted([*directory.glob("*.yml"), *directory.glob("*.yaml")])
    found = [line for path in files for line in problems(path.name, path.read_text())]
    found += [
        line
        for path in files
        if path.name == ONCALL
        for line in oncall_problems(path.name, path.read_text())
    ]
    for line in found:
        print(f"FAIL: {line}", file=sys.stderr)
    if not found:
        print(f"ok: {len(files)} workflows checked")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

"""Check that the workflows holding deployment credentials are out of reach of a fork (#52).

    python3 deploy/check_workflows.py [WORKFLOW_DIR]

Standard library only; it reads the workflow files as text. Rules:
  - a workflow that asks for `id-token: write` (Google sign-in) must not run on `pull_request`,
    `pull_request_target` or `issue_comment`;
  - when it is started by `workflow_run`, its gating condition must require the triggering event to
    be a `push`, the head repository to be this repository, and the head branch to be `main` (the
    trigger's `branches:` filter only matches a branch NAME, which a fork pull request can copy);
  - when it can be started by `workflow_dispatch`, it must require the main branch.
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


def main(argv: list[str]) -> int:
    directory = Path(argv[1]) if len(argv) > 1 else Path(".github/workflows")
    files = sorted([*directory.glob("*.yml"), *directory.glob("*.yaml")])
    found = [line for path in files for line in problems(path.name, path.read_text())]
    for line in found:
        print(f"FAIL: {line}", file=sys.stderr)
    if not found:
        print(f"ok: {len(files)} workflows checked")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

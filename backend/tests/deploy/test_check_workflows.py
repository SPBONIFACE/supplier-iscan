"""deploy/check_workflows.py accepts the repository's workflows and refuses unsafe ones."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "check_workflows", ROOT / "deploy" / "check_workflows.py"
)
assert spec is not None and spec.loader is not None
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)

UNSAFE = """name: x
on:
  workflow_run:
    workflows: [CI]
    types: [completed]
    branches: [main]
jobs:
  deploy:
    if: github.event.workflow_run.conclusion == 'success'
    permissions:
      id-token: write
"""


def test_repository_workflows_pass() -> None:
    assert check.main(["check_workflows.py", str(ROOT / ".github" / "workflows")]) == 0


def test_branch_filter_alone_is_refused() -> None:
    found = check.problems("x.yml", UNSAFE)
    assert any("event == 'push'" in line for line in found)
    assert any("head_repository.full_name" in line for line in found)


def test_credentials_on_pull_request_are_refused() -> None:
    text = "on:\n  pull_request:\n    branches: [main]\npermissions:\n  id-token: write\n"
    assert any("pull_request" in line for line in check.problems("y.yml", text))


def test_workflow_without_credentials_is_ignored() -> None:
    assert check.problems("z.yml", "on:\n  pull_request:\n") == []


ONCALL = (ROOT / ".github" / "workflows" / "oncall.yml").read_text()


def test_the_oncall_workflow_passes_its_rule() -> None:
    assert check.oncall_problems("oncall.yml", ONCALL) == []


def test_oncall_agent_job_with_id_token_or_write_is_refused() -> None:
    agent_header = "  agent:\n    name: diagnose (Claude Code, no cloud credential)\n"
    assert agent_header in ONCALL
    text = ONCALL.replace(
        "    permissions:\n      contents: read\n    outputs:\n      report:",
        "    permissions:\n      contents: write\n      id-token: write\n"
        "    outputs:\n      report:",
    )
    assert text != ONCALL
    found = check.oncall_problems("oncall.yml", text)
    assert any("id-token" in line for line in found)
    assert any("write permission" in line for line in found)


def test_oncall_deploy_merge_or_push_to_main_is_refused() -> None:
    for command in (
        "deploy/deploy.sh dev deploy",
        "gcloud run deploy iscan-api-dev",
        "gh pr merge 12 --squash",
        "git merge oncall/x",
        "git push origin HEAD:main",
        "promote",
    ):
        text = ONCALL + f"      - run: {command}\n"
        assert check.oncall_problems("oncall.yml", text), command


def test_oncall_rule_ignores_comments_and_needs_an_agent_job() -> None:
    assert check.oncall_problems("oncall.yml", ONCALL + "# never merges, never deploys\n") == []
    assert any(
        "no job `agent`" in line for line in check.oncall_problems("oncall.yml", "jobs:\n  x:\n")
    )


def test_oncall_top_level_write_is_refused() -> None:
    text = ONCALL.replace("permissions: {}\n", "permissions:\n  contents: write\n")
    assert any("top-level" in line for line in check.oncall_problems("oncall.yml", text))


AGENT_PERMISSIONS = "    permissions:\n      contents: read\n    outputs:\n      report:"


@pytest.mark.parametrize(
    ("permissions", "id_token"),
    [
        ("    permissions: { contents: write }\n", False),
        ("    permissions: {contents: read, id-token: write}\n", True),
        ("    permissions: write-all\n", False),
        ("    permissions:\n      contents:   write\n", False),
        ("    permissions:\n      contents: read\n      id-token:  write\n", True),
    ],
)
def test_agent_write_in_any_permissions_form_is_refused(permissions: str, id_token: bool) -> None:
    assert AGENT_PERMISSIONS in ONCALL
    text = ONCALL.replace(AGENT_PERMISSIONS, permissions + "    outputs:\n      report:")
    found = check.oncall_problems("oncall.yml", text)

    assert any("write permission" in line for line in found), permissions
    assert any("id-token" in line for line in found) is id_token

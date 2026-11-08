"""deploy/check_workflows.py accepts the repository's workflows and refuses unsafe ones."""

import importlib.util
from pathlib import Path

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

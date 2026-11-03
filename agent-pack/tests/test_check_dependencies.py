"""Tests of scripts/check_dependencies.py on small temporary repositories (no real lockfile)."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_dependencies.py"
REPO = Path(__file__).resolve().parents[2]

LIST_TEXT = """# Approved dependencies

| Package | Exact version | Runtime/dev | Note |
| :--- | :--- | :--- | :--- |
| `alpha` | 1.0.0 | runtime | |
| `psycopg[binary]` | 3.3.6 | runtime | |
| `beta-pkg` | 2.0.0 **SEC** | runtime | |
| `zh-core-web-sm` | 3.8.0 | runtime | URL wheel |
| `old` | 0.9.0 → **remove** | dev | |
| `pytest`, `ruff` | 9.1.1, 0.17.0 | dev | |
| `react` | 19.3.0 | frontend | |
"""

LOCK_TEXT = '[[package]]\nname = "zh-core-web-sm"\nversion = "3.8.0"\n'


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_dependencies", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_repo(
    tmp_path: Path,
    deps: list[str],
    dev: list[str] | None = None,
    node: dict[str, str] | None = None,
    lock: str = LOCK_TEXT,
) -> Path:
    (tmp_path / "_docs/process").mkdir(parents=True)
    (tmp_path / "_docs/process/approved-dependencies.md").write_text(LIST_TEXT, encoding="utf-8")
    (tmp_path / "backend").mkdir()
    quoted = ", ".join(json.dumps(d) for d in deps)
    quoted_dev = ", ".join(json.dumps(d) for d in dev or [])
    (tmp_path / "backend/pyproject.toml").write_text(
        f'[project]\nname = "x"\nversion = "0"\ndependencies = [{quoted}]\n'
        f"[dependency-groups]\ndev = [{quoted_dev}]\n",
        encoding="utf-8",
    )
    (tmp_path / "backend/uv.lock").write_text(lock, encoding="utf-8")
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend/package.json").write_text(
        json.dumps({"dependencies": node or {}, "devDependencies": {}}), encoding="utf-8"
    )
    return tmp_path


def test_clean_passes(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path,
        ["alpha==1.0.0", "psycopg[binary]==3.3.6", "beta_pkg==2.0.0", "zh-core-web-sm"],
        dev=["pytest==9.1.1", "ruff==0.17.0"],
        node={"react": "19.3.0"},
    )
    assert load().check(repo) == []


def test_unlisted_package_fails_and_is_named(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, ["alpha==1.0.0", "protobuf==7.36.2"])
    problems = load().check(repo)
    assert len(problems) == 1
    assert "protobuf" in problems[0] and "not in the approved list" in problems[0]


def test_wrong_version_fails(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, ["alpha==1.0.1"])
    problems = load().check(repo)
    assert len(problems) == 1
    assert "alpha 1.0.1" in problems[0] and "1.0.0" in problems[0]


def test_wrong_frontend_version_fails(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, ["alpha==1.0.0"], node={"react": "19.4.0"})
    assert "react 19.4.0" in load().check(repo)[0]


def test_range_is_not_exact(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, ["alpha>=1.0.0"], node={"react": "^19.3.0"})
    problems = load().check(repo)
    assert len(problems) == 2
    assert all("no exact version" in p for p in problems)


def test_removed_entry_does_not_count(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, ["alpha==1.0.0"], dev=["old==0.9.0"])
    problems = load().check(repo)
    assert len(problems) == 1
    assert "old" in problems[0] and "removed" in problems[0]


def test_url_wheel_takes_its_version_from_the_lockfile(tmp_path: Path) -> None:
    lock = '[[package]]\nname = "zh-core-web-sm"\nversion = "3.9.0"\n'
    repo = make_repo(tmp_path, ["zh-core-web-sm"], lock=lock)
    problems = load().check(repo)
    assert len(problems) == 1 and "zh-core-web-sm 3.9.0" in problems[0]


def test_url_wheel_missing_from_lockfile_fails(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, ["zh-core-web-sm"], lock="")
    assert "no exact version" in load().check(repo)[0]


def test_current_repository_passes() -> None:
    assert load().check(REPO) == []

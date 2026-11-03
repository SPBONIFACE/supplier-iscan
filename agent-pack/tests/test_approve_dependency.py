"""Tests of scripts/approve_dependency.py: a row it adds is read by check_dependencies.py."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


approve = load("approve_dependency")
check = load("check_dependencies")


def make_repo(tmp_path: Path) -> Path:
    (tmp_path / "_docs/process").mkdir(parents=True)
    (tmp_path / "_docs/process/approved-dependencies.md").write_text(
        "# Approved dependencies\n\n| Package | Exact version | Runtime/dev | Note |\n"
        "| :--- | :--- | :--- | :--- |\n| `alpha` | 1.0.0 | runtime | |\n",
        encoding="utf-8",
    )
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend/pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0"\ndependencies = ["alpha==1.0.0", "new-pkg==2.3.4"]\n',
        encoding="utf-8",
    )
    return tmp_path


def test_row_added_by_script_passes_the_check(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    assert any("new-pkg" in p for p in check.check(root))
    approve.add_row(root, "new-pkg", "2.3.4", "runtime", "needed for the parser, owner approved")
    assert check.check(root) == []
    again = (root / "_docs/process/approved-dependencies.md").read_text(encoding="utf-8")
    assert again.count("Owner approvals") == 1
    approve.add_row(root, "other", "1.0", "dev", "second row")
    text = (root / "_docs/process/approved-dependencies.md").read_text(encoding="utf-8")
    assert text.count("Owner approvals") == 1


def test_other_version_still_fails_after_approval(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    approve.add_row(root, "new-pkg", "2.3.5", "runtime", "different version")
    assert any("new-pkg" in p for p in check.check(root))


@pytest.mark.parametrize(
    ("package", "version", "scope", "note"),
    [
        ("", "1.0.0", "dev", "why"),
        ("x", "", "dev", "why"),
        ("x", "1.0.0", "", "why"),
        ("x", "1.0.0", "dev", ""),
        ("x", "1.0.0", "dev", "   "),
        ("x", ">=1.0", "dev", "why"),
        ("x", "^1.0.0", "dev", "why"),
        ("x", "latest", "dev", "why"),
        ("x", "1.0.0 remove", "dev", "why"),
        ("x", "1.0.0", "prod", "why"),
        ("x y", "1.0.0", "dev", "why"),
        ("x|y", "1.0.0", "dev", "why"),
        ("x", "1.0.0", "dev", "a | b"),
        ("x", "1.0.0", "dev", "two\nlines"),
    ],
)
def test_bad_input_is_refused(
    tmp_path: Path, package: str, version: str, scope: str, note: str
) -> None:
    root = make_repo(tmp_path)
    path = root / "_docs/process/approved-dependencies.md"
    before = path.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="must"):
        approve.add_row(root, package, version, scope, note)
    assert path.read_text(encoding="utf-8") == before

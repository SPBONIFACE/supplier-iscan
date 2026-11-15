"""#185: the fast pass takes only `StoredSourceText`, and that type is made in one place: the loader
of the extraction stage, from Source rows read from the database. Any other construction in `app/`
or `eval/` fails this test."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ALLOWED = {
    ROOT / "backend" / "app" / "redaction" / "text.py",  # the class itself
    ROOT / "backend" / "app" / "extraction" / "stage.py",  # the loader (`_load`)
}


def builds(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "StoredSourceText"
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "StoredSourceText"
    )


def test_stored_source_text_is_built_only_by_the_extraction_loader() -> None:
    offenders = []
    for folder in (ROOT / "backend" / "app", ROOT / "eval"):
        for path in folder.rglob("*.py"):
            if path in ALLOWED:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            offenders += [
                f"{path.relative_to(ROOT)}:{getattr(n, 'lineno', 0)}"
                for n in ast.walk(tree)
                if builds(n)
            ]
    assert offenders == []


def test_in_the_extraction_stage_it_is_built_only_in_the_loader() -> None:
    path = ROOT / "backend" / "app" / "extraction" / "stage.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    holders = {f.name for f in functions if any(builds(n) for n in ast.walk(f))}
    assert holders == {"_load"}

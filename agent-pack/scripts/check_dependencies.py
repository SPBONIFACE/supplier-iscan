"""Check every direct dependency against the owner's approved list (standard library only).

Compares name and exact version of each direct dependency declared in backend/pyproject.toml
(runtime and dev), agent-pack/pyproject.toml and frontend/package.json (dependencies and
devDependencies) with the tables of _docs/process/approved-dependencies.md. Fails, naming the
package, when one is missing from the list, differs in version, is only listed as removed, or is
not pinned exactly. The "newer patch or minor" rule of the list does not apply here: a new version
means the list is updated, through the owner (_docs/team/swe.md).

Special cases:
  - Direct-URL wheels and entries without a version in pyproject.toml (for example zh-core-web-sm,
    which has a `[tool.uv.sources]` url): the version is read from the uv.lock next to the
    pyproject.toml, which pins the exact wheel by url and sha256.
  - Extras (`psycopg[binary]`) are dropped from the name; names follow PEP 503.
  - A list row whose version cell contains "remove" is a removed entry and approves nothing.
"""

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIST_FILE = Path("_docs/process/approved-dependencies.md")
PYPROJECTS = (Path("backend/pyproject.toml"), Path("agent-pack/pyproject.toml"))
PACKAGE_JSON = Path("frontend/package.json")

NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*(.*)$")
EXACT = re.compile(r"^==\s*([0-9][^\s;,]*)\s*(;.*)?$")
VERSION = re.compile(r"^[0-9][0-9A-Za-z.+!_-]*")
BACKTICKED = re.compile(r"`([^`]+)`")

Declared = tuple[str, str | None, str]


def normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_list(text: str) -> tuple[dict[str, set[str]], set[str]]:
    """Approved versions by normalised name, and the names listed as removed."""
    approved: dict[str, set[str]] = {}
    removed: set[str] = set()
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        names = [n.split("[")[0] for n in BACKTICKED.findall(cells[0])]
        if not names:
            continue
        if "remove" in cells[1].lower():
            removed.update(normalise(n) for n in names)
            continue
        versions = [v.strip() for v in cells[1].split(",")]
        if len(versions) != len(names):  # a one-name row may carry a note with commas
            versions = [cells[1]] if len(names) == 1 else []
        for name, raw in zip(names, versions, strict=False):
            match = VERSION.match(raw)
            if match:
                approved.setdefault(normalise(name), set()).add(match.group(0))
    return approved, removed


def locked_versions(lock: Path) -> dict[str, str]:
    if not lock.is_file():
        return {}
    data = tomllib.loads(lock.read_text(encoding="utf-8"))
    return {normalise(p["name"]): p["version"] for p in data.get("package", []) if "version" in p}


def python_dependencies(pyproject: Path, label: str) -> list[Declared]:
    """(name, exact version or None, file) for each direct dependency; None when not exact."""
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    specs = list(data.get("project", {}).get("dependencies", []))
    for group in data.get("dependency-groups", {}).values():
        specs += [s for s in group if isinstance(s, str)]
    for extra in data.get("project", {}).get("optional-dependencies", {}).values():
        specs += extra
    locked = locked_versions(pyproject.with_name("uv.lock"))
    found: list[Declared] = []
    for spec in specs:
        match = NAME.match(spec)
        if not match:
            found.append((spec, None, label))
            continue
        name, rest = match.group(1), match.group(3).strip()
        if not rest or rest.startswith(";"):
            # No version in pyproject.toml (direct-URL wheel): the lockfile pins it.
            found.append((name, locked.get(normalise(name)), label))
            continue
        exact = EXACT.match(rest)
        found.append((name, exact.group(1) if exact else None, label))
    return found


def node_dependencies(package_json: Path, label: str) -> list[Declared]:
    data = json.loads(package_json.read_text(encoding="utf-8"))
    found: list[Declared] = []
    for section in ("dependencies", "devDependencies"):
        for name, version in data.get(section, {}).items():
            exact = isinstance(version, str) and version[:1].isdigit()
            found.append((name, version if exact else None, label))
    return found


def check(root: Path) -> list[str]:
    approved, removed = parse_list((root / LIST_FILE).read_text(encoding="utf-8"))
    declared: list[Declared] = []
    for pyproject in PYPROJECTS:
        if (root / pyproject).is_file():
            declared += python_dependencies(root / pyproject, str(pyproject))
    if (root / PACKAGE_JSON).is_file():
        declared += node_dependencies(root / PACKAGE_JSON, str(PACKAGE_JSON))

    problems: list[str] = []
    for name, version, where in declared:
        key = normalise(name)
        if version is None:
            problems.append(f"{name} ({where}): no exact version (pin it, or lock it in uv.lock)")
        elif key in removed and key not in approved:
            problems.append(f"{name} ({where}): listed as removed, not approved")
        elif key not in approved:
            problems.append(f"{name} {version} ({where}): not in the approved list")
        elif version not in approved[key]:
            listed = ", ".join(sorted(approved[key]))
            problems.append(f"{name} {version} ({where}): the approved version is {listed}")
    return problems


def main() -> int:
    problems = check(ROOT)
    if not problems:
        return 0
    print(
        "Dependency check failed. Only the owner approves a package or a version:", file=sys.stderr
    )
    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)
    print(
        f"Stop and report it. {LIST_FILE} changes only with the owner's approval.", file=sys.stderr
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())

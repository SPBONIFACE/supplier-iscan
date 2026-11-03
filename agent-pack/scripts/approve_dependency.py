"""Owner's step: append one approved dependency to the list (standard library only).

Run in your own terminal, never by an agent (the hook blocks it):

    make approve-dependency PACKAGE=name VERSION=x.y.z SCOPE=runtime|dev NOTE="why"

Appends a row to the table "Owner approvals" at the end of _docs/process/approved-dependencies.md,
in the format scripts/check_dependencies.py reads. Refuses an empty value, a name that is not a
package name, a version that is not exact (no range, no "latest", no "remove"), another scope and
a note with a pipe, a backtick or a line break. You may also edit the file by hand.
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIST_FILE = Path("_docs/process/approved-dependencies.md")
HEADING = "## Owner approvals (added with make approve-dependency)"
TABLE_HEAD = "| Package | Exact version | Runtime/dev | Note |\n| :--- | :--- | :--- | :--- |\n"
NAME = re.compile(r"^(@[A-Za-z0-9._-]+/)?[A-Za-z0-9][A-Za-z0-9._-]*$")
EXACT = re.compile(r"^[0-9]+(\.[0-9]+)*([-+.][0-9A-Za-z]+([.-][0-9A-Za-z]+)*)?$")
SCOPES = ("runtime", "dev")


def validate(package: str, version: str, scope: str, note: str) -> list[str]:
    errors: list[str] = []
    if not package.strip() or not NAME.match(package.strip()):
        errors.append("PACKAGE must be a package name (letters, digits, . _ -)")
    if not version.strip() or not EXACT.match(version.strip()):
        errors.append("VERSION must be exact, for example 1.2.3 (no range, no latest)")
    if scope.strip() not in SCOPES:
        errors.append("SCOPE must be runtime or dev")
    if not note.strip() or re.search(r"[|\r\n`]", note):
        errors.append("NOTE must say why, on one line, without | or backticks")
    return errors


def add_row(root: Path, package: str, version: str, scope: str, note: str) -> str:
    errors = validate(package, version, scope, note)
    if errors:
        raise ValueError("; ".join(errors))
    path = root / LIST_FILE
    text = path.read_text(encoding="utf-8").rstrip("\n") + "\n"
    if HEADING not in text:
        text += f"\n{HEADING}\n\n{TABLE_HEAD}"
    row = f"| `{package.strip()}` | {version.strip()} | {scope.strip()} | {note.strip()} |\n"
    path.write_text(text + row, encoding="utf-8")
    return row.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Append an approved dependency (owner only).")
    for arg in ("package", "version", "scope", "note"):
        parser.add_argument(f"--{arg}", default="")
    args = parser.parse_args()
    try:
        row = add_row(ROOT, args.package, args.version, args.scope, args.note)
    except ValueError as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 1
    print(f"Added to {LIST_FILE}: {row}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

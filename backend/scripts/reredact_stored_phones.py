"""Re-redact phone numbers left in stored text, for named sources only (#221).

    DATABASE_URL=... uv run --directory backend python -m scripts.reredact_stored_phones \
        --source-id <uuid> [--source-id <uuid> ...] [--apply]

Without `--apply` this is a DRY RUN: a READ ONLY transaction, rolled back; it only prints counts.
With `--apply` it runs the current stored-text redaction (`Redactor.redact_stored`, the fast pass
the app uses on stored text, with #219) over each given source and over every stored text derived
from it, in ONE transaction: it writes only the texts that change and commits only if no phone
match is left in any of them; otherwise it rolls back and exits 1.

Texts covered, per source:
- `sources.redacted_text` and `sources.author`;
- `facts.quote`, `facts.value`, `facts.original_value`, `facts.author`, `facts.group_level` of the
  facts whose `source_id` is the source (the only columns that copy source text into a fact);
- `assessment_statements.text`, `original_text` and `gap_evidence` of the statements of the same
  run that cite one of those facts (`cited_fact_ids`).
Not covered: URLs (`sources.url`, `facts.source_url`; a path is not source text), demo profiles
(the scan reports them), facts whose source was deleted (`source_id` is null), and the name and
address lists of the identity (the dry run and the apply use no per-run context).

No content hash is stored for a source, a fact or a statement (the hash columns of this schema
are on runs, users and sessions and cover other data), so nothing has to be recomputed; ids,
versions, review state and timestamps are left as they are.

Output: ids, column names and counts only (matches before and after, characters changed). It
never prints, logs or raises a phone number, a span or any text.
"""

import argparse
import os
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TextIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import DATABASE_URL
from app.db import make_engine
from app.models import AssessmentItem, Fact, Source
from app.redaction.engine import (
    Redactor,
    _email_spans,
    _merge,
    _obfuscated_email_spans,
    _phone_spans,
    get_redactor,
)
from app.redaction.text import StoredSourceText
from scripts.scan_stored_phones import count_phones, read_only_session

STATEMENT_TIMEOUT_SECONDS = 600

_FACT_COLUMNS = ("quote", "value", "original_value", "author", "group_level")
_STATEMENT_COLUMNS = ("text", "original_text", "gap_evidence")


def _spans(text: str) -> list[tuple[int, int]]:
    """The spans `Redactor.redact_stored` removes when it has no per-run context."""
    return _merge([*_email_spans(text), *_obfuscated_email_spans(text), *_phone_spans(text)], text)


def rewrite(text: str, stored: StoredSourceText) -> str:
    """The text through the stored-text redaction. A text that is a piece of the source goes
    through `redact_stored` itself; a text that is not (a rewritten value, a statement) gets the
    same spans applied, since `redact_stored` accepts only stored source text."""
    try:
        piece = stored.piece(text)
    except ValueError:
        return Redactor._apply(text, _spans(text))  # noqa: SLF001 - same span replacement
    return get_redactor().redact_stored(piece).text


@dataclass(frozen=True)
class Change:
    kind: str
    row_id: uuid.UUID
    column: str
    before: int
    after: int
    changed: int
    new_text: str | None  # None when the text did not change


def _check(
    row_kind: str,
    row_id: uuid.UUID,
    column: str,
    text: str | None,
    stored: Any,
    rewriter: Callable[[str, StoredSourceText], str],
) -> Change | None:
    if not text:
        return None
    before = count_phones(text)
    new_text = rewriter(text, stored)
    after = count_phones(new_text)
    if new_text == text:
        return Change(row_kind, row_id, column, before, after, 0, None) if before else None
    changed = sum(end - start for start, end in _spans(text))
    return Change(row_kind, row_id, column, before, after, changed, new_text)


def process_source(
    session: Session,
    source: Source,
    rewriter: Callable[[str, StoredSourceText], str],
    apply: bool,
) -> list[Change]:
    """The changes for one source and its derived texts; written to the session only on `apply`."""
    stored = StoredSourceText.of(source)  # the text as it was, before any change below
    changes: list[Change] = []

    def visit(kind: str, row: Any, columns: tuple[str, ...]) -> None:
        for column in columns:
            change = _check(kind, row.id, column, getattr(row, column), stored, rewriter)
            if change is None:
                continue
            changes.append(change)
            if apply and change.new_text is not None:
                setattr(row, column, change.new_text)

    visit("source", source, ("redacted_text", "author"))
    facts = list(session.scalars(select(Fact).where(Fact.source_id == source.id)))
    for fact in facts:
        visit("fact", fact, _FACT_COLUMNS)
    cited = {str(fact.id) for fact in facts}
    if cited:
        statements = session.scalars(
            select(AssessmentItem).where(AssessmentItem.run_id == source.run_id)
        )
        for statement in statements:
            if cited.intersection(str(item) for item in statement.cited_fact_ids):
                visit("statement", statement, _STATEMENT_COLUMNS)
    return changes


def run(
    session: Session,
    source_ids: list[uuid.UUID],
    apply: bool,
    out: TextIO,
    rewriter: Callable[[str, StoredSourceText], str] | None = None,
) -> bool:
    """Process the sources; True when every after-count is 0. Never commits or rolls back."""
    query = select(Source).where(Source.id.in_(source_ids))
    if apply:
        query = query.with_for_update()
    sources = {source.id: source for source in session.scalars(query)}
    clean = True
    for source_id in source_ids:
        source = sources.get(source_id)
        if source is None:
            print(f"source={source_id} NOT FOUND", file=out)
            clean = False
            continue
        changes = process_source(session, source, rewriter or rewrite, apply)
        for change in changes:
            print(
                f"{change.kind}={change.row_id} source={source_id} column={change.column} "
                f"before={change.before} after={change.after} chars_changed={change.changed}",
                file=out,
            )
        before = sum(c.before for c in changes)
        after = sum(c.after for c in changes)
        print(
            f"SOURCE {source_id}: texts_with_matches={len(changes)} before={before} "
            f"after={after} chars_changed={sum(c.changed for c in changes)}",
            file=out,
        )
        clean = clean and after == 0
    return clean


def main(argv: list[str] | None = None, out: TextIO | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts.reredact_stored_phones", description=__doc__)
    parser.add_argument(
        "--source-id",
        type=uuid.UUID,
        action="append",
        required=True,
        dest="source_ids",
        help="a source to re-redact (repeat for several); required",
    )
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    arguments = parser.parse_args(argv)
    out = out or sys.stdout
    url = os.environ.get(DATABASE_URL, "").strip()
    if not url:
        print(f"{DATABASE_URL} is not set", file=sys.stderr)
        return 2
    source_ids = list(dict.fromkeys(arguments.source_ids))
    engine = make_engine(url, STATEMENT_TIMEOUT_SECONDS)
    try:
        if not arguments.apply:
            with read_only_session(engine) as session:
                clean = run(session, source_ids, False, out)
            print("DRY RUN: nothing was written (use --apply to write).", file=out)
            return 0 if clean else 1
        with Session(engine) as session:
            try:
                clean = run(session, source_ids, True, out)
                if not clean:
                    session.rollback()
                    print("ROLLED BACK: a phone match would remain; nothing was written.", file=out)
                    return 1
                session.commit()
            except BaseException:
                session.rollback()
                raise
        print("COMMITTED.", file=out)
        return 0
    except Exception as error:  # noqa: BLE001 - the message could hold the URL or content
        print(
            f"The re-redaction failed ({type(error).__name__}); nothing was written.",
            file=sys.stderr,
        )
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())

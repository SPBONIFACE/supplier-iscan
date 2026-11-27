"""Read-only scan for phone numbers left in stored text (#221).

Runs the current phone detector (`app.redaction.engine._phone_spans`, the one redaction uses, with
the #219 fixes) over every stored `sources.redacted_text` and over the text of every stored demo
profile (`demo_profiles`: facts, assessment, run header), and reports counts.

    DATABASE_URL=... uv run --directory backend python -m scripts.scan_stored_phones [--limit N]

The scan never writes: its transaction is set READ ONLY before anything else, and it is rolled
back, never committed. It never prints, logs or raises a phone number, a span or any source text:
per affected item only ids, the host of the source URL (the path may hold personal data) and the
number of matches. The exit code is 0 when the scan completed, whatever it found.
"""

import argparse
import os
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, TextIO
from urllib.parse import urlsplit

from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.config import DATABASE_URL
from app.db import make_engine
from app.models import DemoProfile, Source
from app.redaction.engine import _phone_spans

# One scan may take longer than a request: the web statement timeout does not apply.
STATEMENT_TIMEOUT_SECONDS = 600
FETCH_BATCH = 50
# Demo values that are identifiers or timestamps, not text a reader sees.
_NOT_TEXT_KEYS = frozenset({"id", "content_type", "status", "supplier_website", "ids"})
_NOT_TEXT_SUFFIXES = ("_id", "_ids", "_url", "url", "_at", "_hash", "_version")


@dataclass(frozen=True)
class SourceHit:
    organisation_id: uuid.UUID
    run_id: uuid.UUID
    source_id: uuid.UUID
    host: str
    matches: int


@dataclass(frozen=True)
class DemoHit:
    profile_id: uuid.UUID
    position: int
    matches: int


@dataclass(frozen=True)
class ScanResult:
    sources_scanned: int
    source_hits: list[SourceHit]
    demo_scanned: int
    demo_hits: list[DemoHit]


@contextmanager
def read_only_session(engine: Engine) -> Iterator[Session]:
    """A session whose transaction is READ ONLY from its first statement; always rolled back."""
    with Session(engine) as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        try:
            yield session
        finally:
            session.rollback()


def count_phones(text_value: str) -> int:
    return len(_phone_spans(text_value))


def url_host(url: str) -> str:
    try:
        return urlsplit(url).hostname or "(none)"
    except ValueError:
        return "(unparsable)"


def _is_text_key(key: str) -> bool:
    return key not in _NOT_TEXT_KEYS and not key.endswith(_NOT_TEXT_SUFFIXES)


def count_in_json(value: Any, key: str = "") -> int:
    """Phone matches in the strings of a stored JSON value, skipping identifier-like keys."""
    if isinstance(value, str):
        return count_phones(value) if _is_text_key(key) else 0
    if isinstance(value, dict):
        return sum(count_in_json(item, str(name)) for name, item in value.items())
    if isinstance(value, list):
        return sum(count_in_json(item, key) for item in value)
    return 0


def scan(session: Session, limit: int | None = None) -> ScanResult:
    source_query = select(
        Source.organisation_id, Source.run_id, Source.id, Source.url, Source.redacted_text
    ).order_by(Source.id)
    if limit is not None:
        source_query = source_query.limit(limit)
    sources_scanned = 0
    source_hits: list[SourceHit] = []
    for organisation_id, run_id, source_id, url, redacted_text in session.execute(
        source_query.execution_options(yield_per=FETCH_BATCH)
    ):
        sources_scanned += 1
        matches = count_phones(redacted_text)
        if matches:
            source_hits.append(
                SourceHit(organisation_id, run_id, source_id, url_host(url), matches)
            )

    demo_query = select(
        DemoProfile.id,
        DemoProfile.position,
        DemoProfile.run,
        DemoProfile.facts,
        DemoProfile.assessment,
        DemoProfile.sources,
    ).order_by(DemoProfile.position, DemoProfile.id)
    if limit is not None:
        demo_query = demo_query.limit(limit)
    demo_scanned = 0
    demo_hits: list[DemoHit] = []
    for profile_id, position, *parts in session.execute(demo_query):
        demo_scanned += 1
        matches = sum(count_in_json(part) for part in parts)
        if matches:
            demo_hits.append(DemoHit(profile_id, position, matches))
    return ScanResult(sources_scanned, source_hits, demo_scanned, demo_hits)


def report(result: ScanResult, out: TextIO) -> None:
    """Ids, hosts and counts only."""
    for hit in result.source_hits:
        print(
            f"source organisation={hit.organisation_id} run={hit.run_id} source={hit.source_id} "
            f"host={hit.host} matches={hit.matches}",
            file=out,
        )
    for demo in result.demo_hits:
        print(
            f"demo_profile id={demo.profile_id} position={demo.position} matches={demo.matches}",
            file=out,
        )
    print(
        f"TOTAL sources: scanned={result.sources_scanned} "
        f"affected={len(result.source_hits)} matches={sum(h.matches for h in result.source_hits)}",
        file=out,
    )
    print(
        f"TOTAL demo profiles: scanned={result.demo_scanned} "
        f"affected={len(result.demo_hits)} matches={sum(h.matches for h in result.demo_hits)}",
        file=out,
    )


def main(argv: list[str] | None = None, out: TextIO | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts.scan_stored_phones", description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="scan at most N items per table")
    arguments = parser.parse_args(argv)
    out = out or sys.stdout
    url = os.environ.get(DATABASE_URL, "").strip()
    if not url:
        print(f"{DATABASE_URL} is not set", file=sys.stderr)
        return 2
    engine = make_engine(url, STATEMENT_TIMEOUT_SECONDS)
    try:
        with read_only_session(engine) as session:
            result = scan(session, arguments.limit)
    except Exception as error:  # noqa: BLE001 - the message could hold the URL or content
        print(f"The scan failed ({type(error).__name__}); nothing was written.", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    report(result, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""#196: sources are redacted N at a time; rows are written in order on the caller thread."""

import threading
import time
import uuid
from collections.abc import Callable

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.collection import source_store
from app.collection.source_store import SourceRecord, SourceStorage
from app.db import Database, utc_now
from app.models import Source
from app.redaction import RedactionUnavailable
from tests.factories import create_organisation
from tests.runs_support import create_run

HOST = "acme.example"


def record(name: str) -> SourceRecord:
    return SourceRecord(f"https://{HOST}/{name}", utc_now(), "text/html", name, None)


class Spy:
    """Stands in for redaction, and watches the row write: threads and order."""

    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, work: Callable[[str], None] | None = None
    ) -> None:
        self.work = work
        self.redaction_threads: set[str] = set()
        self.written: list[tuple[str, str]] = []
        self.write_threads: set[str] = set()
        monkeypatch.setattr(source_store, "redact_for_storage", self._redact)
        original = source_store._write_source

        def write(database, run_id, organisation_id, rec, text, author):  # type: ignore[no-untyped-def]
            self.write_threads.add(threading.current_thread().name)
            self.written.append((rec.url.rsplit("/", 1)[1], text))
            return original(database, run_id, organisation_id, rec, text, author)

        monkeypatch.setattr(source_store, "_write_source", write)

    def _redact(self, text, gate, context):  # type: ignore[no-untyped-def]
        self.redaction_threads.add(threading.current_thread().name)
        if self.work is not None:
            self.work(text)
        return text.upper()


def make_storage(engine: Engine, concurrency: int) -> tuple[SourceStorage, uuid.UUID]:
    organisation_id = create_organisation(engine)
    run_id = create_run(engine, organisation_id)
    return SourceStorage(Database(None, engine), run_id, organisation_id, concurrency), run_id


def test_two_sources_are_redacted_at_the_same_time_and_written_in_order(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    meeting = threading.Barrier(2, timeout=10)  # both redactions must be running together

    def work(text: str) -> None:
        meeting.wait()
        if text == "first":
            time.sleep(0.3)  # the second one finishes first; it is still written second

    spy = Spy(monkeypatch, work)
    storage, run_id = make_storage(engine, 2)

    storage.submit(record("first"))
    storage.submit(record("second"))
    storage.finish()

    assert spy.written == [("first", "FIRST"), ("second", "SECOND")]
    assert spy.write_threads == {threading.current_thread().name}
    assert all(name.startswith("source-redaction") for name in spy.redaction_threads)
    with Session(engine) as db:
        rows = db.scalars(select(Source).where(Source.run_id == run_id)).all()
    assert {row.redacted_text for row in rows} == {"FIRST", "SECOND"}


def test_one_instance_redacts_and_writes_before_submit_returns(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy = Spy(monkeypatch)
    storage, _run_id = make_storage(engine, 1)

    storage.submit(record("first"))
    assert spy.written == [("first", "FIRST")]  # already written, as before
    storage.submit(record("second"))
    storage.finish()

    assert spy.written == [("first", "FIRST"), ("second", "SECOND")]
    assert spy.redaction_threads == {threading.current_thread().name}


def test_never_more_than_the_limit_is_redacted_at_once(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = threading.Lock()
    state = {"running": 0, "peak": 0}

    def work(_text: str) -> None:
        with lock:
            state["running"] += 1
            state["peak"] = max(state["peak"], state["running"])
        time.sleep(0.05)
        with lock:
            state["running"] -= 1

    spy = Spy(monkeypatch, work)
    storage, _run_id = make_storage(engine, 2)

    for index in range(6):
        storage.submit(record(f"s{index}"))
    storage.finish()

    assert state["peak"] == 2
    assert [name for name, _ in spy.written] == [f"s{index}" for index in range(6)]


def test_a_failed_redaction_writes_nothing_after_it(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    def work(text: str) -> None:
        if text == "bad":
            raise RedactionUnavailable

    spy = Spy(monkeypatch, work)
    storage, run_id = make_storage(engine, 2)

    with pytest.raises(RedactionUnavailable):  # at the write of "bad", whichever call that is
        for name in ("good", "bad", "later"):
            storage.submit(record(name))
        storage.finish()

    assert [name for name, _ in spy.written] == ["good"]
    with Session(engine) as db:
        urls = db.scalars(select(Source.url).where(Source.run_id == run_id)).all()
    assert urls == [f"https://{HOST}/good"]


def test_abandon_writes_nothing_pending(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    spy = Spy(monkeypatch)
    storage, _run_id = make_storage(engine, 2)

    storage.submit(record("first"))
    storage.abandon()

    assert spy.written == []

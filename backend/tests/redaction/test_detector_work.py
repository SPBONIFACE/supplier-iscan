"""#196: less detector work with the same output, and personal data still never leaves.

The detector is the real `GlinerDetector` (chunking, run cache, skipping) over a stub model that
"finds" the planted name and records every piece it is given; nothing else is faked, so the cache
and the skip are on the path that the collection takes (`store_source`) and the extraction reads.
"""

import json
import logging
import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.collection.source_store import SourceRecord, store_source
from app.db import Database
from app.models import Source
from app.redaction import RedactionGate, RedactionUnavailable, Redactor, detector
from app.redaction.detector import GlinerDetector, chunk_text, run_piece_cache
from tests.extraction.support import context_for, providers_with, scripted, stage
from tests.factories import create_organisation
from tests.redaction.perf_corpus import MENU, corpus
from tests.redaction.support import FakeDetector
from tests.runs_support import create_run

NAME = "Zelda Quimbly"
EMAIL = "zelda.quimbly@planted-corp.example"
PHONE = "+41 79 555 01 23"
PLANTED = (NAME, EMAIL, PHONE, "Quimbly", "555 01 23")
LINE = f"Contact for audit questions: {NAME}, {EMAIL}, {PHONE}.\n"
FILLER = "The audit committee reviewed the controls of the plant and found them adequate. "
NOW = datetime(2026, 11, 27, tzinfo=UTC)


class StubModel:
    """Stands for GLiNER: finds `NAME` in a piece (any case), records every piece it is given."""

    def __init__(self, fail_after: int | None = None) -> None:
        self.pieces: list[str] = []
        self.fail_after = fail_after

    def batch_predict_entities(
        self, batch: Sequence[str], labels: list[str], threshold: float
    ) -> list[list[dict[str, Any]]]:
        if self.fail_after is not None and len(self.pieces) >= self.fail_after:
            raise RuntimeError("model failure")
        self.pieces.extend(batch)
        return [
            [
                {"start": m.start(), "end": m.end()}
                for m in re.finditer(re.escape(NAME), piece, re.IGNORECASE)
            ]
            for piece in batch
        ]


def stub_redactor(model: StubModel) -> Redactor:
    gliner = GlinerDetector(directory=Path("/nowhere"))
    gliner._model = model
    return Redactor(gliner, FakeDetector())


def planted_texts() -> dict[str, str]:
    long_text = (FILLER * 12 + "\n") * 60 + LINE + (FILLER * 12 + "\n") * 5
    return {
        "https://acme.example/a": f"{MENU}{LINE}{MENU}{FILLER * 20}\n{MENU}{LINE}",  # (i) repeated
        "https://acme.example/b": f"{MENU}{LINE}{FILLER * 20}",  # same pieces as /a, other source
        "https://acme.example/table": "\n".join(f"{n} {n * 7} {n * 13}" for n in range(40))
        + f"\n{LINE}"
        + "\n".join(f"{n} {n * 3}" for n in range(40)),  # (ii) next to a numeric table
        "https://acme.example/long.pdf": long_text,  # (iii) above 40,000 characters
    }


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> tuple[StubModel, RedactionGate]:
    model = StubModel()
    gate = RedactionGate(lambda: [], stub_redactor(model))
    monkeypatch.setattr("app.collection.source_store.gate_for", lambda _db: gate)
    monkeypatch.setattr("app.extraction.stage.gate_for", lambda _db: gate)
    return model, gate


def collect(engine: Engine, texts: dict[str, str]) -> tuple[uuid.UUID, uuid.UUID]:
    organisation_id = create_organisation(engine)
    run_id = create_run(engine, organisation_id, stage="collection", enqueue=False)
    database = Database(None, engine)
    with run_piece_cache(run_id):
        for url, text in texts.items():
            record = SourceRecord(url, NOW, "text/html", text, author=f"{NAME} (author)")
            store_source(database, run_id, organisation_id, record)
    return organisation_id, run_id


def test_planted_personal_data_reaches_no_provider_no_store_no_log(
    engine: Engine, wired: tuple[StubModel, RedactionGate], caplog: pytest.LogCaptureFixture
) -> None:
    model, _gate = wired
    texts = planted_texts()
    assert len(texts["https://acme.example/long.pdf"]) > 40_000

    with caplog.at_level(logging.DEBUG):
        organisation_id, run_id = collect(engine, texts)
        adapter = scripted(lambda asked: [])
        stage()(context_for(engine, organisation_id, run_id, providers_with(adapter)))

    with Session(engine) as db:
        rows = list(db.scalars(select(Source).where(Source.run_id == run_id)))
    assert len(rows) == len(texts)
    assert adapter.asked and any("audit" in asked.text for asked in adapter.asked)
    everything = [row.redacted_text for row in rows] + [a.data for a in adapter.asked]
    everything += [row.author or "" for row in rows] + [caplog.text]
    for planted in PLANTED:
        for text in everything:
            at = text.lower().find(planted.lower())
            assert at < 0, (planted, text[max(0, at - 150) : at + 150])
    # The model really was spared work (the test exercises the cache and the skip).
    total = sum(len(chunk_text(t, max_words=detector.MAX_CHUNK_WORDS)) for t in texts.values())
    assert 0 < len(model.pieces) < 2 * total  # without the steps: text and copy of every piece


def test_a_detector_failure_writes_nothing_and_raises(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = StubModel(fail_after=0)
    gate = RedactionGate(lambda: [], stub_redactor(model))
    monkeypatch.setattr("app.collection.source_store.gate_for", lambda _db: gate)

    with pytest.raises(RedactionUnavailable):
        collect(engine, planted_texts())

    with Session(engine) as db:
        assert db.scalars(select(Source)).first() is None


def test_a_cache_error_writes_nothing_and_raises(
    engine: Engine, wired: tuple[StubModel, RedactionGate], monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(_piece: str) -> bytes:
        raise MemoryError

    monkeypatch.setattr(detector, "_digest", broken)

    with pytest.raises(RedactionUnavailable):
        collect(engine, planted_texts())

    with Session(engine) as db:
        assert db.scalars(select(Source)).first() is None


def test_the_cache_is_never_shared_between_runs() -> None:
    model = StubModel()
    redactor = stub_redactor(model)
    text = f"{LINE}{FILLER}"
    with run_piece_cache("run-one"):
        redactor.redact(text)
        first = len(model.pieces)
        redactor.redact(text)
        assert len(model.pieces) == first  # same run: nothing sent again
    with run_piece_cache("run-two"):
        redactor.redact(text)
    assert len(model.pieces) == 2 * first  # another run: read again
    redactor.redact(text)  # no run: no cache
    assert len(model.pieces) == 3 * first


def test_a_piece_without_a_letter_is_not_sent_but_still_redacted_by_rules() -> None:
    model = StubModel()
    out = stub_redactor(model).redact("12 345 678\n99 100 -----").text
    assert model.pieces == [] and out == "12 345 678\n99 100 -----"
    stub_redactor(model).redact(f"{NAME}")
    assert model.pieces == [NAME]


def test_the_output_is_the_same_with_every_step_off_and_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    texts = list(planted_texts().values()) + corpus()["short"]
    outputs = []
    for on in (False, True):
        for name in ("CACHE_PIECES", "SKIP_NON_TEXT", "DEDUPE_CALL"):
            monkeypatch.setattr(detector, name, on)
        redactor = stub_redactor(StubModel())
        with run_piece_cache(f"identical-{on}"):
            outputs.append([redactor.redact(text).text for text in texts])
    assert outputs[0] == outputs[1]


@pytest.mark.model
def test_the_real_model_gives_what_main_gave_on_the_corpus(real_redactor: Redactor) -> None:
    """The small items and the 40,000-character text equal what `main` produced (expected values
    generated on `main`); the 200,000-character item is checked by `measure_perf`."""
    import hashlib

    expected = json.loads((Path(__file__).parent / "perf_expected.json").read_text("utf-8"))
    for name, texts in corpus().items():
        if name == "text_200k":
            continue
        with run_piece_cache(uuid.uuid4()):
            got = [real_redactor.redact(text).text for text in texts]
        if "texts" in expected[name]:
            assert got == expected[name]["texts"], name
        else:
            joined = "\x00".join(got)
            assert len(joined) == expected[name]["chars"], name
            assert hashlib.sha256(joined.encode()).hexdigest() == expected[name]["sha256"], name

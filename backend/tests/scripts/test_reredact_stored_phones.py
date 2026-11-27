"""The in-place re-redaction of phone numbers in named sources (#221)."""

import io
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.models import AssessmentItem, Fact, Source
from app.redaction.text import OMISSION, StoredSourceText
from scripts import reredact_stored_phones as script
from scripts.scan_stored_phones import count_phones
from tests.extraction.support import add_source
from tests.factories import create_organisation
from tests.runs_support import create_run

PHONE = "+33 4 72 00 11 22"
PHONE_DIGITS = ("72 00 11 22", "0011", "472001122")
TEXT = f"Contact the office. Call {PHONE} for orders."
FACT_QUOTE = f"Call {PHONE} for orders."


def run_script(arguments: list[str]) -> tuple[int, str]:
    out = io.StringIO()
    code = script.main(arguments, out)
    return code, out.getvalue()


@pytest.fixture
def database_env(database_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)


def add_fact(
    engine: Engine,
    organisation_id: uuid.UUID,
    run_id: uuid.UUID,
    source_id: uuid.UUID | None,
    field: str,
    quote: str,
) -> uuid.UUID:
    with Session(engine) as db:
        fact = Fact(
            organisation_id=organisation_id,
            run_id=run_id,
            section="Contact",
            field=field,
            quote=quote,
            value="Orders line",
            source_id=source_id,
            version=3,
        )
        db.add(fact)
        db.commit()
        return fact.id


def add_statement(
    engine: Engine, organisation_id: uuid.UUID, run_id: uuid.UUID, fact_id: uuid.UUID, text: str
) -> uuid.UUID:
    with Session(engine) as db:
        item = AssessmentItem(
            organisation_id=organisation_id,
            run_id=run_id,
            position=1,
            kind="strength",
            text=text,
            cited_fact_ids=[str(fact_id)],
            provider="fake",
            model_id="m",
            model_version="1",
            prompt_id="p",
            prompt_version="1",
            generated_at=datetime(2026, 11, 27, tzinfo=UTC),
        )
        db.add(item)
        db.commit()
        return item.id


class World:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.organisation_id = create_organisation(engine)
        self.run_id = create_run(engine, self.organisation_id, enqueue=False)
        self.source = add_source(
            engine, self.organisation_id, self.run_id, "https://shop.example.test/a", TEXT
        )
        self.other = add_source(
            engine, self.organisation_id, self.run_id, "https://other.example.test/b", TEXT
        )
        self.fact = add_fact(
            engine, self.organisation_id, self.run_id, self.source, "contact", FACT_QUOTE
        )
        self.other_fact = add_fact(
            engine, self.organisation_id, self.run_id, self.other, "other", FACT_QUOTE
        )
        self.statement = add_statement(
            engine, self.organisation_id, self.run_id, self.fact, f"Orders go to {PHONE}."
        )

    def source_text(self, source_id: uuid.UUID) -> str:
        with Session(self.engine) as db:
            return db.get_one(Source, source_id).redacted_text

    def fact_row(self, fact_id: uuid.UUID) -> Fact:
        with Session(self.engine) as db:
            return db.get_one(Fact, fact_id)

    def statement_text(self) -> str:
        with Session(self.engine) as db:
            return db.get_one(AssessmentItem, self.statement).text


def assert_no_digits(*outputs: str) -> None:
    everything = "".join(outputs)
    for digits in (PHONE, *PHONE_DIGITS):
        assert digits not in everything
    assert "Contact the office" not in everything


def test_it_refuses_without_a_source_id(
    engine: Engine, database_env: None, capsys: pytest.CaptureFixture[str]
) -> None:
    World(engine)

    with pytest.raises(SystemExit) as stop:
        run_script([])
    with pytest.raises(SystemExit):
        run_script(["--apply"])

    assert stop.value.code == 2
    captured = capsys.readouterr()
    assert_no_digits(captured.out, captured.err)


def test_a_dry_run_writes_nothing_and_prints_counts(
    engine: Engine, database_env: None, capsys: pytest.CaptureFixture[str]
) -> None:
    world = World(engine)

    code, output = run_script(["--source-id", str(world.source)])

    assert code == 0
    assert "DRY RUN" in output
    assert f"SOURCE {world.source}: texts_with_matches=3 before=3 after=0" in output
    assert f"source={world.source} column=redacted_text before=1 after=0" in output
    assert f"fact={world.fact} source={world.source} column=quote before=1 after=0" in output
    assert str(world.other) not in output
    assert world.source_text(world.source) == TEXT
    assert world.fact_row(world.fact).quote == FACT_QUOTE
    assert world.statement_text() == f"Orders go to {PHONE}."
    captured = capsys.readouterr()
    assert_no_digits(output, captured.out, captured.err)


def test_apply_removes_the_phone_from_the_source_and_what_cites_it(
    engine: Engine, database_env: None, capsys: pytest.CaptureFixture[str]
) -> None:
    world = World(engine)

    code, output = run_script(["--source-id", str(world.source), "--apply"])

    assert code == 0
    assert "COMMITTED" in output
    text = world.source_text(world.source)
    assert count_phones(text) == 0
    assert OMISSION in text
    assert text.startswith("Contact the office.")
    fact = world.fact_row(world.fact)
    assert fact.quote is not None
    assert count_phones(fact.quote) == 0
    assert fact.version == 3
    assert fact.source_id == world.source
    assert count_phones(world.statement_text()) == 0
    # Another source is left alone, even with the same text.
    assert world.source_text(world.other) == TEXT
    assert world.fact_row(world.other_fact).quote == FACT_QUOTE
    captured = capsys.readouterr()
    assert_no_digits(output, captured.out, captured.err)


def test_an_unknown_source_stops_without_writing(engine: Engine, database_env: None) -> None:
    world = World(engine)

    code, output = run_script(
        ["--source-id", str(world.source), "--source-id", str(uuid.uuid4()), "--apply"]
    )

    assert code == 1
    assert "NOT FOUND" in output
    assert "ROLLED BACK" in output
    assert world.source_text(world.source) == TEXT


def test_it_rolls_back_when_a_phone_would_remain(
    engine: Engine,
    database_env: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    world = World(engine)

    original = script.rewrite

    def leaves_fact_quotes(text: str, stored: StoredSourceText) -> str:
        return text if text == FACT_QUOTE else original(text, stored)

    monkeypatch.setattr(script, "rewrite", leaves_fact_quotes)

    code, output = run_script(["--source-id", str(world.source), "--apply"])

    assert code == 1
    assert "ROLLED BACK" in output
    assert f"fact={world.fact} source={world.source} column=quote before=1 after=1" in output
    assert world.source_text(world.source) == TEXT
    assert world.fact_row(world.fact).quote == FACT_QUOTE
    assert world.statement_text() == f"Orders go to {PHONE}."
    captured = capsys.readouterr()
    assert_no_digits(output, captured.out, captured.err)

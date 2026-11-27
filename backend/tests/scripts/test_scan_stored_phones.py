"""The read-only phone scan of stored text (#221)."""

import io
import uuid
from typing import Any

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.models import DemoProfile, Organisation, Source
from scripts import scan_stored_phones as scan_script
from tests.extraction.support import add_source
from tests.factories import create_organisation
from tests.runs_support import create_run

PHONE = "+33 4 72 00 11 22"
PHONE_DIGITS = ("72 00 11 22", "0011", "472001122")
PATH_SECRET = "private-person-page"


def run_script(arguments: list[str]) -> tuple[int, str]:
    out = io.StringIO()
    code = scan_script.main(arguments, out)
    return code, out.getvalue()


@pytest.fixture
def database_env(database_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)


def planted(engine: Engine) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    organisation_id = create_organisation(engine)
    run_id = create_run(engine, organisation_id, enqueue=False)
    dirty = add_source(
        engine,
        organisation_id,
        run_id,
        f"https://shop.example.test/{PATH_SECRET}?x=1",
        f"Contact the office. Call {PHONE} for orders.",
    )
    clean = add_source(
        engine, organisation_id, run_id, "https://clean.example.test/a", "Nothing to see here."
    )
    return organisation_id, run_id, dirty, clean


def test_a_planted_phone_is_counted_and_never_printed(
    engine: Engine, database_env: None, capsys: pytest.CaptureFixture[str]
) -> None:
    organisation_id, run_id, dirty, clean = planted(engine)

    code, output = run_script([])

    assert code == 0
    assert (
        f"source organisation={organisation_id} run={run_id} source={dirty} "
        "host=shop.example.test matches=1"
    ) in output
    assert str(clean) not in output
    assert "TOTAL sources: scanned=2 affected=1 matches=1" in output
    captured = capsys.readouterr()
    everything = output + captured.out + captured.err
    for digits in (PHONE, *PHONE_DIGITS):
        assert digits not in everything
    assert PATH_SECRET not in everything
    assert "Contact the office" not in everything


def test_a_clean_source_is_not_listed(engine: Engine, database_env: None) -> None:
    organisation_id = create_organisation(engine)
    run_id = create_run(engine, organisation_id, enqueue=False)
    clean = add_source(engine, organisation_id, run_id, "https://c.example.test/", "No numbers.")

    code, output = run_script([])

    assert code == 0
    assert str(clean) not in output
    assert "TOTAL sources: scanned=1 affected=0 matches=0" in output


def test_the_limit_bounds_the_scan(engine: Engine, database_env: None) -> None:
    planted(engine)

    _, output = run_script(["--limit", "1"])

    assert "scanned=1 " in output


def test_the_session_is_read_only_and_nothing_is_written(engine: Engine) -> None:
    organisation_id = create_organisation(engine)
    with scan_script.read_only_session(engine) as session, pytest.raises(DBAPIError):
        session.add(Organisation(name="Intruder"))
        session.flush()
    with scan_script.read_only_session(engine) as session, pytest.raises(DBAPIError):
        session.add(
            Source(
                organisation_id=organisation_id,
                run_id=create_run(engine, organisation_id, enqueue=False),
                url="https://x.example.test/",
                fetched_at=func.now(),
                content_type="text/html",
                redacted_text="x",
            )
        )
        session.flush()
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(Organisation)) == 1
        assert db.scalar(select(func.count()).select_from(Source)) == 0


def demo_profile(engine: Engine, position: int, quote: str, **extra: Any) -> uuid.UUID:
    with Session(engine) as db:
        profile = DemoProfile(
            position=position,
            supplier_name="Demo Supplier",
            run={"supplier_name": "Demo Supplier", "finished_at": "2026-11-27T10:00:00+00:00"},
            facts=[
                {
                    "id": str(uuid.uuid4()),
                    "field": "contact",
                    "quote": quote,
                    "source_url": "https://demo.example.test/20261127",
                }
            ],
            assessment={"items": [{"statement": extra.get("statement", "Fine.")}]},
            sources=[{"url": "https://demo.example.test/", "content_type": "text/html"}],
        )
        db.add(profile)
        db.commit()
        return profile.id


def test_demo_profiles_are_covered(
    engine: Engine, database_env: None, capsys: pytest.CaptureFixture[str]
) -> None:
    dirty = demo_profile(engine, 1, f"Reach us on {PHONE}.")
    clean = demo_profile(engine, 2, "We make chairs.")
    in_assessment = demo_profile(engine, 3, "We make tables.", statement=f"Call {PHONE} now")

    code, output = run_script([])

    assert code == 0
    assert f"demo_profile id={dirty} position=1 matches=1" in output
    assert f"demo_profile id={in_assessment} position=3 matches=1" in output
    assert str(clean) not in output
    assert "TOTAL demo profiles: scanned=3 affected=2 matches=2" in output
    captured = capsys.readouterr()
    everything = output + captured.out + captured.err
    for digits in (PHONE, *PHONE_DIGITS):
        assert digits not in everything


def test_a_failure_prints_no_detail(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = "postgresql://user:hunter2@nowhere.invalid:1/db"  # noqa: S105 - dummy
    monkeypatch.setenv("DATABASE_URL", secret)

    code = scan_script.main([])

    captured = capsys.readouterr()
    assert code == 1
    assert "hunter2" not in captured.out + captured.err


def test_without_a_url_it_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert scan_script.main([]) == 2

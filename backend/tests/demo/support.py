"""A demo organisation with one finished run, and a client with a recording fake provider."""

import json
import uuid
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import Database, utc_now
from app.demo.build import load_demo_profiles
from app.main import create_app
from app.models import AssessmentItem, DemoProfile, Fact, ProfileRun
from app.profile_definition import load_profile_definition
from app.providers.fake import FakeStructuringAdapter
from tests.assessment.test_drafting import stage_with_table
from tests.assessment.test_stage import answer, priority, setup, strength
from tests.extraction.support import providers_with
from tests.support import BASE_URL

PERSON = "Jo Martin"
AUTHOR = "Alex Author"
SECRET_PATHS = ("usage", "organisation_id", "created_by", "email", "user_id")


@dataclass(frozen=True)
class DemoSetup:
    organisation_id: uuid.UUID
    run_id: uuid.UUID
    fact_ids: dict[str, uuid.UUID]
    settings: Settings


def finished_run(engine: Engine, settings: Settings, **identity: Any) -> DemoSetup:
    """A finished run with facts (one about a person), a source-less assessment draft with a
    statement that cites the person's fact, and the organisation named as the demo organisation."""
    organisation_id, run_id, facts = setup(engine, **identity)
    adapter = FakeStructuringAdapter(
        [
            answer(
                strength(facts["quality_management"]),
                strength(facts["management_team"], f"{PERSON} leads the company."),
            ),
            answer(priority(facts["quality_management"])),
        ]
    )
    stage_with_table(engine, organisation_id, run_id, adapter)
    with Session(engine) as db:
        db.execute(
            update(ProfileRun)
            .where(ProfileRun.id == run_id)
            .values(status="completed", finished_at=utc_now() - timedelta(hours=1))
        )
        db.execute(
            update(Fact)
            .where(Fact.id == facts["quality_management"])
            .values(author=AUTHOR, publisher="Certifier", source_url="https://registry.example/x")
        )
        db.commit()
    return DemoSetup(
        organisation_id,
        run_id,
        facts,
        replace(settings, demo_organisation_id=organisation_id),
    )


def build(engine: Engine, demo: DemoSetup) -> list[DemoProfile]:
    with Session(engine) as db:
        load_demo_profiles(db, demo.settings, load_profile_definition(), demo.organisation_id)
    with Session(engine) as db:
        return list(db.scalars(select(DemoProfile).order_by(DemoProfile.position)))


def stored_json(engine: Engine) -> str:
    return json.dumps(
        [
            [row.run, row.facts, row.assessment, row.sources, row.supplier_name]
            for row in build_rows(engine)
        ],
        default=str,
    )


def build_rows(engine: Engine) -> list[DemoProfile]:
    with Session(engine) as db:
        return list(db.scalars(select(DemoProfile)))


def items_of(engine: Engine, run_id: uuid.UUID) -> list[AssessmentItem]:
    with Session(engine) as db:
        return list(db.scalars(select(AssessmentItem).where(AssessmentItem.run_id == run_id)))


@dataclass
class RecordingClient:
    client: TestClient
    adapter: FakeStructuringAdapter


def client_with_recording_provider(engine: Engine, settings: Settings) -> RecordingClient:
    """An application whose structuring provider records every call (and fails on any)."""
    adapter = FakeStructuringAdapter([])
    app = create_app(settings, engine=engine, providers=providers_with(adapter))
    return RecordingClient(
        TestClient(app, base_url=BASE_URL, raise_server_exceptions=False), adapter
    )


def database_of(engine: Engine) -> Database:
    return Database(None, engine)

"""Rows and helpers for the run tests: identities, runs, usage rows, a worker environment."""

import uuid
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app import queue
from app.config import Settings
from app.db import Database, utc_now
from app.models import Job, LlmUsage, ProfileRun, SupplierIdentity
from app.providers.metering import UsageEntry
from app.providers.store import sync_provider_configs
from app.runs.executor import RUN_JOB
from app.runs.stages import DEFAULT_STAGES, Stage
from app.worker import work_once
from tests.providers.support import catalogue, config

WORKER = "worker-1"


def create_identity(
    engine: Engine,
    organisation_id: uuid.UUID,
    legal_name: str = "Acme Supplies SA",
    confirmed: bool = True,
    website: str | None = None,
    country: str | None = None,
    sector: str | None = None,
    natural_person: bool = False,
) -> uuid.UUID:
    with Session(engine) as db:
        identity = SupplierIdentity(
            organisation_id=organisation_id,
            legal_name=legal_name,
            website=website,
            country=country,
            sector=sector,
            natural_person=natural_person,
            confirmed_at=utc_now() if confirmed else None,
        )
        db.add(identity)
        db.commit()
        return identity.id


def create_run(
    engine: Engine,
    organisation_id: uuid.UUID,
    legal_name: str = "Acme Supplies SA",
    status: str = "queued",
    stage: str = "identity",
    enqueue: bool = True,
) -> uuid.UUID:
    identity_id = create_identity(engine, organisation_id, legal_name)
    with Session(engine) as db:
        run = ProfileRun(
            organisation_id=organisation_id, identity_id=identity_id, status=status, stage=stage
        )
        db.add(run)
        db.flush()
        if enqueue:
            queue.enqueue(db, RUN_JOB, {"run_id": str(run.id)})
        db.commit()
        return run.id


def get_run(engine: Engine, run_id: uuid.UUID) -> ProfileRun:
    with Session(engine) as db:
        return db.scalars(select(ProfileRun).where(ProfileRun.id == run_id)).one()


def jobs_of(engine: Engine) -> list[Job]:
    with Session(engine) as db:
        return list(db.scalars(select(Job).order_by(Job.created_at)).all())


def add_usage(
    engine: Engine, organisation_id: uuid.UUID, run_id: uuid.UUID, cost: str = "0.5"
) -> None:
    """Two provider call rows (one failed) for the run, with the configuration row they need."""
    with Session(engine) as db:
        sync_provider_configs(db, catalogue(config("primary")))
        for outcome in ("failed", "success"):
            entry = UsageEntry(
                organisation_id=organisation_id,
                run_id=run_id,
                provider_config_id="primary",
                provider="google",
                model_id="model-1",
                role="structuring",
                input_tokens=100,
                output_tokens=40,
                reasoning_tokens=10,
                tool_calls=0,
                attempt=1,
                outcome=outcome,
                billed_amount=Decimal(cost),
                billed_currency="EUR",
                exchange_rate=Decimal(1),
                cost=Decimal(cost),
                cost_basis="price_table",
            )
            db.add(LlmUsage(**entry.__dict__))
        db.commit()


def work(
    engine: Engine,
    settings: Settings,
    stages: Mapping[str, Stage] = DEFAULT_STAGES,
    worker_id: str = WORKER,
    now: datetime | None = None,
) -> bool:
    return work_once(
        Database(None, engine),
        settings,
        worker_id,
        stages,
        now=(lambda: now) if now else utc_now,
    )

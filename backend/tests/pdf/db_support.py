"""Database rows for the PDF endpoint tests: a finished run with a few facts."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.models import Fact
from tests.runs_support import create_run

FETCHED = datetime(2026, 11, 3, 10, 30, tzinfo=UTC)


def add_fact(
    engine: Engine,
    organisation_id: uuid.UUID,
    run_id: uuid.UUID,
    field: str,
    value: str | None,
    *,
    section: str = "company_overview",
    status: str = "proposed",
) -> None:
    with Session(engine) as db:
        found = status != "not_found"
        db.add(
            Fact(
                organisation_id=organisation_id,
                run_id=run_id,
                section=section,
                field=field,
                status=status,
                value=value if found else None,
                quote=f"quote for {value}" if found else None,
                source_url="https://www.acme.example/about" if found else None,
                source_type="supplier_claim" if found else None,
                publisher="acme.example" if found else None,
                fetched_at=FETCHED if found else None,
            )
        )
        db.commit()


def finished_run(
    engine: Engine, organisation_id: uuid.UUID, name: str, status: str = "completed"
) -> uuid.UUID:
    run_id = create_run(engine, organisation_id, legal_name=name, status=status, enqueue=False)
    add_fact(engine, organisation_id, run_id, "founding_year", "2005")
    add_fact(engine, organisation_id, run_id, "legal_form", None, status="not_found")
    return run_id

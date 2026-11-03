"""#18: source storage, the collection stage, the guard until #19, and the endpoints."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.collection import source_store
from app.collection.settings import CollectionSettings
from app.collection.source_store import SourceRecord, store_source
from app.collection.stage import RedactionNotWired, make_collection_stage
from app.crawl import build_client
from app.db import Database, utc_now
from app.models import CrawlPermission, ProfileRun, Source, SupplierIdentity
from app.runs.stages import StageContext
from tests.auth_support import send_with_session
from tests.collection.support import CONTACT, HOST, RESOLVER, html
from tests.contract.test_auth_contract import assert_matches_contract
from tests.factories import create_organisation, create_session, create_user
from tests.http_client.support import MockSite
from tests.isolation_support import OwnedResource, OwnerOrganisation, assert_organisation_isolation
from tests.runs_support import create_run, get_run

LIMITS = CollectionSettings(min_delay_seconds=0, backoff_seconds=0)


def record(url: str = f"https://{HOST}/about", text: str = "Acme text") -> SourceRecord:
    return SourceRecord(url, utc_now(), "text/html", text, None)


def set_website(engine: Engine, run_id: uuid.UUID, website: str | None) -> None:
    with Session(engine) as db:
        run = db.get(ProfileRun, run_id)
        assert run is not None
        db.execute(
            update(SupplierIdentity)
            .where(SupplierIdentity.id == run.identity_id)
            .values(website=website)
        )
        db.commit()


def context(engine: Engine, run_id: uuid.UUID, organisation_id: uuid.UUID) -> StageContext:
    return StageContext(
        run_id, organisation_id, "collection", Database(None, engine), None, lambda: None
    )


def test_the_source_is_stored_once_per_run_and_url_and_replaced_on_a_second_store(
    engine: Engine,
) -> None:
    organisation_id = create_organisation(engine)
    run_id = create_run(engine, organisation_id)
    database = Database(None, engine)

    store_source(database, run_id, organisation_id, record(text="first"))
    store_source(database, run_id, organisation_id, record(text="second"))

    with Session(engine) as db:
        (row,) = db.scalars(select(Source)).all()
    assert (row.redacted_text, row.content_type, row.organisation_id) == (
        "second",
        "text/html",
        organisation_id,
    )


def test_every_stored_text_passes_through_the_redaction_hook(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    organisation_id = create_organisation(engine)
    run_id = create_run(engine, organisation_id)
    monkeypatch.setattr(
        source_store, "redact_for_storage", lambda text, gate, context: text.upper()
    )

    store_source(
        Database(None, engine),
        run_id,
        organisation_id,
        SourceRecord(f"https://{HOST}/r.pdf", utc_now(), "application/pdf", "body", "an author"),
    )

    with Session(engine) as db:
        (row,) = db.scalars(select(Source)).all()
    assert (row.redacted_text, row.author) == ("BODY", "AN AUTHOR")


def test_the_guard_lifts_now_that_storage_redacts(monkeypatch: pytest.MonkeyPatch) -> None:
    assert source_store.REDACTION_WIRED is True  # lifted by #19
    make_collection_stage(CONTACT, LIMITS)
    monkeypatch.setattr(source_store, "REDACTION_WIRED", False)
    with pytest.raises(RedactionNotWired):  # the guard itself is kept, should the flag drop again
        make_collection_stage(CONTACT, LIMITS)
    from app.runs.stages import DEFAULT_STAGES

    assert DEFAULT_STAGES["collection"].__name__ == "no_op"  # wiring the stage is not part of #19


def run_stage(engine: Engine, pages: dict, name: str = "Acme Supplies SA") -> uuid.UUID:  # type: ignore[type-arg]
    organisation_id = create_organisation(engine)
    run_id = create_run(engine, organisation_id, legal_name=name)
    set_website(engine, run_id, f"https://{HOST}")
    site = MockSite(pages)
    stage = make_collection_stage(
        CONTACT,
        LIMITS,
        client_factory=lambda: build_client(
            CONTACT, resolver=RESOLVER, inner_transport=site.transport
        ),
    )
    assert stage(context(engine, run_id, organisation_id)) is None
    return run_id


def test_the_stage_stores_sources_records_permissions_and_flags_a_missing_name(
    engine: Engine,
) -> None:
    run_id = run_stage(
        engine,
        {
            (HOST, "/"): html("<h1>Welcome</h1><a href='/about'>About</a>"),
            (HOST, "/about"): html("<p>A family business.</p>"),
        },
    )

    with Session(engine) as db:
        assert {s.url for s in db.scalars(select(Source))} == {
            f"https://{HOST}/",
            f"https://{HOST}/about",
        }
        (permission,) = db.scalars(select(CrawlPermission)).all()
    assert permission.decision == "allowed"
    assert get_run(engine, run_id).identity_to_verify is True


def test_the_stage_does_not_flag_a_run_whose_site_names_the_supplier(engine: Engine) -> None:
    run_id = run_stage(
        engine, {(HOST, "/"): html("<h1>Acme Supplies</h1><p>Bolts since 1950.</p>")}
    )

    assert get_run(engine, run_id).identity_to_verify is False


def make_run_sources(engine: Engine, owner: OwnerOrganisation) -> OwnedResource:
    run_id = create_run(engine, owner.id, enqueue=False)
    store_source(
        Database(None, engine),
        run_id,
        owner.id,
        record(url="https://distinctive-supplier.example/about", text="SECRET BODY TEXT"),
    )
    return OwnedResource(
        path=f"/runs/{run_id}/sources",
        missing_path=f"/runs/{uuid.uuid4()}/sources",
        marker="distinctive-supplier.example",
    )


def test_the_sources_endpoint_lists_url_time_and_type_without_the_text_and_is_isolated(
    client: TestClient, engine: Engine
) -> None:
    assert_organisation_isolation(client, engine, "GET", make_run_sources)

    user = create_user(engine)
    token = create_session(engine, user.id)
    run_id = create_run(engine, user.organisation_id, enqueue=False)
    store_source(Database(None, engine), run_id, user.organisation_id, record())
    response = send_with_session(client, "GET", f"/runs/{run_id}/sources", token)

    assert response.status_code == 200
    (item,) = response.json()["items"]
    assert set(item) == {"id", "url", "fetched_at", "content_type"}
    assert "Acme text" not in response.text
    assert_matches_contract(response, "/runs/{id}/sources", "get")
    run = send_with_session(client, "GET", f"/runs/{run_id}", token)
    assert run.json()["identity_to_verify"] is False
    assert_matches_contract(run, "/runs/{id}", "get")

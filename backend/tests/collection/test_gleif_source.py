"""#142: the GLEIF source of a run (answers mocked, no network)."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.collection import gleif_source
from app.collection.gleif_source import record_page, store_gleif_source
from app.collection.settings import CollectionSettings
from app.collection.source_store import SourceRecord
from app.collection.stage import make_collection_stage
from app.crawl import build_client
from app.db import Database
from app.extraction.source_type import classify_source, is_official_register
from app.models import ProfileRun, RunFailure, Source, SupplierIdentity
from app.registries.http import FetchError
from app.runs.stages import StageContext
from tests.collection.support import CONTACT, HOST, RESOLVER, html
from tests.factories import create_organisation
from tests.http_client.support import MockSite
from tests.registries.gleif_support import (
    CHILD_LEI,
    PARENT_LEI,
    SUB_LEI,
    FakeGleif,
    group_answers,
    lei_record,
    one,
)
from tests.runs_support import create_run

LIMITS = CollectionSettings(min_delay_seconds=0, backoff_seconds=0)


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(gleif_source, "_cache", None)
    yield


def stored_by(fake: FakeGleif) -> tuple[list[SourceRecord], object]:
    stored: list[SourceRecord] = []
    failure = store_gleif_source(SUB_LEI, stored.append, fake)
    return stored, failure


def test_the_source_text_has_the_labelled_lines_and_the_group() -> None:
    stored, failure = stored_by(FakeGleif(group_answers()))

    assert failure is None
    (source,) = stored
    assert source.url == f"https://search.gleif.org/#/record/{SUB_LEI}"
    assert source.content_type == "text/plain"
    lines = source.text.splitlines()
    assert lines[0] == "Legal name: Acme France SAS"
    assert "Legal form: SAS" in lines
    assert "Registration authority entity ID: 552 081 317" in lines
    assert "Legal address: 1 Rue de la Paix, 75002 Paris, FR" in lines
    assert "Headquarters address: 2 Avenue Foch, 75002 Paris, FR" in lines
    assert f"Direct parent: Acme Europe BV (Amsterdam, NL), LEI {CHILD_LEI}" in lines
    assert f"Ultimate parent: Acme Holding GmbH (Munich, DE), LEI {PARENT_LEI}" in lines
    # The parent, the entity and the other active child; the inactive child is left out.
    assert "Group entities registered with an LEI: 3 in 3 countries" in lines
    assert lines[-3:] == [
        "Acme Holding GmbH, Munich, DE",
        "Acme France SAS, Paris, FR",
        "Acme Europe BV, Amsterdam, NL",
    ]
    assert "Acme Old SAS" not in source.text


def test_the_children_come_from_the_ultimate_parent() -> None:
    fake = FakeGleif(group_answers())

    stored_by(fake)

    assert f"{PARENT_LEI}/ultimate-children" in fake.paths
    assert f"{SUB_LEI}/ultimate-children" not in fake.paths


def test_an_entity_with_no_parent_lists_its_own_children() -> None:
    answers = group_answers()
    del answers[f"{SUB_LEI}/ultimate-parent"], answers[f"{SUB_LEI}/direct-parent"]
    answers[f"{SUB_LEI}/ultimate-children"] = answers.pop(f"{PARENT_LEI}/ultimate-children")

    stored, failure = stored_by(FakeGleif(answers))

    assert failure is None
    assert "Ultimate parent" not in stored[0].text
    assert "Group entities registered with an LEI: 2 in 2 countries" in stored[0].text


def test_a_parent_lookup_failing_only_leaves_its_lines_out() -> None:
    answers = group_answers()
    answers[f"{SUB_LEI}/ultimate-parent"] = FetchError("timeout")

    stored, failure = stored_by(FakeGleif(answers))

    assert failure is None and "Legal name: Acme France SAS" in stored[0].text
    assert "Ultimate parent" not in stored[0].text


@pytest.mark.parametrize(
    ("answer", "kind"),
    [
        (FetchError("timeout"), "timeout"),
        (FetchError("unreachable"), "unreachable"),
        (503, "http_error"),
    ],
)
def test_gleif_failing_stores_nothing_and_is_logged(answer: object, kind: str) -> None:
    stored, failure = stored_by(FakeGleif({SUB_LEI: answer}))

    assert stored == []
    assert failure is not None and failure.kind == kind  # type: ignore[attr-defined]
    assert failure.url == record_page(SUB_LEI)  # type: ignore[attr-defined]


def test_no_record_is_logged_and_no_lei_means_no_request() -> None:
    stored, failure = stored_by(FakeGleif({}))
    assert stored == [] and failure is not None

    fake = FakeGleif(group_answers())
    assert store_gleif_source(None, stored.append, fake) is None
    assert fake.paths == []


def test_the_source_is_an_official_register_not_the_suppliers_claim() -> None:
    url = record_page(SUB_LEI)

    assert is_official_register(url)
    assert not is_official_register(f"https://{HOST}/")
    assert classify_source(url, f"https://{HOST}") == "third_party"


# --- the stage -------------------------------------------------------------------------------


def context(engine: Engine, run_id: uuid.UUID, organisation_id: uuid.UUID) -> StageContext:
    return StageContext(
        run_id, organisation_id, "collection", Database(None, engine), None, lambda: None
    )


def run_stage(engine: Engine, gleif: FakeGleif) -> uuid.UUID:
    organisation_id = create_organisation(engine)
    run_id = create_run(engine, organisation_id, legal_name="Acme France SAS")
    with Session(engine) as db:
        run = db.get(ProfileRun, run_id)
        assert run is not None
        db.execute(
            update(SupplierIdentity)
            .where(SupplierIdentity.id == run.identity_id)
            .values(website=f"https://{HOST}", registry_ids={"lei": SUB_LEI})
        )
        db.commit()
    site = MockSite({(HOST, "/"): html("<p>Acme France SAS</p>")})
    stage = make_collection_stage(
        CONTACT,
        LIMITS,
        client_factory=lambda **kw: build_client(
            CONTACT, resolver=RESOLVER, inner_transport=site.transport, **kw
        ),
        gleif_fetch=gleif,
    )
    assert stage(context(engine, run_id, organisation_id)) is None
    return run_id


def sources_in_extraction_order(engine: Engine, run_id: uuid.UUID) -> list[Source]:
    """The order the extraction reads them in (`app.extraction.stage`)."""
    with Session(engine) as db:
        return list(
            db.scalars(
                select(Source)
                .where(Source.run_id == run_id)
                .order_by(Source.fetched_at, Source.url)
            )
        )


def test_the_gleif_source_is_stored_first_with_the_website_after(engine: Engine) -> None:
    run_id = run_stage(engine, FakeGleif(group_answers()))

    rows = sources_in_extraction_order(engine, run_id)

    assert [r.url for r in rows] == [record_page(SUB_LEI), f"https://{HOST}/"]
    assert "Ultimate parent: Acme Holding GmbH" in rows[0].redacted_text
    assert rows[0].content_type == "text/plain"


def test_gleif_down_the_run_continues_and_the_failure_log_says_so(engine: Engine) -> None:
    run_id = run_stage(engine, FakeGleif({SUB_LEI: FetchError("timeout")}))

    rows = sources_in_extraction_order(engine, run_id)
    with Session(engine) as db:
        failures = list(
            db.scalars(
                select(RunFailure).where(RunFailure.run_id == run_id).order_by(RunFailure.position)
            )
        )

    assert [r.url for r in rows] == [f"https://{HOST}/"]
    # The first line of the log; the missing sitemap of the mock site follows it.
    assert (failures[0].url, failures[0].kind) == (record_page(SUB_LEI), "timeout")


def test_the_elf_code_is_labelled_as_a_code_and_free_text_is_the_legal_form() -> None:
    answers = group_answers()
    answers[SUB_LEI] = one(lei_record(SUB_LEI, "Acme France SAS", form=None))
    code_only, _ = stored_by(FakeGleif(answers))

    assert "Legal form code (ELF): 8888" in code_only[0].text.splitlines()
    assert not any(line.startswith("Legal form:") for line in code_only[0].text.splitlines())


def test_the_free_text_is_shown_as_the_legal_form_and_the_code_is_not() -> None:
    (source,), _ = stored_by(FakeGleif(group_answers()))

    assert "Legal form: SAS" in source.text.splitlines()
    assert "8888" not in source.text

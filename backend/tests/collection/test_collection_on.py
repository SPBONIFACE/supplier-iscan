"""#103: the collection stage on in real runs (DEFAULT_STAGES), the ceilings on all outbound
requests, the natural-person rule, and the whole path from POST /runs, with synthetic fixture sites,
mock transports and the fake provider (no network, no key)."""

import logging
import threading
import uuid
from collections.abc import Callable
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.collection.budget import DomainLimitReached, RequestBudget, RequestLimitReached
from app.collection.settings import CollectionSettings, load_collection_settings
from app.collection.stage import make_collection_stage
from app.crawl import build_client
from app.db import Database
from app.models import ProfileRun, RunFailure, Source, SupplierIdentity
from app.providers import Providers, RetrievedUrl
from app.providers.fake import FakeRetrievalAdapter, fake_adapters
from app.redaction import RedactionGate, RedactionUnavailable
from app.runs.executor import RunEnvironment, execute_run
from app.runs.stages import DEFAULT_STAGES, StageContext, no_op
from tests.auth_support import send_with_session
from tests.collection.support import CONTACT, HOST, OTHER, RESOLVER, html
from tests.factories import create_organisation, create_session, create_user
from tests.http_client.support import MockSite, redirect
from tests.providers.support import SENTINEL_KEY, catalogue, config, make_meter
from tests.redaction.conftest import real_redactor  # noqa: F401  (fixture of the model test)
from tests.runs_support import create_identity, create_run, get_run

FAST = CollectionSettings(min_delay_seconds=0, backoff_seconds=0, retries=0)
REAL_BUILD_CLIENT = build_client


def providers_with(adapter: FakeRetrievalAdapter) -> Providers:
    cat = catalogue(config("primary"))
    return Providers(
        cat,
        {"GEMINI_API_KEY": SENTINEL_KEY},
        fake_adapters(cat, retrieval=adapter),
        meter=make_meter(None),
    )


def stage_over(site: MockSite, limits: CollectionSettings = FAST) -> Any:
    return make_collection_stage(
        CONTACT,
        limits,
        client_factory=lambda **kw: build_client(
            CONTACT, resolver=RESOLVER, inner_transport=site.transport, **kw
        ),
    )


def set_identity(engine: Engine, run_id: uuid.UUID, **values: Any) -> None:
    with Session(engine) as db:
        run = db.get(ProfileRun, run_id)
        assert run is not None
        db.execute(
            update(SupplierIdentity).where(SupplierIdentity.id == run.identity_id).values(**values)
        )
        db.commit()


def member(engine: Engine) -> tuple[Any, str]:
    user = create_user(engine)
    return user, create_session(engine, user.id)


def start_over_api(client: TestClient, engine: Engine, **identity: Any) -> tuple[str, uuid.UUID]:
    """A confirmed identity, and a run started with POST /runs."""
    user, token = member(engine)
    identity_id = create_identity(engine, user.organisation_id)
    with Session(engine) as db:
        db.execute(
            update(SupplierIdentity).where(SupplierIdentity.id == identity_id).values(**identity)
        )
        db.commit()
    response = send_with_session(
        client, "POST", "/runs", token, json={"identity_id": str(identity_id)}
    )
    assert response.status_code == 202
    return token, uuid.UUID(response.json()["id"])


@pytest.fixture
def real_wiring(monkeypatch: pytest.MonkeyPatch) -> Callable[[MockSite], None]:
    """The stage of DEFAULT_STAGES as the worker builds it, its client over a mock site."""
    monkeypatch.setenv("CRAWLER_CONTACT_URL", CONTACT)
    monkeypatch.setenv("COLLECT_MIN_DELAY_SECONDS", "0")
    monkeypatch.setenv("COLLECT_BACKOFF_SECONDS", "0")

    def wire(site: MockSite) -> None:
        monkeypatch.setattr(
            "app.collection.stage.build_client",
            lambda contact, **kw: REAL_BUILD_CLIENT(
                contact, resolver=RESOLVER, inner_transport=site.transport, **kw
            ),
        )

    return wire


def work(engine: Engine, run_id: uuid.UUID, providers: Providers | None) -> None:
    stages = {**DEFAULT_STAGES, "extraction": no_op}  # extraction has its own tests
    env = RunEnvironment(Database(None, engine), stages, providers, lambda: None)
    execute_run(env, run_id)


def failures_of(engine: Engine, run_id: uuid.UUID) -> list[RunFailure]:
    with Session(engine) as db:
        return list(db.scalars(select(RunFailure).where(RunFailure.run_id == run_id)))


def sources_of(engine: Engine, run_id: uuid.UUID) -> list[Source]:
    with Session(engine) as db:
        return list(db.scalars(select(Source).where(Source.run_id == run_id)))


# --- the whole path --------------------------------------------------------------------------


def test_a_run_started_over_the_api_stores_redacted_sources_and_the_failure_log(
    client: TestClient, engine: Engine, real_wiring: Callable[[MockSite], None]
) -> None:
    site = MockSite(
        {
            (HOST, "/"): html(
                "<p>Acme Supplies SA. Contact Anna Keller-Brandt at anna@acme.example.</p>"
                "<a href='/about'>About us</a><a href='/missing-sustainability'>Sustainability</a>"
            ),
            (HOST, "/about"): html("<p>A family business.</p>"),
        }
    )
    real_wiring(site)
    token, run_id = start_over_api(client, engine, website=f"https://{HOST}")

    work(engine, run_id, None)

    run = get_run(engine, run_id)
    assert run.status == "completed" and run.identity_to_verify is False
    stored = {source.url: source.redacted_text for source in sources_of(engine, run_id)}
    assert set(stored) == {f"https://{HOST}/", f"https://{HOST}/about"}
    home = stored[f"https://{HOST}/"]
    assert "Acme Supplies SA" in home
    assert "Anna Keller-Brandt" not in home and "anna@acme.example" not in home
    kinds = {failure.kind for failure in failures_of(engine, run_id)}
    assert "http_error" in kinds  # the dead link is in the failure log
    listed = send_with_session(client, "GET", f"/runs/{run_id}/failures", token).json()
    assert len(listed["items"]) == len(failures_of(engine, run_id))
    # The crawler identity of #17 is on every request, the permission checks included.
    assert site.seen and all(CONTACT in request.user_agent for request in site.seen)
    assert any(request.url.endswith("/robots.txt") for request in site.seen)


def test_a_run_that_finds_nothing_ends_insufficient_sources(
    client: TestClient, engine: Engine, real_wiring: Callable[[MockSite], None]
) -> None:
    real_wiring(MockSite({}))  # every page answers 404
    _token, run_id = start_over_api(client, engine, website=f"https://{HOST}")

    work(engine, run_id, providers_with(FakeRetrievalAdapter([[]])))

    run = get_run(engine, run_id)
    assert run.status == "insufficient_sources"
    assert run.identity_to_verify is False  # D-065: nothing found at all is not flagged
    assert sources_of(engine, run_id) == [] and failures_of(engine, run_id)


def test_a_website_without_sources_but_retrieved_sources_flags_the_identity(
    client: TestClient, engine: Engine, real_wiring: Callable[[MockSite], None]
) -> None:
    real_wiring(MockSite({(OTHER, "/iso"): html("<p>Acme Supplies SA is certified.</p>")}))
    _token, run_id = start_over_api(client, engine, website=f"https://{HOST}")
    adapter = FakeRetrievalAdapter([[RetrievedUrl(url=f"https://{OTHER}/iso", snippet="s")]])

    work(engine, run_id, providers_with(adapter))

    run = get_run(engine, run_id)
    assert run.status == "completed" and run.identity_to_verify is True  # D-065
    assert [source.url for source in sources_of(engine, run_id)] == [f"https://{OTHER}/iso"]


def test_a_redaction_failure_pauses_the_run(
    client: TestClient,
    engine: Engine,
    real_wiring: Callable[[MockSite], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_wiring(MockSite({(HOST, "/"): html("<p>Acme Supplies SA</p>")}))
    _token, run_id = start_over_api(client, engine, website=f"https://{HOST}")

    class Failing(RedactionGate):
        def redact(self, text: str, **_: Any) -> Any:
            raise RedactionUnavailable

    monkeypatch.setattr("app.collection.source_store.gate_for", lambda _db: Failing(lambda: ()))

    work(engine, run_id, None)

    assert get_run(engine, run_id).status == "paused"
    assert sources_of(engine, run_id) == []  # nothing unredacted was written


# --- the natural-person rule -----------------------------------------------------------------


def test_the_retrieval_search_is_skipped_for_a_natural_person_without_a_website(
    engine: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    organisation_id = create_organisation(engine)
    run_id = create_run(engine, organisation_id, "Jean Dupont", stage="collection")
    set_identity(engine, run_id, natural_person=True, website=None)
    adapter = FakeRetrievalAdapter([[RetrievedUrl(url=f"https://{OTHER}/x", snippet="s")]])
    context = StageContext(
        run_id,
        organisation_id,
        "collection",
        Database(None, engine),
        providers_with(adapter),
        lambda: None,
    )

    with caplog.at_level(logging.INFO, logger="app.collection.stage"):
        outcome = stage_over(MockSite({}))(context)

    assert adapter.calls == []  # no query left the application
    assert outcome == "insufficient_sources"
    assert "natural person without a website" in caplog.text
    assert "Jean Dupont" not in caplog.text


def test_a_natural_person_with_a_website_is_still_searched(engine: Engine) -> None:
    organisation_id = create_organisation(engine)
    run_id = create_run(engine, organisation_id, stage="collection")
    set_identity(engine, run_id, natural_person=True, website=f"https://{HOST}")
    adapter = FakeRetrievalAdapter([[] for _ in range(4)])  # one per focus
    context = StageContext(
        run_id,
        organisation_id,
        "collection",
        Database(None, engine),
        providers_with(adapter),
        lambda: None,
    )

    stage_over(MockSite({(HOST, "/"): html("<p>Home</p>")}))(context)

    assert len(adapter.calls) == 4


# --- the ceilings on all outbound requests ---------------------------------------------------


def test_the_budget_counts_every_request_and_every_domain() -> None:
    budget = RequestBudget(max_requests=3, max_domains=2)
    budget(httpx2.URL("https://a.example/robots.txt"))
    budget(httpx2.URL("https://www.a.example/x"))  # the same domain
    budget(httpx2.URL("https://b.example/"))
    with pytest.raises(RequestLimitReached):
        budget(httpx2.URL("https://a.example/y"))
    other = RequestBudget(max_requests=10, max_domains=1)
    other(httpx2.URL("https://a.example/"))
    with pytest.raises(DomainLimitReached):
        other(httpx2.URL("https://b.example/"))


def test_the_budget_holds_under_concurrent_requests() -> None:
    budget = RequestBudget(max_requests=100, max_domains=50)
    refused: list[int] = []

    def send(index: int) -> None:
        for _ in range(50):
            try:
                budget(httpx2.URL(f"https://h{index}.example/"))
            except RequestLimitReached:
                refused.append(index)

    threads = [threading.Thread(target=send, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert budget.sent == 100
    assert len(refused) == 8 * 50 - 100


def test_the_default_ceilings_and_their_environment_variables() -> None:
    defaults = load_collection_settings({})
    assert (defaults.max_requests, defaults.max_domains) == (200, 10)
    tuned = load_collection_settings({"COLLECT_MAX_REQUESTS": "40", "COLLECT_MAX_DOMAINS": "3"})
    assert (tuned.max_requests, tuned.max_domains) == (40, 3)


def test_the_request_ceiling_counts_permission_checks_and_the_run_continues(
    engine: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    organisation_id = create_organisation(engine)
    run_id = create_run(engine, organisation_id, stage="collection")
    set_identity(engine, run_id, website=f"https://{HOST}")
    links = "".join(f"<a href='/{name}'>{name}</a>" for name in ("about", "contact", "news"))
    site = MockSite(
        {
            (HOST, "/"): html(f"<p>Acme Supplies SA</p>{links}"),
            (HOST, "/about"): html("<p>About Acme Supplies SA</p>"),
            (HOST, "/contact"): html("<p>Contact</p>"),
            (HOST, "/news"): html("<p>News</p>"),
        }
    )
    limits = CollectionSettings(
        min_delay_seconds=0, backoff_seconds=0, retries=0, max_requests=4, max_attempts=60
    )
    context = StageContext(
        run_id, organisation_id, "collection", Database(None, engine), None, lambda: None
    )

    with caplog.at_level(logging.WARNING):
        outcome = stage_over(site, limits)(context)

    assert len(site.seen) <= 4  # robots.txt and tdmrep.json count, as the home page does
    assert outcome is None and sources_of(engine, run_id)  # the run goes on with what it has
    log = failures_of(engine, run_id)
    capped = [failure for failure in log if failure.kind == "attempt_cap"]
    assert len(capped) == 1 and "limit of requests" in capped[0].message
    assert "limit of requests" in caplog.text


def test_a_redirect_to_a_new_domain_is_refused_at_the_domain_ceiling(engine: Engine) -> None:
    organisation_id = create_organisation(engine)
    run_id = create_run(engine, organisation_id, stage="collection")
    set_identity(engine, run_id, website=f"https://{HOST}")
    site = MockSite({(HOST, "/"): redirect(f"https://{OTHER}/landing")})
    limits = CollectionSettings(min_delay_seconds=0, backoff_seconds=0, retries=0, max_domains=1)
    context = StageContext(
        run_id, organisation_id, "collection", Database(None, engine), None, lambda: None
    )

    outcome = stage_over(site, limits)(context)

    assert outcome == "insufficient_sources"
    assert all(request.host_header != OTHER for request in site.seen)  # never requested
    messages = [failure.message for failure in failures_of(engine, run_id)]
    assert any("limit of websites" in message for message in messages)


# --- the real model --------------------------------------------------------------------------


@pytest.mark.model
def test_the_stage_redacts_a_name_with_the_real_model(
    engine: Engine,
    real_redactor: Any,  # noqa: F811
) -> None:
    organisation_id = create_organisation(engine)
    run_id = create_run(engine, organisation_id, stage="collection")
    set_identity(engine, run_id, website=f"https://{HOST}")
    site = MockSite(
        {
            (HOST, "/"): html(
                "<p>Acme Supplies SA publishes its annual report.</p>"
                "<p>Sustainability officer: Hollis Varney, write to hollis@acme.example</p>"
            )
        }
    )
    context = StageContext(
        run_id, organisation_id, "collection", Database(None, engine), None, lambda: None
    )

    assert stage_over(site)(context) is None

    (source,) = sources_of(engine, run_id)
    assert "Acme Supplies SA" in source.redacted_text
    assert "Varney" not in source.redacted_text and "hollis@" not in source.redacted_text

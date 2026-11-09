"""#20: the collection stage with the retrieval provider (fake), the end state and the endpoints."""

import uuid
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from app.collection.settings import CollectionSettings
from app.collection.stage import make_collection_stage
from app.crawl import build_client
from app.db import Database
from app.models import ProfileRun, RunFailure, Source, SupplierIdentity
from app.providers import Providers, RetrievedUrl
from app.providers.errors import ProviderCallError
from app.providers.fake import FakeRetrievalAdapter, fake_adapters
from app.providers.metering import ListSink
from app.redaction import RedactionGate, RedactionUnavailable
from app.runs.executor import RunEnvironment, execute_run
from app.runs.stages import DEFAULT_STAGES, StageContext, no_op
from tests.auth_support import send_with_session
from tests.collection.support import CONTACT, HOST, OTHER, RESOLVER, html
from tests.contract.test_auth_contract import assert_matches_contract
from tests.factories import create_organisation, create_session, create_user
from tests.http_client.support import MockSite
from tests.isolation_support import OwnedResource, OwnerOrganisation, assert_organisation_isolation
from tests.providers.support import SENTINEL_KEY, catalogue, config, make_meter
from tests.runs_support import create_run, get_run

LIMITS = CollectionSettings(min_delay_seconds=0, backoff_seconds=0, retries=0)
SNIPPET = "SNIPPET-MARKER-ANSWER-TEXT"


def providers_with(adapter: FakeRetrievalAdapter, sink: ListSink | None = None) -> Providers:
    cat = catalogue(config("primary"))
    return Providers(
        cat,
        {"GEMINI_API_KEY": SENTINEL_KEY},
        fake_adapters(cat, retrieval=adapter),
        meter=make_meter(sink),
    )


def set_identity(engine: Engine, run_id: uuid.UUID, **values: Any) -> None:
    with Session(engine) as db:
        run = db.get(ProfileRun, run_id)
        assert run is not None
        db.execute(
            update(SupplierIdentity).where(SupplierIdentity.id == run.identity_id).values(**values)
        )
        db.commit()


def make_stage(pages: dict[tuple[str, str], httpx2.Response]) -> Any:
    site = MockSite(pages)
    return make_collection_stage(
        CONTACT,
        LIMITS,
        client_factory=lambda **kw: build_client(
            CONTACT, resolver=RESOLVER, inner_transport=site.transport, **kw
        ),
    )


def environment(engine: Engine, stage: Any, providers: Providers | None) -> RunEnvironment:
    stages = {**DEFAULT_STAGES, "collection": stage, "extraction": no_op}
    return RunEnvironment(Database(None, engine), stages, providers, lambda: None)


def start(engine: Engine, website: str | None = f"https://{HOST}", **identity: Any) -> tuple:  # type: ignore[type-arg]
    organisation_id = create_organisation(engine)
    run_id = create_run(engine, organisation_id, stage="collection", status="queued")
    set_identity(engine, run_id, website=website, **identity)
    return organisation_id, run_id


def failures_of(engine: Engine, run_id: uuid.UUID) -> list[RunFailure]:
    with Session(engine) as db:
        return list(
            db.scalars(
                select(RunFailure).where(RunFailure.run_id == run_id).order_by(RunFailure.position)
            )
        )


def sources_of(engine: Engine) -> list[Source]:
    with Session(engine) as db:
        return list(db.scalars(select(Source)))


def test_retrieved_urls_are_stored_like_sources_and_the_snippet_never_is(engine: Engine) -> None:
    _org, run_id = start(engine, country="FR")
    adapter = FakeRetrievalAdapter(
        [[RetrievedUrl(url=f"https://{OTHER}/iso", snippet=SNIPPET)], [], [], []]
    )
    sink = ListSink()
    stage = make_stage(
        {
            (HOST, "/"): html("<p>Acme Supplies SA</p>"),
            (OTHER, "/iso"): html("<p>Certificate of Acme Supplies SA</p>"),
        }
    )

    execute_run(environment(engine, stage, providers_with(adapter, sink)), run_id)

    urls = {s.url for s in sources_of(engine)}
    assert urls == {f"https://{HOST}/", f"https://{OTHER}/iso"}
    assert all(SNIPPET not in s.redacted_text for s in sources_of(engine))
    assert all(SNIPPET not in f.message for f in failures_of(engine, run_id))
    assert get_run(engine, run_id).status == "completed"
    assert len(adapter.calls) == 4  # one request per focus
    for call in adapter.calls:  # identity record and lacking groups, through the gate
        text = call.query.text
        assert "Acme Supplies SA" in text and "FR" in text and f"https://{HOST}" in text
        assert "about" in text and "certifications" in text
    # metered through #12 against the run, once per request
    assert [(e.role, e.run_id) for e in sink.entries] == [("retrieval", run_id)] * 4


def test_a_natural_persons_name_and_address_are_redacted_before_the_provider(
    engine: Engine,
) -> None:
    _org, run_id = start(
        engine,
        natural_person=True,
        legal_name="Zoe Brandstetter",
        registered_address="12 Rue des Lilas, 69003 Lyon",
    )
    adapter = FakeRetrievalAdapter([[] for _ in range(4)])
    stage = make_stage({})

    execute_run(environment(engine, stage, providers_with(adapter)), run_id)

    assert len(adapter.calls) == 4  # every focus's request passes the gate
    for call in adapter.calls:
        assert "Brandstetter" not in call.query.text and "Zoe" not in call.query.text
        assert "Lilas" not in call.query.text and "[…]" in call.query.text


def test_a_provider_outage_is_logged_and_the_run_continues_with_its_other_sources(
    engine: Engine,
) -> None:
    _org, run_id = start(engine)
    outage = ProviderCallError(provider="google", config_id="primary", kind="unavailable")
    stage = make_stage({(HOST, "/"): html("<p>Acme Supplies SA</p>")})

    execute_run(
        environment(engine, stage, providers_with(FakeRetrievalAdapter([outage, [], [], []]))),
        run_id,
    )

    run = get_run(engine, run_id)
    assert run.status == "completed"
    (failure,) = [f for f in failures_of(engine, run_id) if f.strategy == "retrieval"]
    assert failure.kind == "provider_unavailable" and failure.url is None
    assert len(sources_of(engine)) == 1


def test_an_unusable_provider_answer_is_logged_and_the_run_continues(engine: Engine) -> None:
    _org, run_id = start(engine)
    bad = ProviderCallError(provider="google", config_id="primary", kind="invalid_response")
    stage = make_stage({(HOST, "/"): html("<p>Acme Supplies SA</p>")})

    adapter = FakeRetrievalAdapter([bad, [], bad, []])

    execute_run(environment(engine, stage, providers_with(adapter)), run_id)

    # each focus's failure keeps its own kind; the other focuses still ran
    kinds = [f.kind for f in failures_of(engine, run_id) if f.strategy == "retrieval"]
    assert kinds == ["invalid_response", "invalid_response"] and len(adapter.calls) == 4
    assert get_run(engine, run_id).status == "completed"


def test_when_every_strategy_fails_the_run_ends_insufficient_sources_without_quota(
    engine: Engine,
) -> None:
    _org, run_id = start(engine)
    adapter = FakeRetrievalAdapter([[RetrievedUrl(url=f"https://{OTHER}/gone")]])
    stage = make_stage({})

    execute_run(environment(engine, stage, providers_with(adapter)), run_id)

    run = get_run(engine, run_id)
    assert (run.status, run.counts_against_quota) == ("insufficient_sources", False)
    assert run.identity_to_verify is False  # D-065: nothing at all is not flagged
    assert run.finished_at is not None and not sources_of(engine)
    assert {f.strategy for f in failures_of(engine, run_id)} == {"website", "sitemap", "retrieval"}


def test_no_website_and_nothing_retrieved_ends_insufficient_sources(engine: Engine) -> None:
    _org, run_id = start(engine, website=None)

    execute_run(
        environment(engine, make_stage({}), providers_with(FakeRetrievalAdapter([[]]))), run_id
    )

    assert get_run(engine, run_id).status == "insufficient_sources"


def test_website_without_sources_but_retrieved_sources_is_flagged(engine: Engine) -> None:
    _org, run_id = start(engine)
    adapter = FakeRetrievalAdapter([[RetrievedUrl(url=f"https://{OTHER}/profile")]])
    stage = make_stage({(OTHER, "/profile"): html("<p>Acme Supplies SA</p>")})

    execute_run(environment(engine, stage, providers_with(adapter)), run_id)

    run = get_run(engine, run_id)
    assert run.identity_to_verify is True and run.status == "completed"


def test_a_redaction_failure_pauses_the_run_and_is_not_insufficient_sources(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    _org, run_id = start(engine)
    adapter = FakeRetrievalAdapter([[]])

    class Failing(RedactionGate):
        def redact(self, text: str, **_: Any) -> Any:
            raise RedactionUnavailable

    monkeypatch.setattr("app.collection.stage.gate_for", lambda _db: Failing(lambda: ()))

    execute_run(environment(engine, make_stage({}), providers_with(adapter)), run_id)

    assert get_run(engine, run_id).status == "paused"
    assert adapter.calls == []  # nothing was sent


def test_a_stage_without_providers_still_collects_the_website(engine: Engine) -> None:
    organisation_id, run_id = start(engine)
    stage = make_stage({(HOST, "/"): html("<p>Acme Supplies SA</p>")})
    context = StageContext(
        run_id, organisation_id, "collection", Database(None, engine), None, lambda: None
    )

    assert stage(context) is None
    assert len(sources_of(engine)) == 1


def test_the_stage_executed_again_replaces_its_failure_log(engine: Engine) -> None:
    organisation_id, run_id = start(engine)
    stage = make_stage({(HOST, "/"): html("<p>Acme Supplies SA</p>")})
    context = StageContext(
        run_id, organisation_id, "collection", Database(None, engine), None, lambda: None
    )

    stage(context)
    first = len(failures_of(engine, run_id))
    stage(context)

    assert first > 0 and len(failures_of(engine, run_id)) == first


def make_failures(engine: Engine, owner: OwnerOrganisation) -> OwnedResource:
    run_id = create_run(engine, owner.id, enqueue=False)
    with Session(engine) as db:
        db.add(
            RunFailure(
                organisation_id=owner.id,
                run_id=run_id,
                position=0,
                url="https://distinctive-failure.example/x",
                strategy="website",
                kind="http_error",
                next_strategy="sitemap",
                message="The page answered with an error and could not be read.",
            )
        )
        db.commit()
    return OwnedResource(
        path=f"/runs/{run_id}/failures",
        missing_path=f"/runs/{uuid.uuid4()}/failures",
        marker="distinctive-failure.example",
    )


def test_the_failures_endpoint_is_isolated_and_matches_the_contract(
    client: TestClient, engine: Engine
) -> None:
    assert_organisation_isolation(client, engine, "GET", make_failures)

    user = create_user(engine)
    token = create_session(engine, user.id)
    run_id = create_run(engine, user.organisation_id, status="insufficient_sources", enqueue=False)
    with Session(engine) as db:
        db.add(
            RunFailure(
                organisation_id=user.organisation_id,
                run_id=run_id,
                position=0,
                url=None,
                strategy="retrieval",
                kind="provider_unavailable",
                next_strategy=None,
                message="The retrieval provider is unavailable.",
            )
        )
        db.commit()

    response = send_with_session(client, "GET", f"/runs/{run_id}/failures", token)
    assert response.status_code == 200
    assert response.json()["items"][0]["kind"] == "provider_unavailable"
    assert_matches_contract(response, "/runs/{id}/failures", "get")
    run = send_with_session(client, "GET", f"/runs/{run_id}", token)
    assert run.json()["insufficient_sources_explanation"]
    assert_matches_contract(run, "/runs/{id}", "get")
    other = create_run(engine, user.organisation_id, status="running", enqueue=False)
    running = send_with_session(client, "GET", f"/runs/{other}", token)
    assert running.json()["insufficient_sources_explanation"] is None

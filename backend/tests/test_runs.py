"""Profile runs (#13): the endpoints, the worker, stop, pause and resume, the queue."""

import threading
import uuid
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app import queue
from app.config import ConfigurationError, Settings
from app.db import Database, utc_now
from app.errors import NOT_FOUND
from app.models import Job, ProfileRun, UsageEvent
from app.providers.errors import ProviderCallError
from app.redaction import RedactionUnavailable
from app.runs.executor import INTERRUPTED, RUN_JOB
from app.runs.stages import DEFAULT_STAGES, DependencyUnavailable, Stage, StageContext
from app.worker import MAX_ATTEMPTS
from tests.auth_support import assert_requires_session, send_with_session
from tests.factories import create_organisation, create_session, create_user
from tests.isolation_support import OwnedResource, OwnerOrganisation, assert_organisation_isolation
from tests.runs_support import (
    add_usage,
    create_identity,
    create_run,
    get_run,
    jobs_of,
    work,
)
from tests.support import make_client

STAGES = ("identity", "collection", "extraction", "assessment")


def member_session(engine: Engine) -> tuple[Any, str]:
    user = create_user(engine)
    return user, create_session(engine, user.id)


def call(client: TestClient, method: str, path: str, token: str, **kwargs: Any) -> Any:
    return send_with_session(client, method, path, token, **kwargs)


class Counter:
    """Stages that count their executions and may raise on a given stage."""

    def __init__(self, fail_at: str | None = None, error: Exception | None = None) -> None:
        self.calls: list[str] = []
        self.fail_at = fail_at
        self.error = error

    def stages(self) -> dict[str, Stage]:
        def make(name: str) -> Stage:
            def stage(context: StageContext) -> None:
                self.calls.append(name)
                if name == self.fail_at and self.error is not None:
                    raise self.error

            return stage

        return {name: make(name) for name in STAGES}


# --- POST /runs ------------------------------------------------------------------------------


def test_start_queues_the_run_without_executing_a_stage(client: TestClient, engine: Engine) -> None:
    user, token = member_session(engine)
    identity_id = create_identity(engine, user.organisation_id)

    response = call(client, "POST", "/runs", token, json={"identity_id": str(identity_id)})

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["stage"] == "identity"
    assert body["supplier_name"] == "Acme Supplies SA"
    assert body["usage"]["calls"] == 0
    run = get_run(engine, uuid.UUID(body["id"]))
    assert run.started_at is None  # nothing executed in the request
    jobs = jobs_of(engine)
    # The payload also holds the request's trace (#51), so that the worker continues it.
    assert [(job.kind, job.state, set(job.payload)) for job in jobs] == [
        (RUN_JOB, "queued", {"run_id", "traceparent"})
    ]
    assert jobs[0].payload["run_id"] == body["id"]
    with Session(engine) as db:
        events = db.scalars(select(UsageEvent).where(UsageEvent.kind == "run")).all()
    assert [(event.user_id, event.organisation_id) for event in events] == [
        (user.id, user.organisation_id)
    ]


def test_start_refuses_unconfirmed_unknown_and_foreign_identities(
    client: TestClient, engine: Engine
) -> None:
    user, token = member_session(engine)
    unconfirmed = create_identity(engine, user.organisation_id, confirmed=False)
    foreign = create_identity(engine, create_organisation(engine, name="Other"))

    for identity_id in (unconfirmed, foreign, uuid.uuid4()):
        response = call(client, "POST", "/runs", token, json={"identity_id": str(identity_id)})
        assert response.status_code == 404
        assert response.json() == {"detail": NOT_FOUND}
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(ProfileRun)) == 0
        assert db.scalar(select(func.count()).select_from(UsageEvent)) == 0
    assert jobs_of(engine) == []


def test_start_requires_a_session_and_a_valid_body(client: TestClient, engine: Engine) -> None:
    assert_requires_session(
        client, engine, "POST", "/runs", json={"identity_id": str(uuid.uuid4())}
    )
    _, token = member_session(engine)

    assert call(client, "POST", "/runs", token, json={"identity_id": "nope"}).status_code == 422
    assert call(client, "POST", "/runs", token, json={}).status_code == 422


# --- GET /runs, GET /runs/{id} ---------------------------------------------------------------


def test_get_run_shows_status_stage_models_tokens_and_cost(
    client: TestClient, engine: Engine
) -> None:
    user, token = member_session(engine)
    run_id = create_run(engine, user.organisation_id, status="running", stage="collection")
    add_usage(engine, user.organisation_id, run_id)

    body = call(client, "GET", f"/runs/{run_id}", token).json()

    assert (body["status"], body["stage"]) == ("running", "collection")
    usage = body["usage"]
    assert (usage["calls"], usage["input_tokens"], usage["output_tokens"]) == (2, 200, 80)
    assert usage["reasoning_tokens"] == 20
    assert usage["cost"] == "1.00000000"  # the failed attempt counts
    assert usage["roles"] == [
        {"role": "structuring", "config_id": "primary", "provider": "google", "model_id": "model-1"}
    ]
    assert body["counts_against_quota"] is True


def test_list_is_newest_first_and_scoped(client: TestClient, engine: Engine) -> None:
    user, token = member_session(engine)
    first = create_run(engine, user.organisation_id)
    second = create_run(engine, user.organisation_id)
    create_run(engine, create_organisation(engine, name="Other"))

    ids = [item["id"] for item in call(client, "GET", "/runs", token).json()["items"]]

    assert ids == [str(second), str(first)]


def test_a_run_carries_the_identity_header_of_the_supplier_card(
    client: TestClient, engine: Engine
) -> None:
    user, token = member_session(engine)
    identity_id = create_identity(
        engine,
        user.organisation_id,
        website="https://acme-supplies.example",
        country="France",
        sector="Precision machining",
        natural_person=True,
    )

    started = call(client, "POST", "/runs", token, json={"identity_id": str(identity_id)}).json()
    read = call(client, "GET", f"/runs/{started['id']}", token).json()
    listed = call(client, "GET", "/runs", token).json()["items"][0]

    for body in (started, read, listed):
        assert body["supplier_website"] == "https://acme-supplies.example"
        assert (body["supplier_country"], body["supplier_sector"]) == (
            "France",
            "Precision machining",
        )
        assert body["natural_person"] is True


def test_a_run_without_website_country_or_sector_says_so_with_nulls(
    client: TestClient, engine: Engine
) -> None:
    user, token = member_session(engine)
    run_id = create_run(engine, user.organisation_id)

    body = call(client, "GET", f"/runs/{run_id}", token).json()

    assert body["supplier_website"] is body["supplier_country"] is body["supplier_sector"] is None
    assert body["natural_person"] is False


def test_a_hosted_administrator_gets_no_identity_header(engine: Engine, settings: Settings) -> None:
    organisation_id = create_organisation(engine)
    token = create_session(
        engine, create_user(engine, role="admin", organisation_id=organisation_id).id
    )
    identity_id = create_identity(
        engine,
        organisation_id,
        website="https://secret-supplier.example",
        country="Elbonia",
        sector="Secret sector",
        natural_person=True,
    )
    with Session(engine) as db:
        run = ProfileRun(organisation_id=organisation_id, identity_id=identity_id)
        db.add(run)
        db.commit()
        run_id = run.id
    hosted = make_client(settings=replace(settings, instance_mode="hosted"), engine=engine)

    body = call(hosted, "GET", f"/runs/{run_id}", token)

    text = body.text
    for secret in ("secret-supplier", "Elbonia", "Secret sector"):
        assert secret not in text
    assert body.json()["natural_person"] is False


def admin_sees(engine: Engine, settings: Settings, mode: str) -> str:
    organisation_id = create_organisation(engine)
    token = create_session(
        engine, create_user(engine, role="admin", organisation_id=organisation_id).id
    )
    run_id = create_run(engine, organisation_id, legal_name="Secret Supplier SA")
    hosted = make_client(
        settings=replace(settings, instance_mode=mode),  # type: ignore[arg-type]
        engine=engine,
    )
    one = call(hosted, "GET", f"/runs/{run_id}", token)
    many = call(hosted, "GET", "/runs", token)
    assert (one.status_code, many.status_code) == (200, 200)
    assert one.json()["status"] == "queued"
    return str(one.text + many.text)


def test_a_hosted_administrator_gets_run_metadata_without_the_supplier_name(
    engine: Engine, settings: Settings
) -> None:
    assert "Secret Supplier" not in admin_sees(engine, settings, "hosted")


def test_the_self_hosted_local_administrator_reads_names_in_their_organisation(
    engine: Engine, settings: Settings
) -> None:
    assert "Secret Supplier" in admin_sees(engine, settings, "self_hosted")


def make_run_resource(engine: Engine, owner: OwnerOrganisation) -> OwnedResource:
    run_id = create_run(engine, owner.id, legal_name="Distinctive Supplier SA")
    return OwnedResource(
        path=f"/runs/{run_id}", missing_path=f"/runs/{uuid.uuid4()}", marker="Distinctive Supplier"
    )


def make_run_list(engine: Engine, owner: OwnerOrganisation) -> OwnedResource:
    create_run(engine, owner.id, legal_name="Distinctive Supplier SA")
    return OwnedResource(path="/runs", missing_path=None, marker="Distinctive Supplier")


def test_run_endpoints_are_isolated(client: TestClient, engine: Engine) -> None:
    assert_organisation_isolation(client, engine, "GET", make_run_resource)
    assert_organisation_isolation(client, engine, "GET", make_run_list)
    assert_organisation_isolation(client, engine, "POST", make_run_resource_stop)
    assert_organisation_isolation(client, engine, "POST", make_paused_run_resume)


def make_run_resource_stop(engine: Engine, owner: OwnerOrganisation) -> OwnedResource:
    run_id = create_run(engine, owner.id)
    return OwnedResource(
        path=f"/runs/{run_id}/stop", missing_path=f"/runs/{uuid.uuid4()}/stop", marker="Distinctive"
    )


def make_paused_run_resume(engine: Engine, owner: OwnerOrganisation) -> OwnedResource:
    run_id = create_run(engine, owner.id, status="paused", enqueue=False)
    return OwnedResource(
        path=f"/runs/{run_id}/resume",
        missing_path=f"/runs/{uuid.uuid4()}/resume",
        marker="Distinctive",
    )


def test_start_is_isolated(client: TestClient, engine: Engine) -> None:
    # Another organisation's identity answers the same 404 as an unknown one.
    owner_identity = create_identity(
        engine, create_organisation(engine, name="Owner"), "Distinctive Supplier SA"
    )
    _, token = member_session(engine)
    foreign = call(client, "POST", "/runs", token, json={"identity_id": str(owner_identity)})
    unknown = call(client, "POST", "/runs", token, json={"identity_id": str(uuid.uuid4())})
    assert foreign.status_code == unknown.status_code == 404
    assert foreign.json() == unknown.json()
    assert "Distinctive" not in foreign.text


# --- The worker ------------------------------------------------------------------------------


def test_the_worker_runs_the_stages_in_order_and_completes(
    client: TestClient, engine: Engine, settings: Settings
) -> None:
    user, token = member_session(engine)
    identity_id = create_identity(engine, user.organisation_id)
    run_id = call(client, "POST", "/runs", token, json={"identity_id": str(identity_id)}).json()[
        "id"
    ]
    counter = Counter()

    assert work(engine, settings, counter.stages()) is True
    assert work(engine, settings, counter.stages()) is False  # the queue is empty

    run = get_run(engine, uuid.UUID(run_id))
    assert counter.calls == list(STAGES)
    assert run.status == "completed"
    assert run.started_at is not None and run.finished_at is not None
    assert [job.state for job in jobs_of(engine)] == ["done"]
    assert call(client, "GET", f"/runs/{run_id}", token).json()["status"] == "completed"


def test_default_stages_run_collection_and_end_a_run_without_sources(
    engine: Engine, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CRAWLER_CONTACT_URL", "https://iscan.example/contact")
    run_id = create_run(engine, create_organisation(engine))  # no website, no providers

    work(engine, settings, DEFAULT_STAGES)

    assert get_run(engine, run_id).status == "insufficient_sources"


def test_stages_get_the_call_context_of_the_run(engine: Engine, settings: Settings) -> None:
    organisation_id = create_organisation(engine)
    run_id = create_run(engine, organisation_id)
    seen: list[Any] = []

    def stage(context: StageContext) -> None:
        seen.append(context.call_context)

    work(engine, settings, {name: stage for name in STAGES})

    assert {(c.organisation_id, c.run_id) for c in seen} == {(organisation_id, run_id)}


def test_llm_usage_references_the_run(engine: Engine) -> None:
    organisation_id = create_organisation(engine)
    with pytest.raises(Exception, match="fk_llm_usage_run_id_profile_runs"):
        add_usage(engine, organisation_id, uuid.uuid4())


# --- Queue: concurrency and lease ------------------------------------------------------------


def test_two_workers_never_claim_the_same_job(engine: Engine) -> None:
    database = Database(None, engine)
    with Session(engine) as db:
        for index in range(20):
            queue.enqueue(db, RUN_JOB, {"run_id": str(index)})
        db.commit()
    claimed: list[str] = []
    lock = threading.Lock()
    barrier = threading.Barrier(4)

    def worker(name: str) -> None:
        barrier.wait()
        while True:
            with database.session() as db:
                job = queue.claim(db, name, timedelta(minutes=5), utc_now(), (RUN_JOB,))
            if job is None:
                return
            with lock:
                claimed.append(job.payload["run_id"])

    threads = [threading.Thread(target=worker, args=(f"w{n}",)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(claimed, key=int) == [str(index) for index in range(20)]  # each exactly once


def test_two_workers_never_process_the_same_run(engine: Engine, settings: Settings) -> None:
    run_id = create_run(engine, create_organisation(engine))
    counter = Counter()
    barrier = threading.Barrier(2)

    def worker(name: str) -> None:
        barrier.wait()
        work(engine, settings, counter.stages(), worker_id=name)

    threads = [threading.Thread(target=worker, args=(f"w{n}",)) for n in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert counter.calls == list(STAGES)  # once
    assert get_run(engine, run_id).status == "completed"


def test_a_run_whose_worker_died_is_reclaimed_after_the_lease(
    engine: Engine, settings: Settings
) -> None:
    run_id = create_run(engine, create_organisation(engine))
    database = Database(None, engine)
    start = utc_now()
    with database.session() as db:  # a worker claims the job, starts the run, then dies
        job = queue.claim(db, "dead-worker", settings.run_lease, start, (RUN_JOB,))
    assert job is not None
    with Session(engine) as db:
        run = db.get(ProfileRun, run_id)
        assert run is not None
        run.status, run.stage = "running", "extraction"
        db.commit()
    counter = Counter()

    assert work(engine, settings, counter.stages(), now=start + timedelta(seconds=1)) is False
    reclaimed = work(engine, settings, counter.stages(), "w2", now=start + settings.run_lease * 2)

    assert reclaimed is True
    assert counter.calls == ["extraction", "assessment"]  # continues from its stage
    assert get_run(engine, run_id).status == "completed"
    assert [(j.state, j.attempts, j.locked_by) for j in jobs_of(engine)] == [("done", 2, "w2")]


def test_a_job_that_kills_its_worker_too_often_ends_the_run(
    engine: Engine, settings: Settings
) -> None:
    run_id = create_run(engine, create_organisation(engine))
    with Session(engine) as db:
        job = db.scalars(select(Job)).one()
        job.state, job.attempts = "running", MAX_ATTEMPTS
        job.lease_expires_at = utc_now() - timedelta(seconds=1)
        run = db.get(ProfileRun, run_id)
        assert run is not None
        run.status = "running"
        db.commit()

    work(engine, settings, Counter().stages())

    run = get_run(engine, run_id)
    assert (run.status, run.error) == ("failed", INTERRUPTED)


@pytest.mark.parametrize("status", ["queued", "paused"])
def test_the_attempt_cap_ends_a_run_that_never_reached_running(
    engine: Engine, settings: Settings, status: str
) -> None:
    """#13 follow-up: workers dying between claiming the job and starting the run leave it
    `queued`; the cap ends it `failed` whatever its (non-final) status, not for ever queued."""
    run_id = create_run(engine, create_organisation(engine), status=status)
    with Session(engine) as db:
        job = db.scalars(select(Job)).one()
        job.state, job.attempts = "running", MAX_ATTEMPTS
        job.lease_expires_at = utc_now() - timedelta(seconds=1)
        db.commit()
    counter = Counter()

    work(engine, settings, counter.stages())

    run = get_run(engine, run_id)
    assert (run.status, run.error) == ("failed", INTERRUPTED)
    assert run.finished_at is not None and counter.calls == []
    assert [(j.state, j.attempts) for j in jobs_of(engine)] == [("done", MAX_ATTEMPTS + 1)]


def test_the_attempt_cap_leaves_a_finished_run_as_it_is(engine: Engine, settings: Settings) -> None:
    run_id = create_run(engine, create_organisation(engine), status="completed")
    with Session(engine) as db:
        job = db.scalars(select(Job)).one()
        job.state, job.attempts = "running", MAX_ATTEMPTS
        job.lease_expires_at = utc_now() - timedelta(seconds=1)
        db.commit()

    work(engine, settings, Counter().stages())

    assert (get_run(engine, run_id).status, get_run(engine, run_id).error) == ("completed", None)


def test_a_worker_that_lost_its_lease_stops_without_finishing_the_job(
    engine: Engine, settings: Settings
) -> None:
    create_run(engine, create_organisation(engine))

    def steal(context: StageContext) -> None:
        with Session(engine) as db:  # another worker took the job over
            job = db.scalars(select(Job)).one()
            job.locked_by = "someone-else"
            db.commit()
        context.check_stop()

    work(engine, settings, {name: steal for name in STAGES})

    assert [(j.state, j.locked_by) for j in jobs_of(engine)] == [("running", "someone-else")]


# --- Stop ------------------------------------------------------------------------------------


def test_stop_ends_a_queued_run_at_once_and_the_worker_leaves_it(
    client: TestClient, engine: Engine, settings: Settings
) -> None:
    user, token = member_session(engine)
    run_id = create_run(engine, user.organisation_id)
    counter = Counter()

    response = call(client, "POST", f"/runs/{run_id}/stop", token)
    work(engine, settings, counter.stages())

    assert response.status_code == 200
    assert response.json()["status"] == "stopped"
    assert counter.calls == []
    assert [job.state for job in jobs_of(engine)] == ["done"]


def test_any_member_of_the_organisation_can_stop(client: TestClient, engine: Engine) -> None:
    user, _ = member_session(engine)
    colleague = create_user(engine, organisation_id=user.organisation_id)
    run_id = create_run(engine, user.organisation_id)

    token = create_session(engine, colleague.id)

    assert call(client, "POST", f"/runs/{run_id}/stop", token).status_code == 200


def test_stop_during_a_stage_ends_the_run_before_the_next_stage(
    client: TestClient, engine: Engine, settings: Settings
) -> None:
    user, token = member_session(engine)
    run_id = create_run(engine, user.organisation_id)
    counter = Counter()
    stages = counter.stages()
    collection = stages["collection"]
    answers: list[Any] = []

    def stop_while_collecting(context: StageContext) -> None:
        collection(context)
        answers.append(call(client, "POST", f"/runs/{run_id}/stop", token))

    stages["collection"] = stop_while_collecting
    work(engine, settings, stages)

    assert answers[0].status_code == 200
    assert answers[0].json()["status"] == "running"
    assert answers[0].json()["stop_requested"] is True
    assert counter.calls == ["identity", "collection"]  # extraction never started
    assert get_run(engine, run_id).status == "stopped"


def test_stop_is_honoured_before_the_next_provider_call(
    client: TestClient, engine: Engine, settings: Settings
) -> None:
    user, token = member_session(engine)
    run_id = create_run(engine, user.organisation_id)
    after_stop: list[str] = []

    def stage(context: StageContext) -> None:
        call(client, "POST", f"/runs/{run_id}/stop", token)
        context.check_stop()  # the call a stage makes before each provider call
        after_stop.append("provider call")

    work(engine, settings, {name: stage for name in STAGES})

    assert after_stop == []
    assert get_run(engine, run_id).status == "stopped"


@pytest.mark.parametrize("status", ["completed", "failed", "stopped", "partial"])
def test_stopping_a_finished_run_is_a_conflict(
    client: TestClient, engine: Engine, status: str
) -> None:
    user, token = member_session(engine)
    run_id = create_run(engine, user.organisation_id, status=status)

    assert call(client, "POST", f"/runs/{run_id}/stop", token).status_code == 409


# --- Pause and resume ------------------------------------------------------------------------


def provider_error() -> Exception:
    return ProviderCallError(provider="google", config_id="primary", kind="unavailable")


@pytest.mark.parametrize(
    ("error", "dependency", "words"),
    [
        (DependencyUnavailable("structuring_provider"), "structuring_provider", "structuring"),
        (provider_error(), "llm_provider", "AI provider"),
        (OperationalError("SELECT 1", None, Exception("secret")), "database", "database"),
        (ConnectionError("down"), "network", "network"),
        (RedactionUnavailable(), "llm_provider", "nothing was sent"),
    ],
)
def test_a_failing_dependency_pauses_the_run_and_names_it(
    client: TestClient,
    engine: Engine,
    settings: Settings,
    caplog: pytest.LogCaptureFixture,
    error: Exception,
    dependency: str,
    words: str,
) -> None:
    user, token = member_session(engine)
    run_id = create_run(engine, user.organisation_id)

    with caplog.at_level("WARNING"):
        work(engine, settings, Counter("collection", error).stages())

    body = call(client, "GET", f"/runs/{run_id}", token).json()
    assert body["status"] == "paused"
    assert body["stage"] == "collection"
    assert body["pause_dependency"] == dependency
    assert words in body["pause_reason"]
    assert body["counts_against_quota"] is False
    assert f"paused in stage collection: {dependency}" in caplog.text
    assert "secret" not in caplog.text


def test_resume_continues_from_the_paused_stage_without_repeating_results(
    client: TestClient, engine: Engine, settings: Settings
) -> None:
    user, token = member_session(engine)
    run_id = create_run(engine, user.organisation_id)
    broken = Counter("extraction", provider_error())
    work(engine, settings, broken.stages())
    assert get_run(engine, run_id).status == "paused"

    response = call(client, "POST", f"/runs/{run_id}/resume", token)
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert response.json()["pause_reason"] is None
    assert response.json()["counts_against_quota"] is True
    fixed = Counter()
    work(engine, settings, fixed.stages())

    assert broken.calls == ["identity", "collection", "extraction"]
    assert fixed.calls == ["extraction", "assessment"]  # identity and collection are not redone
    assert get_run(engine, run_id).status == "completed"
    assert [job.state for job in jobs_of(engine)] == ["done", "done"]


def test_resume_of_a_run_that_is_not_paused_is_a_conflict(
    client: TestClient, engine: Engine
) -> None:
    user, token = member_session(engine)
    run_id = create_run(engine, user.organisation_id, status="running", enqueue=False)

    assert call(client, "POST", f"/runs/{run_id}/resume", token).status_code == 409
    assert jobs_of(engine) == []


def test_a_paused_run_can_be_stopped(client: TestClient, engine: Engine) -> None:
    user, token = member_session(engine)
    run_id = create_run(engine, user.organisation_id, status="paused", enqueue=False)

    assert call(client, "POST", f"/runs/{run_id}/stop", token).json()["status"] == "stopped"


def test_an_unexpected_error_fails_the_run_without_crashing_the_worker(
    engine: Engine, settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    run_id = create_run(engine, create_organisation(engine))

    with caplog.at_level("ERROR"):
        work(engine, settings, Counter("identity", ValueError("bug")).stages())

    run = get_run(engine, run_id)
    assert (run.status, run.error) == ("failed", "The run failed unexpectedly.")
    assert run.counts_against_quota is True
    assert "failed in stage identity" in caplog.text


def test_a_missing_crawler_contact_fails_the_run_with_a_plain_message(
    engine: Engine, settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    run_id = create_run(engine, create_organisation(engine), stage="collection")
    error = ConfigurationError("CRAWLER_CONTACT_URL must be set before supplier sites are fetched")

    with caplog.at_level("ERROR"):
        work(engine, settings, Counter("collection", error).stages())

    run = get_run(engine, run_id)
    assert run.status == "failed"
    assert run.error == (
        "Collection is not available because the service is not fully configured. "
        "Please contact the administrator."
    )
    assert "CRAWLER_CONTACT_URL" not in run.error
    assert "not configured" in caplog.text


def test_the_worker_refuses_to_start_without_the_crawler_contact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import worker

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@127.0.0.1:1/db")
    monkeypatch.delenv("CRAWLER_CONTACT_URL", raising=False)

    with pytest.raises(SystemExit) as stopped:
        worker.main()

    assert str(stopped.value).startswith("CRAWLER_CONTACT_URL is not set")


def test_insufficient_sources_does_not_count_against_the_quota(
    engine: Engine, settings: Settings
) -> None:
    run_id = create_run(engine, create_organisation(engine))
    stages = Counter().stages()
    stages["collection"] = lambda context: "insufficient_sources"

    work(engine, settings, stages)

    run = get_run(engine, run_id)
    assert (run.status, run.stage, run.counts_against_quota) == (
        "insufficient_sources",
        "collection",
        False,
    )


def _organisation_with(engine: Engine, **fields: Any) -> tuple[Any, str]:
    from app.models import Organisation

    user = create_user(engine, organisation_id=create_organisation(engine))
    with Session(engine) as db:
        organisation = db.get(Organisation, user.organisation_id)
        assert organisation is not None
        for name, value in fields.items():
            setattr(organisation, name, value)
        db.commit()
    return user, create_session(engine, user.id)


def _own_organisation(client: TestClient, token: str) -> dict[str, Any]:
    response = send_with_session(client, "GET", "/organisation", token)
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


def test_organisation_says_no_refusal_and_unlimited_when_nothing_limits(
    client: TestClient, engine: Engine
) -> None:
    _, token = _organisation_with(engine)
    body = _own_organisation(client, token)
    assert (body["profiles_remaining"], body["run_refusal_reason"]) == (None, None)


def test_organisation_counts_the_remaining_quota_and_refuses_when_used(
    client: TestClient, engine: Engine
) -> None:
    user, token = _organisation_with(engine, profile_quota=2)
    create_run(engine, user.organisation_id, enqueue=False)
    body = _own_organisation(client, token)
    assert (body["profiles_remaining"], body["run_refusal_reason"]) == (1, None)
    create_run(engine, user.organisation_id, enqueue=False)
    body = _own_organisation(client, token)
    assert (body["profiles_remaining"], body["run_refusal_reason"]) == (0, "quota_reached")


def test_a_run_that_does_not_count_leaves_the_quota_free(
    client: TestClient, engine: Engine
) -> None:
    user, token = _organisation_with(engine, profile_quota=1)
    run_id = create_run(engine, user.organisation_id, status="insufficient_sources", enqueue=False)
    with Session(engine) as db:
        run = db.get(ProfileRun, run_id)
        assert run is not None
        run.counts_against_quota = False
        db.commit()
    body = _own_organisation(client, token)
    assert (body["profiles_remaining"], body["run_refusal_reason"]) == (1, None)


def test_organisation_refuses_when_not_activated_or_access_ended(
    client: TestClient, engine: Engine
) -> None:
    _, pending = _organisation_with(engine, status="pending_activation")
    assert _own_organisation(client, pending)["run_refusal_reason"] == "not_activated"
    _, ended = _organisation_with(engine, access_ends_at=utc_now() - timedelta(days=1))
    assert _own_organisation(client, ended)["run_refusal_reason"] == "access_ended"


def test_organisation_refuses_when_the_monthly_spend_cap_is_reached(
    engine: Engine, settings: Settings
) -> None:
    user, token = _organisation_with(engine)
    run_id = create_run(engine, user.organisation_id, enqueue=False)
    add_usage(engine, user.organisation_id, run_id, cost="0.5")  # two rows: 1.0 in total
    below = make_client(
        settings=replace(settings, monthly_spend_cap_eur=Decimal("1.5")), engine=engine
    )
    assert _own_organisation(below, token)["run_refusal_reason"] is None
    reached = make_client(
        settings=replace(settings, monthly_spend_cap_eur=Decimal("1")), engine=engine
    )
    body = _own_organisation(reached, token)
    assert body["run_refusal_reason"] == "spend_cap_reached"
    assert "spend" not in " ".join(body).replace("run_refusal_reason", "")

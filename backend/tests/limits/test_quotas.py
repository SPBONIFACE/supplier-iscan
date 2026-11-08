"""Quotas, access period and monthly spend cap, enforced when work starts (#29).

The numbers below are test values: the real ones are configuration and are the owner's.
"""

import threading
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from app.assessment.drafting import ASSESSMENT_JOB
from app.config import ConfigurationError, Settings
from app.db import utc_now
from app.models import Organisation, ProfileRun, UsageEvent
from app.runs.refusal import REFUSAL_MESSAGES, monthly_spend_eur
from app.runs.stages import DependencyUnavailable
from tests.assessment.test_drafting import Drafted
from tests.auth_support import send_with_session
from tests.contract.test_auth_contract import assert_matches_contract
from tests.factories import create_organisation, create_session, create_user
from tests.runs_support import add_usage, create_identity, create_run, get_run, jobs_of, work
from tests.support import make_client
from tests.test_runs import Counter as StageCounter

CONCURRENT = 6
QUOTA = 3
REASONS = ("not_activated", "access_ended", "quota_reached", "spend_cap_reached")


def member(engine: Engine, **organisation: Any) -> tuple[Any, str]:
    """A member of a new organisation with the given limits set on it."""
    user = create_user(engine, organisation_id=create_organisation(engine))
    with Session(engine) as db:
        row = db.get_one(Organisation, user.organisation_id)
        for name, value in organisation.items():
            setattr(row, name, value)
        db.commit()
    return user, create_session(engine, user.id)


def start(client: TestClient, engine: Engine, user: Any, token: str) -> httpx2.Response:
    identity_id = create_identity(engine, user.organisation_id)
    return send_with_session(client, "POST", "/runs", token, json={"identity_id": str(identity_id)})


def capped(settings: Settings, cap: str, engine: Engine) -> TestClient:
    return make_client(
        settings=replace(settings, monthly_spend_cap_eur=Decimal(cap)), engine=engine
    )


def spend(engine: Engine, cost: str = "0.5") -> None:
    """Two usage rows of `cost` each, this month, on a run of another organisation."""
    other = create_organisation(engine, name="Another buyer")
    add_usage(engine, other, create_run(engine, other, enqueue=False), cost=cost)


def spent(engine: Engine) -> Decimal:
    with Session(engine) as db:
        return monthly_spend_eur(db, utc_now())


def run_count(engine: Engine, organisation_id: Any) -> int:
    with Session(engine) as db:
        return (
            db.scalar(
                select(func.count())
                .select_from(ProfileRun)
                .where(ProfileRun.organisation_id == organisation_id)
            )
            or 0
        )


def assert_nothing_started(engine: Engine, organisation_id: Any, before: int = 0) -> None:
    assert run_count(engine, organisation_id) == before
    assert jobs_of(engine) == []
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(UsageEvent)) == 0


# --- POST /runs is refused, with the reason ---------------------------------------------------


def test_a_run_is_refused_when_the_organisation_is_not_activated(
    client: TestClient, engine: Engine
) -> None:
    user, token = member(engine, status="pending_activation")

    response = start(client, engine, user, token)

    assert response.status_code == 403
    assert response.json() == {
        "detail": REFUSAL_MESSAGES["not_activated"],
        "reason": "not_activated",
    }
    assert_matches_contract(response, "/runs", "post")
    assert_nothing_started(engine, user.organisation_id)


def test_a_run_is_refused_once_access_has_ended(client: TestClient, engine: Engine) -> None:
    user, token = member(engine, access_ends_at=utc_now() - timedelta(seconds=1))

    response = start(client, engine, user, token)

    assert (response.status_code, response.json()["reason"]) == (403, "access_ended")
    assert_matches_contract(response, "/runs", "post")
    assert_nothing_started(engine, user.organisation_id)


def test_a_run_is_accepted_until_access_ends(client: TestClient, engine: Engine) -> None:
    user, token = member(engine, access_ends_at=utc_now() + timedelta(hours=1))

    assert start(client, engine, user, token).status_code == 202


def test_a_run_is_refused_once_the_quota_is_used(client: TestClient, engine: Engine) -> None:
    user, token = member(engine, profile_quota=QUOTA)
    for _ in range(QUOTA):
        assert start(client, engine, user, token).status_code == 202
    before = run_count(engine, user.organisation_id)

    response = start(client, engine, user, token)

    assert (response.status_code, response.json()["reason"]) == (403, "quota_reached")
    assert response.json()["detail"] == REFUSAL_MESSAGES["quota_reached"]
    assert_matches_contract(response, "/runs", "post")
    assert run_count(engine, user.organisation_id) == before == QUOTA
    assert len(jobs_of(engine)) == QUOTA


def test_a_run_is_refused_once_the_monthly_spend_cap_is_reached(
    engine: Engine, settings: Settings
) -> None:
    user, token = member(engine)
    spend(engine)  # 1.0 in total, by another organisation: the cap is the instance's

    below = start(capped(settings, "1.5", engine), engine, user, token)
    reached = start(capped(settings, "1", engine), engine, user, token)

    assert below.status_code == 202
    assert (reached.status_code, reached.json()["reason"]) == (403, "spend_cap_reached")
    assert_matches_contract(reached, "/runs", "post")
    assert run_count(engine, user.organisation_id) == 1  # only the first


def test_spend_of_an_earlier_month_does_not_count(engine: Engine, settings: Settings) -> None:
    user, token = member(engine)
    spend(engine)
    from app.models import LlmUsage

    with Session(engine) as db:
        start_of_month = utc_now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        for row in db.scalars(select(LlmUsage)):
            row.created_at = start_of_month - timedelta(seconds=1)
        db.commit()

    assert start(capped(settings, "1", engine), engine, user, token).status_code == 202


def test_the_reasons_are_checked_in_the_documented_order(
    engine: Engine, settings: Settings
) -> None:
    spend(engine)
    user, token = member(
        engine,
        status="pending_activation",
        access_ends_at=utc_now() - timedelta(days=1),
        profile_quota=1,
    )
    create_run(engine, user.organisation_id, enqueue=False)  # the one slot is taken
    client = capped(settings, "1", engine)
    seen = []
    for change in (
        {},
        {"status": "active"},
        {"access_ends_at": None},
        {"profile_quota": None},
    ):
        with Session(engine) as db:
            row = db.get_one(Organisation, user.organisation_id)
            for name, value in change.items():
                setattr(row, name, value)
            db.commit()
        seen.append(start(client, engine, user, token).json()["reason"])
    assert tuple(seen) == REASONS


def test_nothing_set_means_no_limit(client: TestClient, engine: Engine) -> None:
    user, token = member(engine)  # no quota, no access end; the default settings set no cap

    assert [start(client, engine, user, token).status_code for _ in range(5)] == [202] * 5


def test_the_messages_are_plain_and_state_nothing_about_a_supplier() -> None:
    assert set(REFUSAL_MESSAGES) == set(REASONS)
    for message in REFUSAL_MESSAGES.values():
        assert "remain readable" in message
        assert not any(word in message.lower() for word in ("fraud", "risky", "unreliable"))


# --- the last slot, and simultaneous starts ---------------------------------------------------


def _start_together(
    engine: Engine, settings: Settings, user: Any, token: str, count: int
) -> list[httpx2.Response]:
    """One start per thread and client, all released at the same moment (on one warmed-up app)."""
    first = make_client(settings=settings, engine=engine)
    identities = [create_identity(engine, user.organisation_id) for _ in range(count)]
    assert send_with_session(first, "GET", "/runs", token).status_code == 200
    clients = [
        TestClient(first.app, base_url=str(first.base_url), raise_server_exceptions=False)
        for _ in identities
    ]
    barrier = threading.Barrier(count)

    def go(index: int) -> httpx2.Response:
        barrier.wait()
        return send_with_session(
            clients[index], "POST", "/runs", token, json={"identity_id": str(identities[index])}
        )

    with ThreadPoolExecutor(max_workers=count) as pool:
        return list(pool.map(go, range(count)))


def test_simultaneous_starts_for_the_last_slot_let_exactly_one_in(
    engine: Engine, settings: Settings
) -> None:
    user, token = member(engine, profile_quota=1)

    responses = _start_together(engine, settings, user, token, CONCURRENT)

    assert Counter(r.status_code for r in responses) == {202: 1, 403: CONCURRENT - 1}
    assert all(r.json()["reason"] == "quota_reached" for r in responses if r.status_code == 403)
    assert run_count(engine, user.organisation_id) == 1
    assert len(jobs_of(engine)) == 1


def test_simultaneous_starts_never_pass_the_quota(engine: Engine, settings: Settings) -> None:
    user, token = member(engine, profile_quota=QUOTA)

    responses = _start_together(engine, settings, user, token, CONCURRENT)

    assert Counter(r.status_code for r in responses) == {202: QUOTA, 403: CONCURRENT - QUOTA}
    assert run_count(engine, user.organisation_id) == QUOTA


def test_a_start_waits_for_the_organisation_lock_and_then_counts_again(
    client: TestClient, engine: Engine
) -> None:
    # Deterministic version of the race: another transaction holds the organisation row (as a
    # concurrent start does) and takes the last slot while this start waits.
    user, token = member(engine, profile_quota=1)
    identity_id = create_identity(engine, user.organisation_id)
    other_identity = create_identity(engine, user.organisation_id)

    with engine.connect() as other:
        other.execute(
            text("SELECT id FROM organisations WHERE id = :id FOR UPDATE"),
            {"id": user.organisation_id},
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(
                send_with_session,
                client,
                "POST",
                "/runs",
                token,
                json={"identity_id": str(identity_id)},
            )
            time.sleep(1.0)
            assert not pending.done(), "the start did not wait for the organisation lock"
            with Session(bind=other) as taker:
                taker.add(
                    ProfileRun(organisation_id=user.organisation_id, identity_id=other_identity)
                )
                taker.flush()
            other.commit()
            response = pending.result(timeout=15)

    assert (response.status_code, response.json()["reason"]) == (403, "quota_reached")
    assert run_count(engine, user.organisation_id) == 1


# --- what counts against the quota ------------------------------------------------------------


def remaining(client: TestClient, token: str) -> int | None:
    value: int | None = send_with_session(client, "GET", "/organisation", token).json()[
        "profiles_remaining"
    ]
    return value


def test_runs_that_end_completed_partial_or_stopped_count(
    client: TestClient, engine: Engine, settings: Settings
) -> None:
    user, token = member(engine, profile_quota=10)
    completed = start(client, engine, user, token).json()["id"]
    stopped = start(client, engine, user, token).json()["id"]
    stopped_while_queued = start(client, engine, user, token).json()["id"]
    assert (
        send_with_session(client, "POST", f"/runs/{stopped_while_queued}/stop", token).status_code
        == 200
    )
    assert remaining(client, token) == 7

    work(engine, settings, StageCounter().stages())  # the first job: completed
    assert get_run(engine, completed).status == "completed"
    with Session(engine) as db:
        db.get_one(ProfileRun, stopped).status = "stopped"
        db.commit()
    partial = create_run(engine, user.organisation_id, status="partial", enqueue=False)

    assert get_run(engine, partial).counts_against_quota is True
    assert remaining(client, token) == 6
    assert all(
        get_run(engine, run_id).counts_against_quota
        for run_id in (completed, stopped, stopped_while_queued)
    )


def test_insufficient_sources_releases_the_slot(
    client: TestClient, engine: Engine, settings: Settings
) -> None:
    user, token = member(engine, profile_quota=1)
    run_id = start(client, engine, user, token).json()["id"]
    assert start(client, engine, user, token).status_code == 403  # the slot is reserved
    stages = StageCounter().stages()
    stages["collection"] = lambda context: "insufficient_sources"

    work(engine, settings, stages)

    assert get_run(engine, run_id).counts_against_quota is False
    assert remaining(client, token) == 1
    assert start(client, engine, user, token).status_code == 202


def test_a_run_that_fails_because_the_service_is_not_configured_releases_the_slot(
    client: TestClient, engine: Engine, settings: Settings
) -> None:
    # #103: nothing the member did, and no request was sent.
    user, token = member(engine, profile_quota=1)
    run_id = start(client, engine, user, token).json()["id"]
    error = ConfigurationError("CRAWLER_CONTACT_URL must be set before supplier sites are fetched")

    work(engine, settings, StageCounter("collection", error).stages())

    run = get_run(engine, run_id)
    assert (run.status, run.counts_against_quota) == ("failed", False)
    assert remaining(client, token) == 1
    assert start(client, engine, user, token).status_code == 202


def test_a_run_that_fails_on_a_dependency_does_not_count(
    client: TestClient, engine: Engine, settings: Settings
) -> None:
    user, token = member(engine, profile_quota=1)
    run_id = start(client, engine, user, token).json()["id"]
    error = DependencyUnavailable("structuring_provider")

    work(engine, settings, StageCounter("collection", error).stages())

    run = get_run(engine, run_id)
    assert (run.status, run.counts_against_quota) == ("paused", False)
    assert remaining(client, token) == 1


# --- a limit reached while a run is in progress, and reading afterwards -----------------------


def test_a_limit_reached_while_a_run_is_in_progress_lets_it_finish(
    engine: Engine, settings: Settings
) -> None:
    user, token = member(engine, profile_quota=1)
    client = capped(settings, "1", engine)
    run_id = start(client, engine, user, token).json()["id"]
    # Everything is reached while the run is queued: quota used, access ended, cap passed.
    spend(engine, "1")
    with Session(engine) as db:
        db.get_one(Organisation, user.organisation_id).access_ends_at = utc_now() - timedelta(
            seconds=1
        )
        db.commit()

    assert start(client, engine, user, token).status_code == 403  # the next run is refused
    work(engine, settings, StageCounter().stages())  # the job in progress still finishes

    assert get_run(engine, run_id).status == "completed"


def test_existing_profiles_stay_readable_after_every_limit(
    engine: Engine, settings: Settings
) -> None:
    drafted = Drafted(make_client(settings=settings, engine=engine), engine)
    spend(engine, "1")
    with Session(engine) as db:
        organisation = db.get_one(Organisation, drafted.organisation_id)
        organisation.profile_quota = 1
        organisation.access_ends_at = utc_now() - timedelta(days=1)
        db.commit()
    client = capped(settings, str(spent(engine)), engine)
    drafted.client = client

    paths = ["", "/facts", "/assessment", "/sources", "/failures"]
    for tail in paths:
        response = send_with_session(client, "GET", f"/runs/{drafted.run_id}{tail}", drafted.token)
        assert response.status_code == 200, (tail, response.status_code)
    assert send_with_session(client, "GET", "/runs", drafted.token).status_code == 200
    organisation_body = send_with_session(client, "GET", "/organisation", drafted.token).json()
    assert organisation_body["run_refusal_reason"] == "access_ended"


# --- the spend cap on fit and recommendations (#37) -------------------------------------------


@pytest.mark.parametrize("tail", ["fit", "recommendations"])
def test_drafting_is_refused_on_the_spend_cap_and_queues_nothing(
    engine: Engine, settings: Settings, tail: str
) -> None:
    drafted = Drafted(make_client(settings=settings, engine=engine), engine)
    drafted.criteria("Certified quality management")
    spend(engine, "1")
    before = len([job for job in jobs_of(engine) if job.kind == ASSESSMENT_JOB])
    drafted.client = capped(settings, str(spent(engine)), engine)

    response = drafted.call("POST", tail)

    assert (response.status_code, response.json()["reason"]) == (403, "spend_cap_reached")
    assert response.json()["detail"] == REFUSAL_MESSAGES["spend_cap_reached"]
    assert_matches_contract(response, f"/runs/{{id}}/{tail}", "post")
    assert len([job for job in jobs_of(engine) if job.kind == ASSESSMENT_JOB]) == before
    assert drafted.call("GET", "assessment").status_code == 200  # reading is not affected


@pytest.mark.parametrize("tail", ["fit", "recommendations"])
def test_drafting_is_accepted_below_the_cap_and_without_one(
    engine: Engine, settings: Settings, tail: str
) -> None:
    drafted = Drafted(make_client(settings=settings, engine=engine), engine)
    drafted.criteria("Certified quality management")
    spend(engine, "1")

    drafted.client = capped(settings, str(spent(engine) + 1), engine)
    assert drafted.call("POST", tail).status_code == 202
    drafted.client = make_client(settings=settings, engine=engine)  # no cap
    assert drafted.call("POST", tail).status_code == 202


def test_drafting_is_not_blocked_by_the_quota_or_the_access_period(
    engine: Engine, settings: Settings
) -> None:
    # Only the cost of AI work stops drafting on an existing profile (contract, #29).
    drafted = Drafted(make_client(settings=settings, engine=engine), engine)
    with Session(engine) as db:
        organisation = db.get_one(Organisation, drafted.organisation_id)
        organisation.profile_quota = 1
        organisation.access_ends_at = utc_now() - timedelta(days=1)
        db.commit()

    assert drafted.call("POST", "recommendations").status_code == 202


# --- resume (#29, QA) -------------------------------------------------------------------------


def paused_run(engine: Engine, user: Any) -> str:
    return str(create_run(engine, user.organisation_id, status="paused", enqueue=False))


def resume(client: TestClient, token: str, run_id: str) -> httpx2.Response:
    return send_with_session(client, "POST", f"/runs/{run_id}/resume", token)


def test_resume_is_refused_once_access_has_ended(client: TestClient, engine: Engine) -> None:
    user, token = member(engine, access_ends_at=utc_now() - timedelta(seconds=1))
    run_id = paused_run(engine, user)

    response = resume(client, token, run_id)

    assert (response.status_code, response.json()["reason"]) == (403, "access_ended")
    assert response.json()["detail"] == REFUSAL_MESSAGES["access_ended"]
    assert_matches_contract(response, "/runs/{id}/resume", "post")
    assert get_run(engine, uuid.UUID(run_id)).status == "paused"
    assert jobs_of(engine) == []


def test_resume_is_refused_when_not_activated(client: TestClient, engine: Engine) -> None:
    user, token = member(engine, status="pending_activation")

    response = resume(client, token, paused_run(engine, user))

    assert (response.status_code, response.json()["reason"]) == (403, "not_activated")


def test_resume_is_refused_on_the_spend_cap_and_allowed_below_it(
    engine: Engine, settings: Settings
) -> None:
    user, token = member(engine)
    run_id = paused_run(engine, user)
    spend(engine)  # 1.0

    refused = resume(capped(settings, "1", engine), token, run_id)
    allowed = resume(capped(settings, "1.5", engine), token, run_id)

    assert (refused.status_code, refused.json()["reason"]) == (403, "spend_cap_reached")
    assert allowed.status_code == 202 and allowed.json()["status"] == "queued"
    assert len(jobs_of(engine)) == 1


def test_resume_does_not_take_the_quota_again(client: TestClient, engine: Engine) -> None:
    user, token = member(engine, profile_quota=1)
    run_id = paused_run(engine, user)  # a paused run does not count: the slot looks free

    response = resume(client, token, run_id)

    assert response.status_code == 202  # the run continues; the quota is not checked
    assert get_run(engine, uuid.UUID(run_id)).status == "queued"


def test_simultaneous_resumes_of_one_run_queue_it_once(engine: Engine, settings: Settings) -> None:
    user, token = member(engine)
    run_id = paused_run(engine, user)
    first = make_client(settings=settings, engine=engine)
    assert send_with_session(first, "GET", "/runs", token).status_code == 200
    clients = [
        TestClient(first.app, base_url=str(first.base_url), raise_server_exceptions=False)
        for _ in range(CONCURRENT)
    ]
    barrier = threading.Barrier(CONCURRENT)

    def go(index: int) -> httpx2.Response:
        barrier.wait()
        return resume(clients[index], token, run_id)

    with ThreadPoolExecutor(max_workers=CONCURRENT) as pool:
        responses = list(pool.map(go, range(CONCURRENT)))

    assert Counter(r.status_code for r in responses) == {202: 1, 409: CONCURRENT - 1}
    assert len(jobs_of(engine)) == 1


def test_simultaneous_resumes_all_refused_when_the_cap_is_reached(
    engine: Engine, settings: Settings
) -> None:
    user, token = member(engine)
    run_ids = [paused_run(engine, user) for _ in range(CONCURRENT)]
    spend(engine)
    first = capped(settings, "1", engine)
    assert send_with_session(first, "GET", "/runs", token).status_code == 200
    clients = [
        TestClient(first.app, base_url=str(first.base_url), raise_server_exceptions=False)
        for _ in run_ids
    ]
    barrier = threading.Barrier(CONCURRENT)

    def go(index: int) -> httpx2.Response:
        barrier.wait()
        return resume(clients[index], token, run_ids[index])

    with ThreadPoolExecutor(max_workers=CONCURRENT) as pool:
        responses = list(pool.map(go, range(CONCURRENT)))

    assert {r.status_code for r in responses} == {403}
    assert jobs_of(engine) == []

"""The on-demand worker (#200): drain mode, and the API starting the job after it queues work."""

import threading
from dataclasses import replace

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError

from app import worker
from app.config import ConfigurationError, Settings, load_settings
from app.http_client import start_worker_job
from app.runs import wake
from tests.assessment.test_drafting import Drafted
from tests.auth_support import send_with_session
from tests.factories import create_organisation, create_session, create_user
from tests.runs_support import create_identity, create_run, get_run, jobs_of, work
from tests.support import make_client

JOB = "projects/p-1/locations/europe-west1/jobs/iscan-worker-dev"
TOKEN = "ya29.secret-token-value"


# --- drain mode --------------------------------------------------------------------------------


class Queue:
    """`work` for the loop: True while jobs are left, then False; records the waits."""

    def __init__(self, jobs: int, stopping: threading.Event) -> None:
        self.jobs, self.processed, self.polls = jobs, 0, 0
        self.stopping = stopping
        self.waits: list[float] = []
        real_wait = stopping.wait

        def wait(timeout: float | None = None) -> bool:
            self.waits.append(timeout or 0)
            if len(self.waits) > 10:  # a loop that never ends fails the test instead of hanging
                stopping.set()
            return real_wait(0)

        stopping.wait = wait  # type: ignore[method-assign]

    def work(self) -> bool:
        self.polls += 1
        if self.processed < self.jobs:
            self.processed += 1
            return True
        return False


def test_drain_mode_processes_queued_jobs_then_exits_after_one_empty_interval() -> None:
    stopping = threading.Event()
    queue = Queue(3, stopping)

    worker.drain(queue.work, stopping, 7, until_empty=True)

    assert queue.processed == 3
    assert queue.polls == 5  # three jobs, an empty poll, one interval, a second empty poll
    assert queue.waits == [7]
    assert not stopping.is_set()


def test_drain_mode_on_an_empty_queue_exits_after_one_interval() -> None:
    stopping = threading.Event()
    queue = Queue(0, stopping)

    worker.drain(queue.work, stopping, 2, until_empty=True)

    assert (queue.polls, queue.waits) == (2, [2])


def test_a_job_queued_during_the_interval_is_processed_before_exiting() -> None:
    stopping = threading.Event()
    answers = iter([False, True, False, False])
    polls: list[int] = []

    def work() -> bool:
        polls.append(1)
        return next(answers)

    stopping.wait = lambda timeout=None: False  # type: ignore[method-assign]
    worker.drain(work, stopping, 2, until_empty=True)

    assert len(polls) == 4


def test_drain_mode_does_not_stay_alive_on_an_unreachable_database() -> None:
    stopping = threading.Event()
    polls: list[int] = []

    def work() -> bool:
        polls.append(1)
        raise OperationalError("SELECT", {}, Exception("down"))

    stopping.wait = lambda timeout=None: False  # type: ignore[method-assign]
    worker.drain(work, stopping, 2, until_empty=True)

    assert len(polls) == 2


def test_without_the_flag_the_worker_keeps_polling_until_stopped() -> None:
    stopping = threading.Event()
    queue = Queue(1, stopping)

    worker.drain(queue.work, stopping, 2, until_empty=False)

    assert stopping.is_set()  # ended only by the guard in Queue, after more than ten waits
    assert queue.processed == 1 and len(queue.waits) == 11


def test_the_flag_is_accepted_and_others_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@127.0.0.1:1/db")
    monkeypatch.delenv("CRAWLER_CONTACT_URL", raising=False)

    with pytest.raises(SystemExit) as accepted:
        worker.main(["--until-empty"])
    with pytest.raises(SystemExit) as refused:
        worker.main(["--unknown"])

    assert str(accepted.value).startswith("CRAWLER_CONTACT_URL is not set")
    assert refused.value.code == 2


def test_drain_mode_processes_the_queue_of_the_database_then_exits(
    engine: Engine, settings: Settings
) -> None:
    organisation_id = create_organisation(engine)
    first, second = create_run(engine, organisation_id), create_run(engine, organisation_id)
    stages = {name: (lambda context: None) for name in ("identity", "collection", "extraction")}
    stages["assessment"] = lambda context: None
    stopping = threading.Event()
    stopping.wait = lambda timeout=None: False  # type: ignore[method-assign]

    worker.drain(lambda: work(engine, settings, stages), stopping, 1, until_empty=True)

    assert [job.state for job in jobs_of(engine)] == ["done", "done"]
    assert {get_run(engine, run_id).status for run_id in (first, second)} == {"completed"}


# --- the setting -------------------------------------------------------------------------------


def test_the_job_name_setting_is_optional_and_checked() -> None:
    assert load_settings({}).worker_job_name is None
    assert load_settings({"WORKER_JOB_NAME": f" {JOB} "}).worker_job_name == JOB
    with pytest.raises(ConfigurationError, match="WORKER_JOB_NAME") as error:
        load_settings({"WORKER_JOB_NAME": "iscan-worker-dev"})
    assert "iscan-worker-dev" not in str(error.value)


# --- started on demand -------------------------------------------------------------------------


class CloudRun:
    def __init__(self, run_status: int = 200) -> None:
        self.runs: list[str] = []
        self.run_status = run_status

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "metadata.google.internal":
            return httpx2.Response(200, json={"access_token": TOKEN})
        self.runs.append(str(request.url))
        return httpx2.Response(self.run_status, json={})


@pytest.fixture
def cloud(monkeypatch: pytest.MonkeyPatch) -> CloudRun:
    """The real start function on a mocked transport: no call reaches Google Cloud."""
    cloud = CloudRun()
    transport = httpx2.MockTransport(cloud.handle)
    monkeypatch.setattr(
        wake, "start_worker_job", lambda name: start_worker_job(name, transport=transport)
    )
    return cloud


def client_with_job(engine: Engine, settings: Settings) -> TestClient:
    return make_client(settings=replace(settings, worker_job_name=JOB), engine=engine)


def start(client: TestClient, engine: Engine) -> httpx2.Response:
    user = create_user(engine)
    token = create_session(engine, user.id)
    identity_id = create_identity(engine, user.organisation_id)
    response: httpx2.Response = send_with_session(
        client, "POST", "/runs", token, json={"identity_id": str(identity_id)}
    )
    return response


def test_queuing_a_run_starts_the_job_once(
    cloud: CloudRun, engine: Engine, settings: Settings
) -> None:
    response = start(client_with_job(engine, settings), engine)

    assert response.status_code == 202
    assert cloud.runs == [f"https://run.googleapis.com/v2/{JOB}:run"]
    assert len(jobs_of(engine)) == 1


def test_without_the_setting_nothing_is_started(
    cloud: CloudRun, client: TestClient, engine: Engine
) -> None:
    assert start(client, engine).status_code == 202
    assert cloud.runs == []


def test_a_failed_start_does_not_fail_the_request_and_logs_no_token(
    cloud: CloudRun, engine: Engine, settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    cloud.run_status = 403

    with caplog.at_level("INFO"):
        response = start(client_with_job(engine, settings), engine)

    assert response.status_code == 202
    assert [job.state for job in jobs_of(engine)] == ["queued"]
    assert "Worker job not started: HTTP 403" in caplog.text
    assert TOKEN not in caplog.text


def test_resuming_a_run_starts_the_job_once(
    cloud: CloudRun, engine: Engine, settings: Settings
) -> None:
    user = create_user(engine)
    token = create_session(engine, user.id)
    run_id = create_run(engine, user.organisation_id, status="paused", enqueue=False)

    response = send_with_session(
        client_with_job(engine, settings), "POST", f"/runs/{run_id}/resume", token
    )

    assert response.status_code == 202
    assert len(cloud.runs) == 1


def test_queuing_a_drafting_job_starts_the_job_once(
    cloud: CloudRun, engine: Engine, settings: Settings
) -> None:
    drafted = Drafted(client_with_job(engine, settings), engine)
    drafted.criteria("Certified to ISO 9001")

    assert drafted.call("POST", "fit").status_code == 202
    assert drafted.call("POST", "fit").status_code == 202  # already waiting: nothing queued

    assert len(cloud.runs) == 1


def test_a_refused_request_starts_nothing(
    cloud: CloudRun, engine: Engine, settings: Settings
) -> None:
    drafted = Drafted(client_with_job(engine, settings), engine)

    assert drafted.call("POST", "fit").status_code == 409  # no criteria

    assert cloud.runs == []

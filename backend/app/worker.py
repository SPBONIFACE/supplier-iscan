"""The worker process (spec, Architecture constraints): `python -m app.worker`.

It claims jobs from the PostgreSQL queue (`app.queue`) one at a time and executes them. Run as
many worker processes as needed: a job is never claimed twice, and a job whose worker died is
claimed again after the lease timeout (`RUN_LEASE_SECONDS`).
"""

import logging
import os
import signal
import threading
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app import queue
from app.assessment.drafting import ASSESSMENT_JOB, run_draft_job
from app.config import CRAWLER_CONTACT_URL, ConfigurationError, Settings, load_settings
from app.db import Database, utc_now
from app.providers import Providers
from app.runs.executor import (
    INTERRUPTED,
    RUN_JOB,
    RunEnvironment,
    count_finished,
    execute_run,
    fail_run,
)
from app.runs.stages import DEFAULT_STAGES, LeaseLost, Stage
from app.telemetry import TRACEPARENT, context_from_traceparent, span
from app.telemetry.setup import configure

logger = logging.getLogger(__name__)

# A job claimed more often than this keeps killing its worker: its run is ended, not retried.
MAX_ATTEMPTS = 3

# Runs one drafting job (fit or recommendations, #26): database, providers, run id, part, beat.
Drafter = Callable[[Database, Providers | None, uuid.UUID, str, Callable[[], None]], None]


def default_drafter(
    database: Database,
    providers: Providers | None,
    run_id: uuid.UUID,
    part: str,
    beat: Callable[[], None],
) -> None:
    """The drafting job with the profile definition and the prompt set of the settings."""
    from app.main import load_definition, load_prompts

    settings = load_settings()
    run_draft_job(
        database, providers, load_definition(settings), load_prompts(settings), run_id, part, beat
    )


def work_once(
    database: Database,
    settings: Settings,
    worker_id: str,
    stages: Mapping[str, Stage] = DEFAULT_STAGES,
    providers: Providers | None = None,
    now: Callable[[], datetime] = utc_now,
    drafter: Drafter = default_drafter,
) -> bool:
    """Claim and execute one job. False when there was none."""
    with database.session() as db:
        job = queue.claim(db, worker_id, settings.run_lease, now(), (RUN_JOB, ASSESSMENT_JOB))
    if job is None:
        return False
    run_id = uuid.UUID(job.payload["run_id"])
    # The job carries the trace of the request that queued it: the worker continues it.
    with span(
        "job.process",
        {
            "iscan.job_kind": job.kind,
            "iscan.job_attempt": job.attempts,
            "iscan.run_id": str(run_id),
        },
        parent=context_from_traceparent(job.payload.get(TRACEPARENT)),
    ):
        return _process(database, settings, worker_id, stages, providers, now, drafter, job, run_id)


def _process(
    database: Database,
    settings: Settings,
    worker_id: str,
    stages: Mapping[str, Stage],
    providers: Providers | None,
    now: Callable[[], datetime],
    drafter: Drafter,
    job: Any,
    run_id: uuid.UUID,
) -> bool:
    def beat() -> None:
        with database.session() as db:
            if not queue.heartbeat(db, job.id, worker_id, settings.run_lease, now()):
                raise LeaseLost

    if job.kind == ASSESSMENT_JOB:
        return _draft_part(database, drafter, providers, job, worker_id, run_id, beat, now)

    try:
        if job.attempts > MAX_ATTEMPTS:
            logger.error("Run %s: job claimed %s times, run ended", run_id, job.attempts)
            with count_finished(database, run_id):
                fail_run(database, run_id, INTERRUPTED)
        else:
            execute_run(RunEnvironment(database, stages, providers, beat), run_id)
    except LeaseLost:
        logger.warning("Run %s: lease lost, another worker owns the job", run_id)
        return True
    except SQLAlchemyError:
        # The database failed while the run was being saved: the lease will expire and the job
        # will be claimed again, and the run continues from its stage.
        logger.error("Run %s: database error, the job will be reclaimed", run_id, exc_info=True)
        return True
    with database.session() as db:
        queue.finish(db, job.id, worker_id, now())
    return True


def _draft_part(
    database: Database,
    drafter: Drafter,
    providers: Providers | None,
    job: Any,
    worker_id: str,
    run_id: uuid.UUID,
    beat: Callable[[], None],
    now: Callable[[], datetime],
) -> bool:
    """One drafting job. The run itself is not touched: a failure ends the job, the member asks
    again (nothing is stored by a failed draft)."""
    ok = True
    try:
        if job.attempts > MAX_ATTEMPTS:
            raise RuntimeError("claimed too many times")
        drafter(database, providers, run_id, str(job.payload.get("part")), beat)
    except LeaseLost:
        logger.warning("Run %s: lease lost, another worker owns the drafting job", run_id)
        return True
    except SQLAlchemyError:
        logger.error("Run %s: database error, the drafting job will be reclaimed", run_id)
        return True
    except ConfigurationError:
        logger.error("Run %s: drafting not configured", run_id, exc_info=True)
        ok = False
    except Exception as error:
        # A provider outage or an unexpected failure: no detail of the prompt is logged.
        logger.warning("Run %s: drafting failed (%s)", run_id, type(error).__name__)
        ok = False
    with database.session() as db:
        queue.finish(db, job.id, worker_id, now(), ok=ok)
    return True


def main() -> None:
    settings = load_settings()
    telemetry = configure("worker", settings)
    if not settings.database_url:
        raise SystemExit("DATABASE_URL is not set")
    if not settings.crawler_contact_url:
        raise SystemExit(f"{CRAWLER_CONTACT_URL} is not set: collection cannot start without it")
    from app.main import load_providers  # imported here: it builds the API's providers

    database = Database(
        settings.database_url, statement_timeout_seconds=settings.database_statement_timeout_seconds
    )
    providers = load_providers(settings, database)
    worker_id = f"worker-{os.getpid()}-{uuid.uuid4().hex[:6]}"
    stopping = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stopping.set())
    logger.info("Worker %s started", worker_id)
    while not stopping.is_set():
        try:
            if work_once(database, settings, worker_id, providers=providers):
                continue
        except SQLAlchemyError:
            # Database down or not migrated yet: wait, as for an empty queue.
            logger.warning("Worker %s: the database is unavailable", worker_id)
        stopping.wait(settings.worker_poll_seconds)
    database.dispose()
    telemetry.shutdown()  # sends what is left; bounded by the export timeout
    logger.info("Worker %s stopped", worker_id)


if __name__ == "__main__":
    main()

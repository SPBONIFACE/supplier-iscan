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

from sqlalchemy.exc import SQLAlchemyError

from app import queue
from app.config import Settings, load_settings
from app.db import Database, utc_now
from app.providers import Providers
from app.runs.executor import INTERRUPTED, RUN_JOB, RunEnvironment, execute_run, fail_run
from app.runs.stages import DEFAULT_STAGES, LeaseLost, Stage

logger = logging.getLogger(__name__)

# A job claimed more often than this keeps killing its worker: its run is ended, not retried.
MAX_ATTEMPTS = 3


def work_once(
    database: Database,
    settings: Settings,
    worker_id: str,
    stages: Mapping[str, Stage] = DEFAULT_STAGES,
    providers: Providers | None = None,
    now: Callable[[], datetime] = utc_now,
) -> bool:
    """Claim and execute one job. False when there was none."""
    with database.session() as db:
        job = queue.claim(db, worker_id, settings.run_lease, now(), (RUN_JOB,))
    if job is None:
        return False
    run_id = uuid.UUID(job.payload["run_id"])

    def beat() -> None:
        with database.session() as db:
            if not queue.heartbeat(db, job.id, worker_id, settings.run_lease, now()):
                raise LeaseLost

    try:
        if job.attempts > MAX_ATTEMPTS:
            logger.error("Run %s: job claimed %s times, run ended", run_id, job.attempts)
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


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = load_settings()
    if not settings.database_url:
        raise SystemExit("DATABASE_URL is not set")
    from app.main import load_providers  # imported here: it builds the API's providers

    database = Database(settings.database_url)
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
    logger.info("Worker %s stopped", worker_id)


if __name__ == "__main__":
    main()

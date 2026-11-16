"""Start the hosted worker after a commit that queued work (#200).

Called from a FastAPI background task, so the buyer's response never waits for it, and only after
the transaction committed, so the worker always finds the job. With `WORKER_JOB_NAME` unset
(local Docker Compose, tests) nothing is started: an always-on worker polls the queue.
"""

from fastapi import BackgroundTasks

from app.config import Settings
from app.http_client import start_worker_job


def start_worker(settings: Settings) -> None:
    if settings.worker_job_name:
        start_worker_job(settings.worker_job_name)


def start_worker_after_response(background: BackgroundTasks, settings: Settings) -> None:
    if settings.worker_job_name:
        background.add_task(start_worker, settings)

"""PostgreSQL job queue (spec, Architecture constraints; approved-dependencies: own queue on
psycopg, no library).

A job is a row of `jobs`. A worker claims one with `SELECT ... FOR UPDATE SKIP LOCKED`, so two
workers never get the same row, and holds it under a lease. The lease is extended by `heartbeat`;
a job whose lease has expired (its worker died) is claimed again, so no job stays `running` for
ever. Every function takes the caller's session and commits itself; `now` is a parameter so that
tests control time.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from app.models import Job
from app.telemetry import TRACEPARENT, current_traceparent


@dataclass(frozen=True)
class ClaimedJob:
    id: uuid.UUID
    kind: str
    payload: dict[str, Any]
    attempts: int  # including this claim


def enqueue(db: Session, kind: str, payload: dict[str, Any]) -> uuid.UUID:
    """Add a job in the caller's transaction (the caller commits, with its own changes). The
    trace of the caller travels in the payload (`traceparent`), so that the worker continues it."""
    traceparent = current_traceparent()
    if traceparent is not None:
        payload = {**payload, TRACEPARENT: traceparent}
    job = Job(kind=kind, payload=payload)
    db.add(job)
    db.flush()
    return job.id


def claim(
    db: Session, worker_id: str, lease: timedelta, now: datetime, kinds: tuple[str, ...]
) -> ClaimedJob | None:
    """The oldest queued job, or running job whose lease has expired; None when there is none."""
    job = db.scalar(
        select(Job)
        .where(
            Job.kind.in_(kinds),
            or_(
                Job.state == "queued",
                and_(Job.state == "running", Job.lease_expires_at < now),
            ),
        )
        .order_by(Job.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        db.rollback()
        return None
    job.state = "running"
    job.locked_by = worker_id
    job.lease_expires_at = now + lease
    job.attempts += 1
    claimed = ClaimedJob(job.id, job.kind, dict(job.payload), job.attempts)
    db.commit()
    return claimed


def heartbeat(
    db: Session, job_id: uuid.UUID, worker_id: str, lease: timedelta, now: datetime
) -> bool:
    """Extend the lease. False when the job is no longer this worker's (lease lost)."""
    result = db.execute(
        update(Job)
        .where(Job.id == job_id, Job.state == "running", Job.locked_by == worker_id)
        .values(lease_expires_at=now + lease)
    )
    db.commit()
    return bool(result.rowcount == 1)  # type: ignore[attr-defined]


def finish(db: Session, job_id: uuid.UUID, worker_id: str, now: datetime, ok: bool = True) -> None:
    """Close the job, if it is still this worker's."""
    db.execute(
        update(Job)
        .where(Job.id == job_id, Job.state == "running", Job.locked_by == worker_id)
        .values(state="done" if ok else "failed", finished_at=now, lease_expires_at=None)
    )
    db.commit()

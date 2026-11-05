"""Executes one run in the worker, stage by stage (spec Flow 1 step 4; F7 stop; Robustness).

The run record is the state: `stage` is the stage being executed, so a resumed or reclaimed run
continues there and completed stages are never executed again. Every change of the run is made
under a row lock, so a member's stop and the worker's progress never overwrite each other.
"""

import logging
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from sqlalchemy import select

from app.config import ConfigurationError
from app.db import Database, utc_now
from app.limits.budget import RunBudgetExhausted
from app.limits.partial import explanation, uncovered_sections
from app.models import ProfileRun
from app.models.runs import FINISHED_STATUSES, RUN_STAGES
from app.profile_definition import ProfileDefinition
from app.providers import Providers
from app.runs.stages import (
    LeaseLost,
    RunStopped,
    Stage,
    StageContext,
    StageOutcome,
    classify,
    pause_reason,
)

logger = logging.getLogger(__name__)

RUN_JOB = "profile_run"  # the kind of the queue job that executes a run
INTERRUPTED = "The run was interrupted too many times and was ended."
FAILED = "The run failed unexpectedly."
NOT_CONFIGURED = (
    "Collection is not available because the service is not fully configured. "
    "Please contact the administrator."
)


@dataclass(frozen=True)
class RunEnvironment:
    database: Database
    stages: Mapping[str, Stage]
    providers: Providers | None
    # Extends the job's lease; raises LeaseLost when the job is no longer this worker's.
    beat: Callable[[], None]
    # The profile definition, to name the sections a partial run did not cover; the one of the
    # settings when not given.
    definition: ProfileDefinition | None = None


def _update(database: Database, run_id: uuid.UUID, change: Callable[[ProfileRun], None]) -> None:
    """Apply `change` to the run under a row lock, only while the run is `running`."""
    with database.session() as db:
        run = db.scalar(select(ProfileRun).where(ProfileRun.id == run_id).with_for_update())
        if run is not None and run.status == "running":
            change(run)
            db.commit()


def _finish(run: ProfileRun, status: str, counts: bool = True) -> None:
    run.status = status
    run.finished_at = utc_now()
    run.counts_against_quota = counts


def _is_stopped(database: Database, run_id: uuid.UUID) -> bool:
    with database.session() as db:
        run = db.get(ProfileRun, run_id)
        return run is None or run.stop_requested or run.status == "stopped"


def fail_run(database: Database, run_id: uuid.UUID, reason: str) -> None:
    """End the run `failed`, whatever its status while it is not final: a run still `queued`
    (workers died between claiming the job and starting it, #13 follow-up) or `paused` ends too."""
    with database.session() as db:
        run = db.scalar(select(ProfileRun).where(ProfileRun.id == run_id).with_for_update())
        if run is not None and run.status not in FINISHED_STATUSES:
            _finish(run, "failed")
            run.error = reason
            db.commit()


def _pause(database: Database, run_id: uuid.UUID, dependency: str, reason: str) -> None:
    def change(run: ProfileRun) -> None:
        if run.stop_requested:
            _finish(run, "stopped")
            return
        run.status = "paused"
        run.pause_dependency = dependency
        run.pause_reason = reason
        run.counts_against_quota = False

    _update(database, run_id, change)


def _default_definition() -> ProfileDefinition:
    from app.config import load_settings
    from app.main import load_definition

    return load_definition(load_settings())


def _end_partial(
    env: "RunEnvironment", run_id: uuid.UUID, stage: str, done: frozenset[str]
) -> None:
    """The run reached its cost budget (#30): it ends `partial`, which counts against the quota,
    with the sections it did not cover and a plain explanation. What it produced is kept."""
    definition = env.definition or _default_definition()
    with env.database.session() as db:
        run = db.scalar(select(ProfileRun).where(ProfileRun.id == run_id).with_for_update())
        if run is None or run.status != "running":
            return
        if run.stop_requested:
            _finish(run, "stopped")
            db.commit()
            return
        uncovered = uncovered_sections(db, run, definition, done)
        _finish(run, "partial")
        run.uncovered_sections = uncovered
        run.partial_explanation = explanation(stage, uncovered, definition)
        db.commit()
    logger.info("Run %s ended partial at its cost budget, in stage %s", run_id, stage)


def _advance(database: Database, run_id: uuid.UUID, stage: str) -> None:
    index = RUN_STAGES.index(stage)

    def change(run: ProfileRun) -> None:
        if index + 1 < len(RUN_STAGES):
            run.stage = RUN_STAGES[index + 1]
        else:
            _finish(run, "completed")

    _update(database, run_id, change)


def _end_with(database: Database, run_id: uuid.UUID, outcome: StageOutcome) -> None:
    # "Insufficient sources" does not count against the quota (spec F7).
    _update(
        database,
        run_id,
        lambda run: _finish(run, outcome, counts=outcome != "insufficient_sources"),
    )


def execute_run(env: RunEnvironment, run_id: uuid.UUID) -> None:
    """Run the stages from the run's current stage. Returns when the run is no longer `running`."""
    with env.database.session() as db:
        run = db.scalar(select(ProfileRun).where(ProfileRun.id == run_id).with_for_update())
        if run is None or run.status not in ("queued", "running"):
            return  # stopped while queued, or already finished: nothing to do
        if run.stop_requested:
            _finish(run, "stopped")
            db.commit()
            return
        if run.status == "queued":
            run.status = "running"
            run.started_at = run.started_at or utc_now()
        organisation_id, first_stage = run.organisation_id, run.stage
        db.commit()

    def check_stop() -> None:
        env.beat()
        if _is_stopped(env.database, run_id):
            raise RunStopped

    stage = first_stage
    try:
        for stage in RUN_STAGES[RUN_STAGES.index(first_stage) :]:
            check_stop()
            context = StageContext(
                run_id, organisation_id, stage, env.database, env.providers, check_stop
            )
            outcome = env.stages[stage](context)
            if outcome is not None:
                _end_with(env.database, run_id, outcome)
                return
            _advance(env.database, run_id, stage)
    except LeaseLost:
        raise
    except RunStopped:
        _update(env.database, run_id, lambda run: _finish(run, "stopped"))
    except RunBudgetExhausted as exhausted:
        _end_partial(env, run_id, stage, exhausted.done)
    except ConfigurationError:
        # The operator named the setting in the log; the member gets a plain message, and the run
        # ends as failed (no request was sent).
        logger.error(
            "Run %s failed in stage %s: the service is not configured", run_id, stage, exc_info=True
        )
        fail_run(env.database, run_id, NOT_CONFIGURED)
    except Exception as error:
        dependency = classify(error)
        if dependency is None:
            logger.error("Run %s failed in stage %s", run_id, stage, exc_info=True)
            fail_run(env.database, run_id, FAILED)
        else:
            logger.warning(
                "Run %s paused in stage %s: %s unavailable (%s)",
                run_id,
                stage,
                dependency,
                type(error).__name__,
            )
            _pause(env.database, run_id, dependency, pause_reason(error, dependency))

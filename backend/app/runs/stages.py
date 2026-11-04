"""The stages of a run, and how a failure is told apart.

A stage is a function of a `StageContext`. Collection is real (#103); the others are still
no-ops: #23 and #24 (extraction), #25 and #26 (assessment) replace them in `DEFAULT_STAGES`.
Rules for a stage:

- It may be executed again after a crash or a resume, so it must not duplicate stored results
  (it writes with a key such as the run id and the field, and skips what is stored).
- It calls `context.check_stop()` before every provider call, and passes `context.call_context`
  on every provider call (so that the usage is metered against the run).
- It raises `DependencyUnavailable` (or lets a provider, database or network error escape) when a
  dependency fails: the run pauses and the member can resume it.
"""

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.exc import InterfaceError, OperationalError

from app.db import Database, DatabaseUnavailable
from app.http_client import DnsResolutionError, FetchTimeoutError
from app.providers import Providers, StructuredOutputInvalid
from app.providers.errors import ProviderError
from app.providers.metering import CallContext
from app.redaction import RedactionUnavailable

# A stage returns None to go on, or the final status of a run that cannot go on.
StageOutcome = Literal["insufficient_sources", "partial"]

# In the plain language shown to the member; each names the dependency.
DEPENDENCY_REASONS: dict[str, str] = {
    "structuring_provider": "The structuring provider is unavailable.",
    "retrieval_provider": "The retrieval provider is unavailable.",
    "llm_provider": "An AI provider is unavailable.",
    "registry": "A public registry is unavailable.",
    "website": "The supplier's website could not be reached.",
    "database": "The database is unavailable.",
    "network": "The network connection failed.",
}


class DependencyUnavailable(Exception):
    """A stage raises it when a dependency it needs is down."""

    def __init__(self, dependency: str) -> None:
        if dependency not in DEPENDENCY_REASONS:
            raise ValueError(f"unknown dependency {dependency!r}")
        super().__init__(dependency)
        self.dependency = dependency


class RunStopped(Exception):
    """A member stopped the run."""


class LeaseLost(Exception):
    """The job is no longer this worker's (its lease expired and another worker took it)."""


def classify(error: BaseException) -> str | None:
    """The dependency behind a failure, or None when it is not a dependency failure."""
    if isinstance(error, DependencyUnavailable):
        return error.dependency
    if isinstance(error, RedactionUnavailable):
        # The contract's dependency list has no redaction entry: nothing reached a provider, so
        # the run pauses as an AI-provider step, with its own plain-language reason.
        return "llm_provider"
    if isinstance(error, StructuredOutputInvalid):
        return None  # the provider answered; the answer was unusable
    if isinstance(error, ProviderError):
        return "llm_provider"
    if isinstance(error, OperationalError | InterfaceError | DatabaseUnavailable):
        return "database"
    if isinstance(error, DnsResolutionError | FetchTimeoutError | ConnectionError | TimeoutError):
        return "network"
    return None


def pause_reason(error: BaseException, dependency: str) -> str:
    """The plain-language reason shown to the member for a paused run."""
    if isinstance(error, RedactionUnavailable):
        return RedactionUnavailable.REASON
    return DEPENDENCY_REASONS[dependency]


@dataclass(frozen=True)
class StageContext:
    run_id: uuid.UUID
    organisation_id: uuid.UUID
    stage: str
    database: Database
    providers: Providers | None
    # Raises RunStopped when a member stopped the run, and extends the job's lease.
    check_stop: Callable[[], None]

    @property
    def call_context(self) -> CallContext:
        return CallContext(organisation_id=self.organisation_id, run_id=self.run_id)


Stage = Callable[[StageContext], StageOutcome | None]


def no_op(context: StageContext) -> None:
    return None


def collection_stage(context: StageContext) -> StageOutcome | None:
    """The real collection stage (#18 to #20), built when the stage runs in the worker: the
    crawler's contact page comes from the settings (`CRAWLER_CONTACT_URL`, #17)."""
    from app.collection.stage import make_collection_stage  # imported here: it imports this module
    from app.config import load_settings

    return make_collection_stage(load_settings().crawler_contact_url)(context)


DEFAULT_STAGES: Mapping[str, Stage] = {
    "identity": no_op,
    "collection": collection_stage,
    "extraction": no_op,
    "assessment": no_op,
}

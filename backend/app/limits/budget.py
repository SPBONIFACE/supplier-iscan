"""The per-run cost budget (spec F7, Robustness: "Run budget exhausted"; #30).

Before every provider attempt of a run (a first call and each retry alike), the client asks the
budget: the billed cost of the run so far (every `llm_usage` row of #12: failed, retried and
invalid-output attempts, search tools and reasoning tokens included) plus the largest cost the
attempt can have must stay within the configured budget. If not, `RunBudgetExhausted` is raised
and the call is not made. A run that already ended `partial` makes no further call at all.

Maximum overrun. The estimate is an upper bound (one token per character of input, the whole
output allowance priced at the dearer of the output and reasoning prices, the largest number of
tool calls an adapter allows), so a run whose calls are made one after the other never exceeds
the budget. The check reads recorded usage, and two calls of the same run in flight at once both
see the same total: that happens only for the two drafting jobs (fit, recommendations) the
member queues on a finished run. The overrun is therefore at most ONE call: the smaller of the
two estimates, or the part of one call's real cost (a provider-reported billed amount) that is
above its estimate. No other call of the run can be in flight.
"""

import uuid
from decimal import Decimal
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import Database
from app.models import LlmUsage, ProfileRun


class RunBudgetExhausted(Exception):
    """The next provider attempt of the run would exceed its budget; nothing was sent.

    `done` is set by the assessment stage: the parts it had finished (it keeps them).
    """

    def __init__(self, done: frozenset[str] = frozenset()) -> None:
        super().__init__("run budget reached")
        self.done = done


class BudgetGate(Protocol):
    """What a provider client needs: the retry bound and the check before each attempt."""

    @property
    def max_retries(self) -> int: ...

    def check(self, organisation_id: uuid.UUID, run_id: uuid.UUID, estimate: Decimal) -> None: ...


def spent(db: Session, organisation_id: uuid.UUID, run_id: uuid.UUID) -> Decimal:
    """The billed cost of the run so far, in EUR."""
    total = db.scalar(
        select(func.coalesce(func.sum(LlmUsage.cost), Decimal(0))).where(
            LlmUsage.organisation_id == organisation_id, LlmUsage.run_id == run_id
        )
    )
    return Decimal(total or 0)


class RunBudget:
    def __init__(self, database: Database, budget_eur: Decimal, max_retries: int) -> None:
        if budget_eur <= 0:
            raise ValueError("the run budget must be above 0")
        self._database = database
        self.budget_eur = budget_eur
        self._max_retries = max_retries

    @property
    def max_retries(self) -> int:
        return self._max_retries

    def check(self, organisation_id: uuid.UUID, run_id: uuid.UUID, estimate: Decimal) -> None:
        with self._database.session() as db:
            status = db.scalar(select(ProfileRun.status).where(ProfileRun.id == run_id))
            if status == "partial":
                raise RunBudgetExhausted  # it stopped at its budget: no further call is made
            if spent(db, organisation_id, run_id) + estimate > self.budget_eur:
                raise RunBudgetExhausted


def used_up(db: Session, run: ProfileRun, budget_eur: Decimal | None) -> bool:
    """The run ended `partial`, or has billed its whole budget: a request to draft more for it
    (fit, recommendations) is refused, since no further call would be made."""
    if run.status == "partial":
        return True
    return budget_eur is not None and spent(db, run.organisation_id, run.id) >= budget_eur

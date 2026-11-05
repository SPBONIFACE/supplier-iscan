"""Whether a new profile run would be refused now, and why (spec F7, Robustness cases).

One function, read by GET /organisation so that the workspace can say it before the member
starts. The reason codes are those of openapi.yaml (`run_refusal_reason`).
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import utc_now
from app.errors import RunRefusedError
from app.models import LlmUsage, Organisation, ProfileRun

RefusalReason = Literal["not_activated", "access_ended", "quota_reached", "spend_cap_reached"]

# Plain messages, one per reason (the screens word the same cases in the member's language). They
# say what is refused and that what exists stays readable; they claim nothing about a supplier.
REFUSAL_MESSAGES: dict[str, str] = {
    "not_activated": (
        "New profile runs are refused because your organisation has not been activated yet. "
        "Your existing profiles remain readable."
    ),
    "access_ended": (
        "New profile runs are refused because your organisation's access has ended. "
        "Your existing profiles remain readable."
    ),
    "quota_reached": (
        "New profile runs are refused because your organisation has used its profile quota. "
        "Your existing profiles remain readable."
    ),
    "spend_cap_reached": (
        "New AI work is refused because this instance has reached its monthly limit for AI "
        "usage. Your existing profiles remain readable. It is possible again next month, or "
        "earlier if the administrator raises the limit."
    ),
}


def profiles_remaining(db: Session, organisation: Organisation) -> int | None:
    """Runs that may still start under the quota; None when the quota is unlimited."""
    if organisation.profile_quota is None:
        return None
    used = db.scalar(
        select(func.count())
        .select_from(ProfileRun)
        .where(
            ProfileRun.organisation_id == organisation.id,
            ProfileRun.counts_against_quota.is_(True),
        )
    )
    return max(0, organisation.profile_quota - (used or 0))


def monthly_spend_eur(db: Session, now: datetime) -> Decimal:
    """Everything the instance spent on LLM calls since the start of the current UTC month."""
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = db.scalar(select(func.sum(LlmUsage.cost)).where(LlmUsage.created_at >= start))
    return Decimal(total or 0)


def run_refusal_reason(
    db: Session, organisation: Organisation, settings: Settings, now: datetime | None = None
) -> RefusalReason | None:
    now = now or utc_now()
    if organisation.status == "pending_activation":
        return "not_activated"
    if organisation.access_ends_at is not None and organisation.access_ends_at <= now:
        return "access_ended"
    remaining = profiles_remaining(db, organisation)
    if remaining is not None and remaining == 0:
        return "quota_reached"
    cap = settings.monthly_spend_cap_eur
    if cap is not None and monthly_spend_eur(db, now) >= cap:
        return "spend_cap_reached"
    return None


def refuse(reason: RefusalReason) -> RunRefusedError:
    return RunRefusedError(reason, REFUSAL_MESSAGES[reason])


def spend_cap_reached(db: Session, settings: Settings, now: datetime | None = None) -> bool:
    """True when this month's LLM spend of the instance has reached the cap (none set: False)."""
    cap = settings.monthly_spend_cap_eur
    return cap is not None and monthly_spend_eur(db, now or utc_now()) >= cap


def reserve_run_slot(db: Session, organisation_id: uuid.UUID, settings: Settings) -> None:
    """Refuse a new run now, or allow it (#29). Call it inside the transaction that inserts the
    run, before it: the organisation row stays locked until that transaction ends, so two starts
    for the same organisation are checked one after the other, and the second sees the first's
    run (a run that has not ended counts until it ends without counting). Raises RunRefusedError.

    The monthly cap is the instance's, read from the usage records: simultaneous starts across
    organisations can each pass just under it; the spend they cause is recorded as it happens.
    """
    organisation = db.scalar(
        select(Organisation).where(Organisation.id == organisation_id).with_for_update()
    )
    if organisation is None:
        raise refuse("not_activated")
    reason = run_refusal_reason(db, organisation, settings)
    if reason is not None:
        raise refuse(reason)


def check_resume(db: Session, organisation_id: uuid.UUID, settings: Settings) -> None:
    """Refuse to resume a paused run when resuming would spend where new work is not allowed (#29):
    the organisation is not activated, its access has ended, or the instance's monthly spend cap is
    reached. The quota is not checked: the run continues, it is not a new one."""
    organisation = db.scalar(select(Organisation).where(Organisation.id == organisation_id))
    if organisation is None or organisation.status == "pending_activation":
        raise refuse("not_activated")
    now = utc_now()
    if organisation.access_ends_at is not None and organisation.access_ends_at <= now:
        raise refuse("access_ended")
    if spend_cap_reached(db, settings, now):
        raise refuse("spend_cap_reached")

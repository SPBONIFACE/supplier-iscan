"""Whether a new profile run would be refused now, and why (spec F7, Robustness cases).

One function, read by GET /organisation so that the workspace can say it before the member
starts. The reason codes are those of openapi.yaml (`run_refusal_reason`).
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import utc_now
from app.models import LlmUsage, Organisation, ProfileRun

RefusalReason = Literal["not_activated", "access_ended", "quota_reached", "spend_cap_reached"]


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

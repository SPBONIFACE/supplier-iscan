"""Usage records in the database, and per-run totals (#12).

`run_usage_totals` is the single source of a run's tokens, cost and models. #13 writes it onto the
run record, #29 (monthly spend) and #30 (run budget) read the same records, so every failed and
retried attempt is in the figures they use.
"""

import uuid
from dataclasses import asdict, dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import Database
from app.models import LlmUsage
from app.providers.metering import UsageEntry


class DbUsageSink:
    """Writes each record in its own transaction, so a caller's rollback never loses metering."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def record(self, entry: UsageEntry) -> None:
        with self._database.session() as db:
            db.add(LlmUsage(**asdict(entry)))
            db.commit()


@dataclass(frozen=True)
class RoleModel:
    config_id: str
    provider: str
    model_id: str


@dataclass(frozen=True)
class RunUsageTotals:
    calls: int
    input_tokens: int
    output_tokens: int  # without reasoning tokens
    reasoning_tokens: int
    tool_calls: int
    cost: Decimal  # EUR
    roles: dict[str, tuple[RoleModel, ...]]  # per role, the configurations used, first used first


def run_usage_totals(db: Session, organisation_id: uuid.UUID, run_id: uuid.UUID) -> RunUsageTotals:
    """Totals of every attempt of a run: failed, retried and invalid-output ones included."""
    totals = db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(LlmUsage.input_tokens), 0),
            func.coalesce(func.sum(LlmUsage.output_tokens), 0),
            func.coalesce(func.sum(LlmUsage.reasoning_tokens), 0),
            func.coalesce(func.sum(LlmUsage.tool_calls), 0),
            func.coalesce(func.sum(LlmUsage.cost), Decimal(0)),
        ).where(LlmUsage.organisation_id == organisation_id, LlmUsage.run_id == run_id)
    ).one()
    models = db.execute(
        select(
            LlmUsage.role,
            LlmUsage.provider_config_id,
            LlmUsage.provider,
            LlmUsage.model_id,
        )
        .where(LlmUsage.organisation_id == organisation_id, LlmUsage.run_id == run_id)
        .group_by(LlmUsage.role, LlmUsage.provider_config_id, LlmUsage.provider, LlmUsage.model_id)
        .order_by(func.min(LlmUsage.created_at), LlmUsage.provider_config_id)
    ).all()
    roles: dict[str, list[RoleModel]] = {}
    for role, config_id, provider, model_id in models:
        roles.setdefault(role, []).append(RoleModel(config_id, provider, model_id))
    calls, input_tokens, output_tokens, reasoning_tokens, tool_calls, cost = totals
    return RunUsageTotals(
        calls=int(calls),
        input_tokens=int(input_tokens),
        output_tokens=int(output_tokens),
        reasoning_tokens=int(reasoning_tokens),
        tool_calls=int(tool_calls),
        cost=Decimal(cost),
        roles={role: tuple(items) for role, items in roles.items()},
    )

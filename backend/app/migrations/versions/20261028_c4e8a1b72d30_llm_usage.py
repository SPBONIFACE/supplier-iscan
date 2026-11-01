"""Per-call LLM usage records (#12): llm_usage.

Revision ID: c4e8a1b72d30
Revises: b3d5f7a91c20
Create Date: 2026-10-28 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4e8a1b72d30"
down_revision: str | None = "b3d5f7a91c20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_usage",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organisation_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("provider_config_id", sa.String(length=100), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model_id", sa.String(length=200), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("reasoning_tokens", sa.Integer(), nullable=False),
        sa.Column("tool_calls", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("billed_amount", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("billed_currency", sa.String(length=3), nullable=False),
        sa.Column("exchange_rate", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("cost", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("cost_basis", sa.String(length=20), nullable=False),
        sa.Column("price_as_of", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('retrieval', 'structuring')", name=op.f("ck_llm_usage_role")),
        sa.CheckConstraint(
            "outcome IN ('success', 'invalid_output', 'failed')",
            name=op.f("ck_llm_usage_outcome"),
        ),
        sa.CheckConstraint(
            "cost_basis IN ('provider', 'price_table', 'unreported')",
            name=op.f("ck_llm_usage_cost_basis"),
        ),
        sa.CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND reasoning_tokens >= 0"
            " AND tool_calls >= 0 AND attempt >= 1 AND cost >= 0 AND billed_amount >= 0",
            name=op.f("ck_llm_usage_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_llm_usage_organisation_id_organisations"),
        ),
        sa.ForeignKeyConstraint(
            ["provider_config_id"],
            ["provider_configs.id"],
            name=op.f("fk_llm_usage_provider_config_id_provider_configs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_usage")),
    )
    op.create_index("ix_llm_usage_run_id", "llm_usage", ["run_id"])
    op.create_index(
        "ix_llm_usage_organisation_id_created_at", "llm_usage", ["organisation_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_llm_usage_organisation_id_created_at", table_name="llm_usage")
    op.drop_index("ix_llm_usage_run_id", table_name="llm_usage")
    op.drop_table("llm_usage")

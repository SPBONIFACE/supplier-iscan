"""Approved provider configurations (#11): provider_configs.

Revision ID: b3d5f7a91c20
Revises: ff6bede2fa28
Create Date: 2026-10-27 21:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3d5f7a91c20"
down_revision: str | None = "ff6bede2fa28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_configs",
        sa.Column("id", sa.String(length=100), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("api", sa.String(length=200), nullable=False),
        sa.Column("model_id", sa.String(length=200), nullable=False),
        sa.Column("endpoint", sa.String(length=500), nullable=False),
        sa.Column("training_setting", sa.String(length=200), nullable=False),
        sa.Column("retention", sa.String(length=200), nullable=False),
        sa.Column("region", sa.String(length=200), nullable=False),
        sa.Column("transfer_mechanism", sa.String(length=200), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "provider IN ('anthropic', 'google', 'openai', 'mistral', 'perplexity')",
            name=op.f("ck_provider_configs_provider"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_configs")),
    )


def downgrade() -> None:
    op.drop_table("provider_configs")

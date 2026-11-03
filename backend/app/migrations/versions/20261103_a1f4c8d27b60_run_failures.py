"""run failures

Revision ID: a1f4c8d27b60
Revises: e7b3d2c85f14
Create Date: 2026-11-03 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1f4c8d27b60"
down_revision: str | None = "e7b3d2c85f14"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "run_failures",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(length=2000), nullable=True),
        sa.Column("strategy", sa.String(length=20), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("next_strategy", sa.String(length=20), nullable=True),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organisation_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_run_failures_organisation_id_organisations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["profile_runs.id"],
            name=op.f("fk_run_failures_run_id_profile_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_run_failures")),
    )
    op.create_index(
        op.f("ix_run_failures_organisation_id"), "run_failures", ["organisation_id"], unique=False
    )
    op.create_index(op.f("ix_run_failures_run_id"), "run_failures", ["run_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_run_failures_run_id"), table_name="run_failures")
    op.drop_index(op.f("ix_run_failures_organisation_id"), table_name="run_failures")
    op.drop_table("run_failures")

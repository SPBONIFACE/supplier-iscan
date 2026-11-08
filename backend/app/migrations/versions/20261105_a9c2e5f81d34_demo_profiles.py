"""demo profiles (read-only copies for the public demo)

Revision ID: a9c2e5f81d34
Revises: f7a1c4e92b05
Create Date: 2026-11-05 21:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a9c2e5f81d34"
# The head of main when #50 was written. #29 adds no migration, so the two pull requests do not
# chain; a later migration must take this one as its parent.
down_revision: str | None = "f7a1c4e92b05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "demo_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("demo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("supplier_name", sa.String(length=300), nullable=False),
        sa.Column("run", sa.JSON(), nullable=False),
        sa.Column("facts", sa.JSON(), nullable=False),
        sa.Column("assessment", sa.JSON(), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_demo_profiles")),
    )


def downgrade() -> None:
    op.drop_table("demo_profiles")

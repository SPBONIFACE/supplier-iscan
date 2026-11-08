"""review fields of facts and assessment statements

Revision ID: e6f9b3d48c02
Revises: d5e8a2c37b91
Create Date: 2026-11-05 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e6f9b3d48c02"
down_revision: str | None = "d5e8a2c37b91"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, the column that keeps the AI value once a member corrects it)
TABLES = (("facts", "original_value"), ("assessment_statements", "original_text"))


def upgrade() -> None:
    for table, original in TABLES:
        op.add_column(table, sa.Column(original, sa.Text(), nullable=True))
        op.add_column(table, sa.Column("version", sa.Integer(), server_default="1", nullable=False))
        op.add_column(table, sa.Column("reviewed_by", sa.Uuid(), nullable=True))
        op.add_column(table, sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
        op.create_foreign_key(
            op.f(f"fk_{table}_reviewed_by_users"),
            table,
            "users",
            ["reviewed_by"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    for table, original in TABLES:
        op.drop_constraint(op.f(f"fk_{table}_reviewed_by_users"), table, type_="foreignkey")
        op.drop_column(table, "reviewed_at")
        op.drop_column(table, "reviewed_by")
        op.drop_column(table, "version")
        op.drop_column(table, original)

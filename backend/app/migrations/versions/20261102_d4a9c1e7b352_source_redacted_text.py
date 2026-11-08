"""rename sources.text to redacted_text

Revision ID: d4a9c1e7b352
Revises: 10c28898ef5b
Create Date: 2026-11-02 15:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d4a9c1e7b352"
down_revision: str | None = "45b374679350"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("sources", "text", new_column_name="redacted_text")


def downgrade() -> None:
    op.alter_column("sources", "redacted_text", new_column_name="text")

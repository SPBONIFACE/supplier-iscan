"""uncovered sections and explanation of a partial run

Revision ID: f7a1c4e92b05
Revises: d5e8a2c37b91
Create Date: 2026-11-05 19:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f7a1c4e92b05"
# When the review migration of #28 (e6f9b3d48c02) is merged first, this becomes "e6f9b3d48c02".
down_revision: str | None = "d5e8a2c37b91"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "profile_runs",
        sa.Column("uncovered_sections", sa.JSON(), server_default="[]", nullable=False),
    )
    op.add_column("profile_runs", sa.Column("partial_explanation", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("profile_runs", "partial_explanation")
    op.drop_column("profile_runs", "uncovered_sections")

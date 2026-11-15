"""The parent group of a confirmed identity and the group-level label of a fact (#195)

Revision ID: c5a8d2e61f37
Revises: b4e7c1a93d28
Create Date: 2026-11-15 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c5a8d2e61f37"
down_revision: str | None = "b4e7c1a93d28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("supplier_identities", sa.Column("group_name", sa.String(300)))
    op.add_column("supplier_identities", sa.Column("group_website", sa.String(2000)))
    op.add_column("facts", sa.Column("group_level", sa.String(300)))


def downgrade() -> None:
    op.drop_column("facts", "group_level")
    op.drop_column("supplier_identities", "group_website")
    op.drop_column("supplier_identities", "group_name")

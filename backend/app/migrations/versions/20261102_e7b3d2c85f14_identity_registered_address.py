"""supplier_identities.registered_address (natural persons only)

Revision ID: e7b3d2c85f14
Revises: d4a9c1e7b352
Create Date: 2026-11-02 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7b3d2c85f14"
down_revision: str | None = "d4a9c1e7b352"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "supplier_identities",
        sa.Column("registered_address", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("supplier_identities", "registered_address")

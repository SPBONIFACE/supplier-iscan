"""supplier_identities.country holds the ISO alpha-2 code (#136)

Revision ID: b4e7c1a93d28
Revises: a9c2e5f81d34
Create Date: 2026-11-08 10:00:00.000000

One-way: a row that held a name ("France") now holds its code ("FR") when the English or French
name maps unambiguously; a two-letter value is upper-cased; any other value is left unchanged. The
original names are not kept, so the downgrade does nothing (the code is a valid value for the column
either way).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.countries import code_for_name, normalise_code

revision: str = "b4e7c1a93d28"
down_revision: str | None = "a9c2e5f81d34"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id, country FROM supplier_identities WHERE country IS NOT NULL")
    ).all()
    for row_id, country in rows:
        code = normalise_code(country) or code_for_name(country)
        if code and code != country:
            connection.execute(
                sa.text("UPDATE supplier_identities SET country = :code WHERE id = :id"),
                {"code": code, "id": row_id},
            )


def downgrade() -> None:
    """One-way: the names are not recoverable, and a code is valid for the column."""

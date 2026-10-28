"""Organisation limits and invitations (#9).

Adds seat_limit, profile_quota, access_period_days and access_ends_at to organisations (null means
unlimited), and the invitations table (only a hash of each token is stored).

Revision ID: ff6bede2fa28
Revises: 7c1e2a9f4b10
Create Date: 2026-10-27 21:40:43.688114
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ff6bede2fa28"
down_revision: str | None = "7c1e2a9f4b10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LIMITS = ("seat_limit", "profile_quota", "access_period_days")


def upgrade() -> None:
    for column in _LIMITS:
        op.add_column("organisations", sa.Column(column, sa.Integer(), nullable=True))
        op.create_check_constraint(
            op.f(f"ck_organisations_{column}_positive"),
            "organisations",
            f"{column} IS NULL OR {column} > 0",
        )
    op.add_column(
        "organisations", sa.Column("access_ends_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_table(
        "invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organisation_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_invitations_organisation_id_organisations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invitations")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_invitations_token_hash")),
    )
    op.create_index(
        op.f("ix_invitations_organisation_id"), "invitations", ["organisation_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_invitations_organisation_id"), table_name="invitations")
    op.drop_table("invitations")
    op.drop_column("organisations", "access_ends_at")
    for column in reversed(_LIMITS):
        op.drop_constraint(
            op.f(f"ck_organisations_{column}_positive"), "organisations", type_="check"
        )
        op.drop_column("organisations", column)

"""facts, linked PDFs and extraction counts

Revision ID: b8c2d6f13a45
Revises: a1f4c8d27b60
Create Date: 2026-11-04 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8c2d6f13a45"
down_revision: str | None = "a1f4c8d27b60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("linked_from_source_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_sources_linked_from_source_id_sources"),
        "sources",
        "sources",
        ["linked_from_source_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "profile_runs",
        sa.Column("grounding_failures", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "profile_runs",
        sa.Column("invalid_items", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_table(
        "facts",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("section", sa.String(length=200), nullable=False),
        sa.Column("field", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("quote", sa.Text(), nullable=True),
        sa.Column("quote_redacted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("source_url", sa.String(length=2000), nullable=True),
        sa.Column("source_type", sa.String(length=20), nullable=True),
        sa.Column("publisher", sa.String(length=300), nullable=True),
        sa.Column("author", sa.String(length=300), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organisation_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status IN ('proposed', 'approved', 'corrected', 'not_found')",
            name=op.f("ck_facts_status"),
        ),
        sa.CheckConstraint(
            "source_type IS NULL OR source_type IN ('supplier_claim', 'third_party')",
            name=op.f("ck_facts_source_type"),
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_facts_organisation_id_organisations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["profile_runs.id"],
            name=op.f("fk_facts_run_id_profile_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name=op.f("fk_facts_source_id_sources"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_facts")),
        sa.UniqueConstraint("run_id", "field", name="run_field"),
    )
    op.create_index(op.f("ix_facts_organisation_id"), "facts", ["organisation_id"], unique=False)
    op.create_index(op.f("ix_facts_run_id"), "facts", ["run_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_facts_run_id"), table_name="facts")
    op.drop_index(op.f("ix_facts_organisation_id"), table_name="facts")
    op.drop_table("facts")
    op.drop_column("profile_runs", "invalid_items")
    op.drop_column("profile_runs", "grounding_failures")
    op.drop_constraint(
        op.f("fk_sources_linked_from_source_id_sources"), "sources", type_="foreignkey"
    )
    op.drop_column("sources", "linked_from_source_id")

"""assessment statements and assessment counts

Revision ID: c3d7e9f14a62
Revises: b8c2d6f13a45
Create Date: 2026-11-05 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3d7e9f14a62"
down_revision: str | None = "b8c2d6f13a45"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KINDS = (
    "'strength', 'weakness', 'opportunity', 'threat', 'risk_indicator', 'evidence_gap', "
    "'procurement_implication', 'relationship_level', 'contract_approach', 'volume_share', "
    "'next_action', 'procurement_priority'"
)


def upgrade() -> None:
    op.add_column(
        "profile_runs",
        sa.Column("rejected_statements", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "profile_runs",
        sa.Column("assessment_drafted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "assessment_statements",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("level", sa.String(length=10), nullable=True),
        sa.Column("label", sa.String(length=20), nullable=True),
        sa.Column("timing", sa.String(length=200), nullable=True),
        sa.Column("cited_fact_ids", sa.JSON(), nullable=False),
        sa.Column("cites_buyer_context", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("gap_evidence", sa.Text(), nullable=True),
        sa.Column("buyer_context_version", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model_id", sa.String(length=200), nullable=False),
        sa.Column("model_version", sa.String(length=100), nullable=False),
        sa.Column("prompt_id", sa.String(length=50), nullable=False),
        sa.Column("prompt_version", sa.String(length=100), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organisation_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(f"kind IN ({KINDS})", name=op.f("ck_assessment_statements_kind")),
        sa.CheckConstraint(
            "status IN ('ai_draft', 'approved', 'corrected', 'deleted')",
            name=op.f("ck_assessment_statements_status"),
        ),
        sa.CheckConstraint(
            "level IS NULL OR level IN ('low', 'medium', 'high')",
            name=op.f("ck_assessment_statements_level"),
        ),
        sa.CheckConstraint(
            "label IS NULL OR label IN ('strategic', 'preferred', 'transactional')",
            name=op.f("ck_assessment_statements_label"),
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_assessment_statements_organisation_id_organisations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["profile_runs.id"],
            name=op.f("fk_assessment_statements_run_id_profile_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assessment_statements")),
    )
    op.create_index(
        op.f("ix_assessment_statements_organisation_id"),
        "assessment_statements",
        ["organisation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_assessment_statements_run_id"), "assessment_statements", ["run_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_assessment_statements_run_id"), table_name="assessment_statements")
    op.drop_index(
        op.f("ix_assessment_statements_organisation_id"), table_name="assessment_statements"
    )
    op.drop_table("assessment_statements")
    op.drop_column("profile_runs", "assessment_drafted_at")
    op.drop_column("profile_runs", "rejected_statements")

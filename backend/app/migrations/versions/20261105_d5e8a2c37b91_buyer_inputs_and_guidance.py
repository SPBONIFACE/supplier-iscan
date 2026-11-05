"""buyer inputs, the fit kind and the financial guidance of a statement

Revision ID: d5e8a2c37b91
Revises: c3d7e9f14a62
Create Date: 2026-11-05 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d5e8a2c37b91"
down_revision: str | None = "c3d7e9f14a62"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = (
    "'strength', 'weakness', 'opportunity', 'threat', 'risk_indicator', 'evidence_gap', "
    "'procurement_implication', 'relationship_level', 'contract_approach', 'volume_share', "
    "'next_action', 'procurement_priority'"
)
NEW_KINDS = OLD_KINDS.replace("'evidence_gap', ", "'evidence_gap', 'fit', ")
CONSTRAINT = "ck_assessment_statements_kind"


def upgrade() -> None:
    op.drop_constraint(op.f(CONSTRAINT), "assessment_statements", type_="check")
    op.create_check_constraint(op.f(CONSTRAINT), "assessment_statements", f"kind IN ({NEW_KINDS})")
    op.add_column("assessment_statements", sa.Column("guidance", sa.JSON(), nullable=True))
    op.create_table(
        "buyer_inputs",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("field", sa.String(length=100), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organisation_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_buyer_inputs_organisation_id_organisations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["profile_runs.id"],
            name=op.f("fk_buyer_inputs_run_id_profile_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["users.id"], name=op.f("fk_buyer_inputs_updated_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_buyer_inputs")),
        sa.UniqueConstraint("run_id", "field", name=op.f("uq_buyer_inputs_run_field")),
    )
    op.create_index(
        op.f("ix_buyer_inputs_organisation_id"), "buyer_inputs", ["organisation_id"], unique=False
    )
    op.create_index(op.f("ix_buyer_inputs_run_id"), "buyer_inputs", ["run_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_buyer_inputs_run_id"), table_name="buyer_inputs")
    op.drop_index(op.f("ix_buyer_inputs_organisation_id"), table_name="buyer_inputs")
    op.drop_table("buyer_inputs")
    op.drop_column("assessment_statements", "guidance")
    op.execute("DELETE FROM assessment_statements WHERE kind = 'fit'")
    op.drop_constraint(op.f(CONSTRAINT), "assessment_statements", type_="check")
    op.create_check_constraint(op.f(CONSTRAINT), "assessment_statements", f"kind IN ({OLD_KINDS})")

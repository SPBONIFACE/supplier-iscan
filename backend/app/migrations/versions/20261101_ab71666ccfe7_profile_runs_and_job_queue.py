"""Supplier identities, profile runs, the job queue (#13); usage event kind "run".

Revision ID: ab71666ccfe7
Revises: c4e8a1b72d30
Create Date: 2026-11-01 23:44:11.114116
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ab71666ccfe7"
down_revision: str | None = "c4e8a1b72d30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_usage_events_kind"), "usage_events", type_="check")
    op.create_check_constraint(
        op.f("ck_usage_events_kind"), "usage_events", "kind IN ('login', 'login_failed', 'run')"
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(length=10), nullable=False),
        sa.Column("locked_by", sa.String(length=100), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('queued', 'running', 'done', 'failed')", name=op.f("ck_jobs_state")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    )
    op.create_index(
        "ix_jobs_state_lease_expires_at", "jobs", ["state", "lease_expires_at"], unique=False
    )
    op.create_table(
        "supplier_identities",
        sa.Column("legal_name", sa.String(length=300), nullable=False),
        sa.Column("website", sa.String(length=2000), nullable=True),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("sector", sa.String(length=200), nullable=True),
        sa.Column("registry_ids", sa.JSON(), nullable=False),
        sa.Column("natural_person", sa.Boolean(), nullable=False),
        sa.Column("confirmed_by", sa.Uuid(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organisation_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["confirmed_by"], ["users.id"], name=op.f("fk_supplier_identities_confirmed_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_supplier_identities_organisation_id_organisations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_supplier_identities")),
    )
    op.create_index(
        op.f("ix_supplier_identities_organisation_id"),
        "supplier_identities",
        ["organisation_id"],
        unique=False,
    )
    op.create_table(
        "profile_runs",
        sa.Column("identity_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("stage", sa.String(length=20), nullable=False),
        sa.Column("stop_requested", sa.Boolean(), nullable=False),
        sa.Column("counts_against_quota", sa.Boolean(), nullable=False),
        sa.Column("pause_dependency", sa.String(length=30), nullable=True),
        sa.Column("pause_reason", sa.String(length=300), nullable=True),
        sa.Column("error", sa.String(length=300), nullable=True),
        sa.Column("profile_definition_hash", sa.String(length=100), nullable=True),
        sa.Column("prompt_set_hash", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organisation_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "pause_dependency IS NULL OR pause_dependency IN ('structuring_provider',"
            " 'retrieval_provider', 'llm_provider', 'registry', 'website', 'database', 'network')",
            name=op.f("ck_profile_runs_pause_dependency"),
        ),
        sa.CheckConstraint(
            "stage IN ('identity', 'collection', 'extraction', 'assessment')",
            name=op.f("ck_profile_runs_stage"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'paused', 'stopped', 'failed',"
            " 'insufficient_sources', 'partial', 'completed')",
            name=op.f("ck_profile_runs_status"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_profile_runs_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["identity_id"],
            ["supplier_identities.id"],
            name=op.f("fk_profile_runs_identity_id_supplier_identities"),
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_profile_runs_organisation_id_organisations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_profile_runs")),
    )
    op.create_index(
        op.f("ix_profile_runs_organisation_id"), "profile_runs", ["organisation_id"], unique=False
    )
    op.create_index(
        "ix_profile_runs_organisation_id_created_at",
        "profile_runs",
        ["organisation_id", "created_at"],
        unique=False,
    )
    op.create_foreign_key(
        op.f("fk_llm_usage_run_id_profile_runs"),
        "llm_usage",
        "profile_runs",
        ["run_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_llm_usage_run_id_profile_runs"), "llm_usage", type_="foreignkey")
    op.drop_index("ix_profile_runs_organisation_id_created_at", table_name="profile_runs")
    op.drop_index(op.f("ix_profile_runs_organisation_id"), table_name="profile_runs")
    op.drop_table("profile_runs")
    op.drop_index(op.f("ix_supplier_identities_organisation_id"), table_name="supplier_identities")
    op.drop_table("supplier_identities")
    op.drop_index("ix_jobs_state_lease_expires_at", table_name="jobs")
    op.drop_table("jobs")
    op.execute("DELETE FROM usage_events WHERE kind = 'run'")
    op.drop_constraint(op.f("ck_usage_events_kind"), "usage_events", type_="check")
    op.create_check_constraint(
        op.f("ck_usage_events_kind"), "usage_events", "kind IN ('login', 'login_failed')"
    )

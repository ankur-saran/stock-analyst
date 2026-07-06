"""Initial schema: 9 tables with RLS policies and audit-log append-only enforcement.

Revision ID: 001
Revises:
Create Date: 2026-07-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Tables that carry a tenant_id column and must be isolated via RLS.
# agent_audit_log is included even though its tenant_id has no FK.
_RLS_TABLES = [
    "users",
    "coverages",
    "documents",
    "research_outputs",
    "kpi_timeseries",
    "task_queue",
    "agent_audit_log",
]


def upgrade() -> None:
    # ── 1. Enum types ─────────────────────────────────────────────────────────
    op.execute(sa.text(
        "CREATE TYPE plan_enum AS ENUM ('starter', 'professional', 'enterprise')"
    ))
    op.execute(sa.text(
        "CREATE TYPE user_role_enum AS ENUM ('viewer', 'analyst', 'senior_analyst', 'admin')"
    ))
    op.execute(sa.text(
        "CREATE TYPE coverage_status_enum AS ENUM ('setup', 'active', 'archived')"
    ))
    op.execute(sa.text(
        "CREATE TYPE ingest_status_enum AS ENUM "
        "('pending', 'indexing', 'indexed', 'failed', 'review_needed')"
    ))
    op.execute(sa.text(
        "CREATE TYPE output_type_enum AS ENUM "
        "('industry_primer', 'lynch_pitch', 'munger_invert', 'quarterly_update', 'kpi_snapshot')"
    ))
    op.execute(sa.text(
        "CREATE TYPE enforcer_status_enum AS ENUM ('pending', 'approved', 'partial', 'failed')"
    ))
    op.execute(sa.text(
        "CREATE TYPE period_type_enum AS ENUM ('annual', 'quarterly')"
    ))
    op.execute(sa.text(
        "CREATE TYPE task_status_enum AS ENUM "
        "('queued', 'running', 'completed', 'failed', 'cancelled')"
    ))

    # ── 2. tenants ────────────────────────────────────────────────────────────
    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "plan",
            sa.Enum("starter", "professional", "enterprise",
                    name="plan_enum", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "settings",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # ── 3. users ──────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column(
            "role",
            sa.Enum("viewer", "analyst", "senior_analyst", "admin",
                    name="user_role_enum", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    # ── 4. industries ─────────────────────────────────────────────────────────
    op.create_table(
        "industries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("primer_content", sa.Text(), nullable=True),
        sa.Column(
            "primer_citations",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("word_count", sa.Integer(), nullable=True),
        sa.Column("llm_used", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("name", name="uq_industries_name"),
    )

    # ── 5. coverages ──────────────────────────────────────────────────────────
    op.create_table(
        "coverages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("company_name", sa.String(500), nullable=False),
        sa.Column("exchange", sa.String(50), nullable=False),
        sa.Column(
            "industry_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("industries.id"),
            nullable=True,
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("setup", "active", "archived",
                    name="coverage_status_enum", create_type=False),
            server_default=sa.text("'setup'"),
            nullable=False,
        ),
        sa.Column(
            "document_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("last_updated", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id", "ticker", "exchange",
            name="uq_coverage_tenant_ticker_exchange",
        ),
    )

    # ── 6. documents ──────────────────────────────────────────────────────────
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "coverage_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("coverages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("file_name", sa.String(500), nullable=False),
        sa.Column("filing_type", sa.String(50), nullable=False),
        sa.Column("period", sa.String(50), nullable=False),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("source_url", sa.String(1000), nullable=True),
        sa.Column("storage_path", sa.String(1000), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column(
            "chunk_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column(
            "ingest_status",
            sa.Enum("pending", "indexing", "indexed", "failed", "review_needed",
                    name="ingest_status_enum", create_type=False),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("file_hash", sa.String(64), nullable=True),
    )

    # ── 7. research_outputs ───────────────────────────────────────────────────
    op.create_table(
        "research_outputs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "coverage_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("coverages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "output_type",
            sa.Enum("industry_primer", "lynch_pitch", "munger_invert",
                    "quarterly_update", "kpi_snapshot",
                    name="output_type_enum", create_type=False),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "citations",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("citation_coverage_pct", sa.Float(), nullable=True),
        sa.Column(
            "approved_by_enforcer",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "enforcer_status",
            sa.Enum("pending", "approved", "partial", "failed",
                    name="enforcer_status_enum", create_type=False),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("llm_used", sa.String(100), nullable=True),
        sa.Column(
            "tokens_used",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "approved_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
    )

    # ── 8. kpi_timeseries ─────────────────────────────────────────────────────
    op.create_table(
        "kpi_timeseries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "coverage_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("coverages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kpi_name", sa.String(100), nullable=False),
        sa.Column("period", sa.String(50), nullable=False),
        sa.Column(
            "period_type",
            sa.Enum("annual", "quarterly",
                    name="period_type_enum", create_type=False),
            nullable=False,
        ),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(50), nullable=False),
        sa.Column("citation", postgresql.JSONB(), nullable=False),
        sa.Column(
            "is_restated",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("restatement_note", sa.Text(), nullable=True),
        sa.Column(
            "extracted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # ── 9. agent_audit_log ────────────────────────────────────────────────────
    # tenant_id has NO FK — log entries survive tenant deletion.
    op.create_table(
        "agent_audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("coverage_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agent_name", sa.String(100), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=True),
        sa.Column("output_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("llm_used", sa.String(100), nullable=True),
        sa.Column(
            "tokens_used",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )

    # ── 10. task_queue ────────────────────────────────────────────────────────
    op.create_table(
        "task_queue",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "coverage_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("coverages.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("task_type", sa.String(100), nullable=False),
        sa.Column(
            "status",
            sa.Enum("queued", "running", "completed", "failed", "cancelled",
                    name="task_status_enum", create_type=False),
            server_default=sa.text("'queued'"),
            nullable=False,
        ),
        sa.Column("celery_task_id", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=True),
    )

    # ── 11. Row-Level Security ────────────────────────────────────────────────
    for table in _RLS_TABLES:
        op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        op.execute(sa.text(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
        ))

    # ── 12. Append-only enforcement for agent_audit_log ───────────────────────
    op.execute(sa.text("REVOKE DELETE ON agent_audit_log FROM PUBLIC"))
    op.execute(sa.text("REVOKE UPDATE ON agent_audit_log FROM PUBLIC"))


def downgrade() -> None:
    # ── Restore write privileges on audit log ─────────────────────────────────
    op.execute(sa.text("GRANT DELETE ON agent_audit_log TO PUBLIC"))
    op.execute(sa.text("GRANT UPDATE ON agent_audit_log TO PUBLIC"))

    # ── Drop RLS policies and disable RLS (reverse of enable order) ───────────
    for table in reversed(_RLS_TABLES):
        op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation ON {table}"))
        op.execute(sa.text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))

    # ── Drop tables in reverse FK order ───────────────────────────────────────
    op.drop_table("task_queue")
    op.drop_table("agent_audit_log")
    op.drop_table("kpi_timeseries")
    op.drop_table("research_outputs")
    op.drop_table("documents")
    op.drop_table("coverages")
    op.drop_table("industries")
    op.drop_table("users")
    op.drop_table("tenants")

    # ── Drop enum types (reverse creation order) ──────────────────────────────
    op.execute(sa.text("DROP TYPE IF EXISTS task_status_enum"))
    op.execute(sa.text("DROP TYPE IF EXISTS period_type_enum"))
    op.execute(sa.text("DROP TYPE IF EXISTS enforcer_status_enum"))
    op.execute(sa.text("DROP TYPE IF EXISTS output_type_enum"))
    op.execute(sa.text("DROP TYPE IF EXISTS ingest_status_enum"))
    op.execute(sa.text("DROP TYPE IF EXISTS coverage_status_enum"))
    op.execute(sa.text("DROP TYPE IF EXISTS user_role_enum"))
    op.execute(sa.text("DROP TYPE IF EXISTS plan_enum"))

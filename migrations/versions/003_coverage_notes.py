"""Add coverage_notes table for the analyst notes editor.

Revision ID: 003
Revises: 002
Create Date: 2026-07-29

One row per coverage (unique on coverage_id), upserted on every autosave
from the Tiptap editor. Carries a tenant_id column of its own (unlike
kpi_timeseries) so it can follow the same RLS pattern as every other
tenant-scoped table rather than requiring a join through coverages.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "coverage_notes",
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
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("coverage_id", name="uq_coverage_notes_coverage_id"),
    )

    op.execute(sa.text("ALTER TABLE coverage_notes ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text(
        "CREATE POLICY tenant_isolation ON coverage_notes "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    ))


def downgrade() -> None:
    op.execute(sa.text("DROP POLICY IF EXISTS tenant_isolation ON coverage_notes"))
    op.execute(sa.text("ALTER TABLE coverage_notes DISABLE ROW LEVEL SECURITY"))
    op.drop_table("coverage_notes")

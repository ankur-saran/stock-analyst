"""Add research_outputs.output_metadata for cross-quarter tracking data.

Revision ID: 002
Revises: 001
Create Date: 2026-07-24

Earnings Monitor needs somewhere to accumulate a per-quarter management
credibility verdict that isn't part of the citation-checked `content` prose
-- mirrors the existing `agent_audit_log.metadata` JSONB column rather than
inventing a new pattern.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "research_outputs",
        sa.Column(
            "output_metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("research_outputs", "output_metadata")

"""persist camera onboarding diagnostics

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-19
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cameras",
        sa.Column("probe_status", sa.String(20), nullable=False, server_default="untested"),
    )
    op.add_column("cameras", sa.Column("last_probe_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("cameras", sa.Column("probe_details", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("cameras", "probe_details")
    op.drop_column("cameras", "last_probe_at")
    op.drop_column("cameras", "probe_status")

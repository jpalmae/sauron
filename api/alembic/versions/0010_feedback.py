"""event feedback + labeled dataset export (model improvement loop)

Revision ID: 0010
Create Date: 2026-08-10
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "analytics_events",
        sa.Column("feedback", sa.String(20), nullable=True),  # correct | false_positive
    )


def downgrade() -> None:
    op.drop_column("analytics_events", "feedback")

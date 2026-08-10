"""notification channels (webhook/email/telegram)

Revision ID: 0008
Create Date: 2026-08-10
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_channels",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),  # webhook | email | telegram
        sa.Column("config", sa.JSON, nullable=False),
        sa.Column("min_priority", sa.String(20), server_default="critical"),
        sa.Column("camera_id", sa.Uuid, sa.ForeignKey("cameras.id"), nullable=True),
        sa.Column("enabled", sa.Boolean, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("notification_channels")

"""corridors table (travel-time ReID)

Revision ID: 0009
Create Date: 2026-08-10
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "corridors",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("from_camera_id", sa.Uuid, sa.ForeignKey("cameras.id"), nullable=False),
        sa.Column("to_camera_id", sa.Uuid, sa.ForeignKey("cameras.id"), nullable=False),
        sa.Column("distance_m", sa.Float, nullable=False),
        sa.Column("max_travel_s", sa.Integer, server_default="7200"),
        sa.Column("enabled", sa.Boolean, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("corridors")

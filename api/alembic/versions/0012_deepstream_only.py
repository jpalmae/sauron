"""replace legacy detector settings with a DeepStream analytics profile

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-16
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cameras",
        sa.Column("analytics_profile", sa.String(20), nullable=False, server_default="traffic"),
    )
    op.execute(
        "UPDATE cameras SET analytics_profile = 'people' "
        "WHERE lower(coalesce(detector, '')) LIKE '%pose%' "
        "OR lower(coalesce(model, '')) LIKE '%pose%'"
    )
    op.drop_column("cameras", "detector")
    op.drop_column("cameras", "model")
    op.drop_table("engine_config")


def downgrade() -> None:
    op.create_table(
        "engine_config",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("defaults", JSONB, nullable=False),
        sa.Column("target_fps", sa.Integer, nullable=False, server_default="5"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("cameras", sa.Column("detector", sa.String(30), nullable=True))
    op.add_column("cameras", sa.Column("model", sa.String(40), nullable=True))
    op.execute(
        "UPDATE cameras SET detector = CASE analytics_profile "
        "WHEN 'people' THEN 'pose_objects' ELSE 'tensorrt' END"
    )
    op.drop_column("cameras", "analytics_profile")

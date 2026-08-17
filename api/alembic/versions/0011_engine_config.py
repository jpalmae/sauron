"""engine_config singleton: GUI-editable inference defaults

Revision ID: 0011
Create Date: 2026-08-08
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "engine_config",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("defaults", JSONB, nullable=False),
        sa.Column("target_fps", sa.Integer, nullable=False, server_default="5"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("INSERT INTO engine_config (id, defaults, target_fps) VALUES (1, '{}'::jsonb, 5)")


def downgrade() -> None:
    op.drop_table("engine_config")

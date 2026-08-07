"""widen cameras.rtsp_url to 1024 (resolved HLS manifests are long)

Revision ID: 0005
Create Date: 2026-08-07
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("cameras", "rtsp_url", type_=sa.Text)


def downgrade() -> None:
    op.alter_column("cameras", "rtsp_url", type_=sa.String(255))

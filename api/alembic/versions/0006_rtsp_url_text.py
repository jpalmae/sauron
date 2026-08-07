"""cameras.rtsp_url -> TEXT (HLS manifests exceed 1024 chars)

Revision ID: 0006
Create Date: 2026-08-07
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("cameras", "rtsp_url", type_=sa.Text)


def downgrade() -> None:
    op.alter_column("cameras", "rtsp_url", type_=sa.String(1024))

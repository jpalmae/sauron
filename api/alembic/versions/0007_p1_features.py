"""P1 features: GIS coords, per-camera detector/model, push subs, pgvector embeddings

Revision ID: 0007
Create Date: 2026-08-08
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # GIS (map view)
    op.add_column("cameras", sa.Column("latitude", sa.Float, nullable=True))
    op.add_column("cameras", sa.Column("longitude", sa.Float, nullable=True))
    # Per-camera model rollout (OTA model management)
    op.add_column("cameras", sa.Column("detector", sa.String(30), nullable=True))
    op.add_column("cameras", sa.Column("model", sa.String(40), nullable=True))

    # Web Push subscriptions (PWA notifications)
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("endpoint", sa.Text, unique=True),
        sa.Column("keys", sa.JSON),
        sa.Column("user_email", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # CLIP embeddings for natural-language evidence search
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("ALTER TABLE analytics_events ADD COLUMN IF NOT EXISTS embedding vector(512)")


def downgrade() -> None:
    op.execute("ALTER TABLE analytics_events DROP COLUMN IF EXISTS embedding")
    op.drop_table("push_subscriptions")
    op.drop_column("cameras", "model")
    op.drop_column("cameras", "detector")
    op.drop_column("cameras", "longitude")
    op.drop_column("cameras", "latitude")

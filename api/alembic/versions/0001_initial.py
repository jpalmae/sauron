"""initial schema + timescaledb hypertables

Revision ID: 0001
Create Date: 2026-08-06
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import context, op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

JSON_TYPE = JSONB if context.get_context().dialect.name == "postgresql" else sa.JSON


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

    op.create_table(
        "cameras",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("stream_id", sa.String(100), nullable=False, unique=True),
        sa.Column("rtsp_url", sa.String(255), server_default=""),
        sa.Column("roi_config", JSON_TYPE, nullable=True),
        sa.Column("is_active", sa.Boolean, server_default=sa.true()),
    )
    op.create_index("ix_cameras_stream_id", "cameras", ["stream_id"], unique=True)

    op.create_table(
        "analytics_events",
        sa.Column("timestamp", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("event_id", sa.Uuid, unique=True),
        sa.Column("camera_id", sa.Uuid, sa.ForeignKey("cameras.id"), index=True),
        sa.Column("event_type", sa.String(50), index=True),
        sa.Column("priority", sa.String(20), server_default="info"),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("snapshot_key", sa.String(255), nullable=True),
        sa.Column("clip_url", sa.String(255), nullable=True),
        sa.Column("rule_id", sa.String(100), server_default=""),
        sa.Column("object_id", sa.Integer, nullable=True),
        sa.Column("metadata", JSON_TYPE, nullable=True),
    )
    op.create_index("ix_analytics_events_camera_id", "analytics_events", ["camera_id"])
    op.create_index("ix_analytics_events_event_type", "analytics_events", ["event_type"])

    op.create_table(
        "hourly_kpis",
        sa.Column("bucket", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("camera_id", sa.Uuid, sa.ForeignKey("cameras.id"), primary_key=True),
        sa.Column("vehicle_class", sa.String(50), primary_key=True),
        sa.Column("total_count", sa.Integer, server_default="0"),
        sa.Column("avg_speed_kmh", sa.Float, nullable=True),
        sa.Column("congestion_minutes", sa.Integer, server_default="0"),
        sa.Column("notes", sa.Text, nullable=True),
    )

    op.execute(
        "SELECT create_hypertable('analytics_events', 'timestamp', if_not_exists => TRUE)"
    )
    op.execute("SELECT create_hypertable('hourly_kpis', 'bucket', if_not_exists => TRUE)")


def downgrade() -> None:
    op.drop_table("hourly_kpis")
    op.drop_table("analytics_events")
    op.drop_table("cameras")

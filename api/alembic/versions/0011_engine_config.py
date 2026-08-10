"""engine_config singleton: GUI-editable inference defaults

Revision ID: 0007
Create Date: 2026-08-08
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

DEFAULTS_SEED: dict = {
    "confidence_threshold": 0.4,
    "nms_threshold": 0.45,
    "input_size": [640, 640],
    "detector": {"backend": "pose_objects"},
    "model": "yolov8n",
    "pose_onnx_path": "models/yolov8n-pose.onnx",
    "objects_onnx_path": "models/yolov8n.onnx",
    "classes": {
        "2": "car", "3": "motorcycle", "5": "bus", "7": "truck",
        "62": "chair", "63": "couch",
    },
    "tracker": {
        "high_thresh": 0.4, "low_thresh": 0.1, "match_thresh": 0.8,
        "max_time_lost": 30, "history_size": 60,
    },
    "capture": {"queue_size": 2, "use_gstreamer": False},
    "clips": {"enabled": True, "preroll_seconds": 6, "clip_fps": 10},
}


def upgrade() -> None:
    op.create_table(
        "engine_config",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("defaults", JSONB, nullable=False),
        sa.Column("target_fps", sa.Integer, nullable=False, server_default="5"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "INSERT INTO engine_config (id, defaults, target_fps) VALUES (1, '"
        + json.dumps(DEFAULTS_SEED) + "'::jsonb, 5)"
    )


def downgrade() -> None:
    op.drop_table("engine_config")

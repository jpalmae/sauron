"""composite PK (timestamp, event_id) so multiple events per instant are allowed

Revision ID: 0004
Create Date: 2026-08-07
"""

from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Several rules (OCCUPANCY, CHAIR_OCCUPANCY, GROUPING, ...) can emit events
    # in the same frame (same timestamp). The old single-column PK (timestamp)
    # rejected all but the first. Switch to a composite PK so every event row
    # is unique by (timestamp, event_id). Timescale requires the partitioning
    # column (timestamp) in the PK, which is preserved.
    op.execute(
        "ALTER TABLE analytics_events DROP CONSTRAINT IF EXISTS analytics_events_pkey"
    )
    op.execute(
        "ALTER TABLE analytics_events DROP CONSTRAINT IF EXISTS "
        "analytics_events_event_id_timestamp_key"
    )
    op.execute(
        "ALTER TABLE analytics_events ADD CONSTRAINT analytics_events_pkey "
        "PRIMARY KEY (timestamp, event_id)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE analytics_events DROP CONSTRAINT analytics_events_pkey")
    op.execute(
        "ALTER TABLE analytics_events ADD CONSTRAINT analytics_events_pkey "
        "PRIMARY KEY (timestamp)"
    )

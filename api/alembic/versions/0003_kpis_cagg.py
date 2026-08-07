"""vehicle_class column + continuous aggregate for KPIs

Revision ID: 0003
Create Date: 2026-08-07
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "analytics_events", sa.Column("vehicle_class", sa.String(50), nullable=True)
    )
    op.create_index("ix_analytics_events_vehicle_class", "analytics_events", ["vehicle_class"])
    op.execute(
        "UPDATE analytics_events SET vehicle_class = metadata->>'vehicle_class' "
        "WHERE vehicle_class IS NULL AND metadata->>'vehicle_class' IS NOT NULL"
    )
    op.execute(
        """
        CREATE MATERIALIZED VIEW analytics_kpis_hourly
        WITH (timescaledb.continuous) AS
        SELECT time_bucket('1 hour', timestamp) AS bucket,
               camera_id,
               vehicle_class,
               count(CASE WHEN event_type = 'LINE_CROSSING' THEN 1 END) AS total_count,
               avg(CASE WHEN event_type = 'LINE_CROSSING'
                        THEN (metadata->>'speed_kmh')::float END) AS avg_speed_kmh,
               sum(CASE WHEN event_type = 'CONGESTION'
                        THEN coalesce((metadata->>'sustained_seconds')::float, 0) END) / 60.0
                   AS congestion_minutes
        FROM analytics_events
        GROUP BY bucket, camera_id, vehicle_class
        WITH NO DATA
        """
    )
    op.execute(
        """
        SELECT add_continuous_aggregate_policy('analytics_kpis_hourly',
            start_offset => INTERVAL '3 hours',
            end_offset => INTERVAL '10 minutes',
            schedule_interval => INTERVAL '30 minutes')
        """
    )
    # backfill existing data immediately (policy only covers the trailing window).
    # TimescaleDB: refresh_continuous_aggregate() cannot run inside a transaction block,
    # so commit the migration txn first, then run the refresh in autocommit.
    op.execute("COMMIT")
    op.execute("CALL refresh_continuous_aggregate('analytics_kpis_hourly', NULL, NULL)")


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS analytics_kpis_hourly")
    op.drop_index("ix_analytics_events_vehicle_class", "analytics_events")
    op.drop_column("analytics_events", "vehicle_class")

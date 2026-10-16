"""Record website visits separately from searches and GPS events."""

from alembic import op

revision = "0042_page_view_analytics"
down_revision = "0041_poi_knowledge_more_sg_2"
branch_labels = None
depends_on = None

_TYPES = "'search', 'location_ping', 'poi_impression', 'poi_dwell', 'poi_click', 'navigation_start', 'review'"


def upgrade() -> None:
    op.drop_constraint("ingestion_events_event_type_check", "ingestion_events", type_="check")
    op.create_check_constraint("ingestion_events_event_type_check", "ingestion_events",
                               f"event_type IN ({_TYPES}, 'page_view')")
    op.execute("CREATE INDEX ix_ingestion_page_views_received ON ingestion_events (received_at) WHERE event_type = 'page_view'")


def downgrade() -> None:
    # Never erase recorded visits merely to restore an older event constraint.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM ingestion_events WHERE event_type = 'page_view') THEN
                RAISE EXCEPTION 'Retain page-view history: archive it explicitly before downgrading';
            END IF;
        END $$;
    """)
    op.drop_index("ix_ingestion_page_views_received", table_name="ingestion_events")
    op.drop_constraint("ingestion_events_event_type_check", "ingestion_events", type_="check")
    op.create_check_constraint("ingestion_events_event_type_check", "ingestion_events",
                               f"event_type IN ({_TYPES})")

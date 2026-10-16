"""Analytics SQL against isolated temporary tables; never modify application data.

Set ANALYTICS_TEST_DATABASE_URL to a disposable/local PostgreSQL connection.
"""
import os
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app import admin

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    not os.getenv("ANALYTICS_TEST_DATABASE_URL"), reason="set ANALYTICS_TEST_DATABASE_URL",
)]


@pytest.fixture
def connection():
    with psycopg.connect(os.environ["ANALYTICS_TEST_DATABASE_URL"], row_factory=dict_row) as conn:
        conn.execute("""CREATE TEMP TABLE ingestion_events (
            id uuid PRIMARY KEY, session_id uuid NOT NULL, event_type text NOT NULL,
            received_at timestamptz NOT NULL, metadata jsonb NOT NULL DEFAULT '{}'::jsonb
        ) ON COMMIT DROP""")
        yield conn
        conn.rollback()


def add(conn, browser, visit, device, days_ago=0, event_type="page_view"):
    conn.execute("""
        INSERT INTO ingestion_events VALUES (%s, %s, %s,
            ((NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date - %s + INTERVAL '1 hour')
                AT TIME ZONE 'Asia/Ho_Chi_Minh', %s)
    """, (uuid4(), browser, event_type, days_ago, Jsonb({"visit_id": visit, "device": device})))


@pytest.mark.parametrize("days", [7, 14, 30])
def test_views_visits_browsers_devices_and_local_dates(connection, days):
    a, b, c, old, unrelated = [uuid4() for _ in range(5)]
    add(connection, a, "tab-1", "mobile")
    add(connection, a, "tab-1", "mobile")  # reload: another view, same visit
    add(connection, a, "tab-2", "desktop")
    add(connection, b, "tab-3", "mobile", days_ago=1)
    add(connection, c, "tab-4", "unexpected")
    add(connection, old, "tab-5", "desktop", days_ago=31)
    add(connection, unrelated, "tab-x", "mobile", event_type="search")
    add(connection, unrelated, "tab-x", "mobile", event_type="location_ping")

    result = admin._traffic_overview(connection, days)
    assert result["totalViews"] == 6
    assert result["viewsToday"] == 4
    assert result["viewsPeriod"] == 5
    assert result["visitsPeriod"] == 4
    assert result["browsersPeriod"] == 3
    assert {d["device"]: d["views"] for d in result["devices"]} == {
        "mobile": 3, "desktop": 1, "unknown": 1,
    }
    assert result["trackingSince"]
    daily = admin._daily_activity(connection, days)
    assert len(daily) == days
    assert daily[-1]["page_views"] == 4
    assert daily[-1]["visits"] == 3
    assert daily[-1]["visitors"] == 2
    assert daily[-1]["searches"] == 1
    assert daily[-2]["page_views"] == 1
    assert all(day["page_views"] == 0 for day in daily[:-2])
    assert sum(day["page_views"] for day in daily) == result["viewsPeriod"]


def test_empty_traffic_does_not_infer_visits_from_gps_or_searches(connection):
    add(connection, uuid4(), "tab", "mobile", event_type="location_ping")
    result = admin._traffic_overview(connection, 7)
    assert result == {
        "totalViews": 0, "viewsToday": 0, "viewsPeriod": 0,
        "visitsPeriod": 0, "browsersPeriod": 0, "trackingSince": None, "devices": [],
    }


def test_same_visit_id_in_different_browsers_is_not_merged(connection):
    add(connection, uuid4(), "cloned-tab", "mobile")
    add(connection, uuid4(), "cloned-tab", "mobile")
    assert admin._traffic_overview(connection, 7)["visitsPeriod"] == 2


def test_midnight_boundary_is_vietnam_midnight_not_database_timezone(connection):
    connection.execute("SET LOCAL TIME ZONE 'UTC'")
    browser = uuid4()
    for offset in (-1, 0):
        connection.execute("""
            INSERT INTO ingestion_events VALUES (%s, %s, 'page_view',
                ((NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date::timestamp
                    AT TIME ZONE 'Asia/Ho_Chi_Minh') + %s * INTERVAL '1 second',
                '{}'::jsonb)
        """, (uuid4(), browser, offset))
    result = admin._traffic_overview(connection, 7)
    assert result["viewsToday"] == 1
    assert result["viewsPeriod"] == 2
    days = admin._daily_activity(connection, 7)
    assert days[-1]["page_views"] == 1
    assert days[-2]["page_views"] == 1


def test_migration_accepts_views_rejects_unknown_types_and_preserves_history(monkeypatch):
    import importlib.util
    from pathlib import Path
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = Path(__file__).parents[2] / "migrations/versions/0042_page_view_analytics.py"
    spec = importlib.util.spec_from_file_location("traffic_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    url = os.environ["ANALYTICS_TEST_DATABASE_URL"].replace("postgresql://", "postgresql+psycopg://", 1)
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn, conn.begin():
            conn.execute(sa.text("""CREATE TEMP TABLE ingestion_events (
                event_type text, received_at timestamptz DEFAULT NOW(),
                CONSTRAINT ingestion_events_event_type_check CHECK (event_type IN ('search'))
            ) ON COMMIT DROP"""))
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(conn)))
            migration.upgrade()
            conn.execute(sa.text("INSERT INTO ingestion_events (event_type) VALUES ('page_view')"))
            with pytest.raises(sa.exc.IntegrityError), conn.begin_nested():
                conn.execute(sa.text("INSERT INTO ingestion_events (event_type) VALUES ('unknown')"))
            with pytest.raises(sa.exc.DBAPIError), conn.begin_nested():
                migration.downgrade()
            assert conn.execute(sa.text("SELECT count(*) FROM ingestion_events")).scalar() == 1
            # Remove test-only data to exercise the empty-table rollback path.
            conn.execute(sa.text("DELETE FROM ingestion_events"))
            migration.downgrade()
            with pytest.raises(sa.exc.IntegrityError), conn.begin_nested():
                conn.execute(sa.text("INSERT INTO ingestion_events (event_type) VALUES ('page_view')"))
    finally:
        engine.dispose()

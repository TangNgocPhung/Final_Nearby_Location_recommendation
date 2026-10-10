"""Xe buýt: tuyến, trạm và thứ tự trạm trên từng lượt — nhập từ OSM.

Revision ID: 0036_bus_transit
Revises: 0035_department_store_not_mall

Mỗi ``bus_routes`` là MỘT LƯỢT (relation ``route=bus`` của OSM): tuyến 14 có hai
dòng, lượt đi Miền Đông → Miền Tây và lượt về. Hai lượt cùng ``network`` +
``ref`` gộp thành một tuyến lúc đọc (xem ``app/bus.py``), không gộp lúc lưu —
thứ tự trạm, lộ trình và độ dài mỗi lượt khác nhau.

Giờ chạy (``opening_hours``), giãn cách (``interval``) và giá vé (``charge``)
giữ CHUỖI THÔ của OSM; phân tích lúc đọc để sửa parser không phải nhập lại.

``bus_stops`` tách khỏi ``pois``: 6.700 trạm, gần sát trần ``OSM_MAX_POIS`` của
bảng POI, và trạm xe buýt không phải nơi để "gợi ý đi chơi".
"""

from alembic import op

revision = "0036_bus_transit"
down_revision = "0035_department_store_not_mall"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE bus_routes (
            id BIGINT PRIMARY KEY,
            ref TEXT NOT NULL,
            name TEXT NOT NULL,
            origin TEXT,
            destination TEXT,
            via TEXT,
            network TEXT,
            operator TEXT,
            opening_hours TEXT,
            interval TEXT,
            charge TEXT,
            duration TEXT,
            colour TEXT,
            roundtrip BOOLEAN NOT NULL DEFAULT FALSE,
            path GEOGRAPHY(MULTILINESTRING, 4326),
            length_meters DOUBLE PRECISION,
            streets JSONB NOT NULL DEFAULT '[]'::jsonb,
            imported_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX bus_routes_ref_idx ON bus_routes (ref)")
    op.execute(
        """
        CREATE TABLE bus_stops (
            id BIGINT PRIMARY KEY,
            name TEXT NOT NULL,
            location GEOGRAPHY(POINT, 4326) NOT NULL,
            shelter BOOLEAN,
            bench BOOLEAN,
            tags JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )
    op.execute("CREATE INDEX bus_stops_location_idx ON bus_stops USING GIST (location)")
    op.execute(
        """
        CREATE TABLE bus_route_stops (
            route_id BIGINT NOT NULL REFERENCES bus_routes (id) ON DELETE CASCADE,
            seq INTEGER NOT NULL,
            stop_id BIGINT NOT NULL REFERENCES bus_stops (id) ON DELETE CASCADE,
            role TEXT NOT NULL DEFAULT 'platform',
            distance_meters DOUBLE PRECISION,
            PRIMARY KEY (route_id, seq)
        )
        """
    )
    op.execute("CREATE INDEX bus_route_stops_stop_idx ON bus_route_stops (stop_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS bus_route_stops")
    op.execute("DROP TABLE IF EXISTS bus_stops")
    op.execute("DROP TABLE IF EXISTS bus_routes")

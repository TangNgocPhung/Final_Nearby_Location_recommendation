"""Bãi xe & trạm sạc: thông tin gửi xe có cấu trúc + giá do người dùng báo.

Revision ID: 0024_parking_facilities
Revises: 0023_phu_tho_hoa_bot_day_thep

`parking_facilities` — một dòng cho mỗi POI bãi xe/trạm sạc, tách từ thẻ OSM
gốc (`poi_source_records.raw_payload`) hoặc từ Open Charge Map: loại xe phục
vụ, giá đã chuẩn hoá, sức chứa, cổng sạc. Dựng lại được bất cứ lúc nào bằng
`app.parking.refresh_facilities` — bảng này là dữ liệu DẪN XUẤT, không phải
nguồn sự thật.

`parking_reports` — giá/giờ mở cửa do người dùng báo (crowdsource). Đo được
thật (Overpass, bbox TP.HCM, 2026-09-25): chỉ 8/824 bãi xe trên OSM có ghi giá,
6/824 có giờ mở cửa — không có nguồn dữ liệu mở nào khác cho giá gửi xe ở
Việt Nam, nên người dùng là nguồn duy nhất để dữ liệu dày lên theo thời gian.
Mỗi phiên chỉ được báo một lần / bãi / loại xe / ngày (chặn spam đơn giản).
"""

from __future__ import annotations

from alembic import op

revision = "0024_parking_facilities"
down_revision = "0023_phu_tho_hoa_bot_day_thep"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE parking_facilities (
            poi_id UUID PRIMARY KEY REFERENCES pois(id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK (kind IN ('parking', 'charging_station')),
            -- Tri-state: 'yes' | 'no' | 'unknown' — OSM thường không ghi rõ loại
            -- xe, "không biết" khác hẳn "không nhận".
            motorbike TEXT NOT NULL DEFAULT 'unknown' CHECK (motorbike IN ('yes', 'no', 'unknown')),
            car TEXT NOT NULL DEFAULT 'unknown' CHECK (car IN ('yes', 'no', 'unknown')),
            bicycle TEXT NOT NULL DEFAULT 'unknown' CHECK (bicycle IN ('yes', 'no', 'unknown')),
            ev_charging BOOLEAN NOT NULL DEFAULT false,
            fee TEXT NOT NULL DEFAULT 'unknown' CHECK (fee IN ('yes', 'no', 'unknown')),
            price_raw TEXT,
            -- [{vehicle, amountVnd, unit, unitAssumed}] — xem app/parking_tags.parse_price
            prices JSONB NOT NULL DEFAULT '[]'::jsonb,
            capacity INTEGER CHECK (capacity IS NULL OR capacity >= 0),
            parking_type TEXT,
            access TEXT,
            operator TEXT,
            -- [{type, count, powerKw}] cho trạm sạc
            sockets JSONB NOT NULL DEFAULT '[]'::jsonb,
            source TEXT NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX parking_facilities_kind_idx ON parking_facilities (kind)")

    op.execute(
        """
        CREATE TABLE parking_reports (
            id BIGSERIAL PRIMARY KEY,
            poi_id UUID NOT NULL REFERENCES pois(id) ON DELETE CASCADE,
            session_id UUID NOT NULL,
            vehicle TEXT NOT NULL CHECK (vehicle IN ('motorbike', 'car', 'bicycle', 'ev')),
            amount_vnd INTEGER CHECK (amount_vnd IS NULL OR amount_vnd BETWEEN 0 AND 5000000),
            unit TEXT CHECK (unit IS NULL OR unit IN ('turn', 'hour', 'day', 'night', 'month', 'kwh')),
            opening_hours TEXT CHECK (opening_hours IS NULL OR length(opening_hours) <= 120),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            report_date DATE NOT NULL DEFAULT CURRENT_DATE,
            CHECK (amount_vnd IS NOT NULL OR opening_hours IS NOT NULL),
            CHECK ((amount_vnd IS NULL) = (unit IS NULL))
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX parking_reports_once_per_day "
        "ON parking_reports (poi_id, session_id, vehicle, report_date)"
    )
    op.execute("CREATE INDEX parking_reports_poi_idx ON parking_reports (poi_id, created_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS parking_reports")
    op.execute("DROP TABLE IF EXISTS parking_facilities")

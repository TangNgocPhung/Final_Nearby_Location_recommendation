"""Sân bay: thêm bộ lọc `aeroway` và gieo Tân Sơn Nhất làm POI demo.

Revision ID: 0017_airport_pois
Revises: 0016_saved_places

Sân bay trong OSM mang thẻ `aeroway=aerodrome`, không phải `amenity`/
`tourism`/`leisure`/`shop` — bốn khoá duy nhất mà `poi_import.OSM_FILTERS`
từng lọc. Vì vậy không phải Tân Sơn Nhất bị nhập sai, mà nó CHƯA TỪNG được
nhập: `poi_features.CATEGORY_MAP` không có khoá `aeroway` nên
`osm_category` luôn trả `None` cho một node aerodrome, và `normalize_osm_
element` loại bỏ thẳng node đó trước khi tới bước ghi DB (xem điều kiện
`not category_value` ở đó).

Bản vá gồm ba phần, cùng một nguyên nhân:

1. `poi_import.OSM_FILTERS` thêm khoá `"aeroway": "aerodrome"` — lần nhập
   OSM kế tiếp trên VPS mới thấy được node.
2. `poi_features.CATEGORY_MAP` thêm `("aeroway", "aerodrome") -> ("airport",
   "Sân bay")`, và `osm_category` duyệt thêm khoá `aeroway`. Nhãn mới kéo
   theo `CATEGORY_KEYWORDS["airport"]` (để truy vấn "sân bay" khớp được —
   xem lý do cùng cơ chế ở `0015_cinema_pois`), icon `Plane` ở
   `poi-cover.tsx`/`location-explorer.tsx`, và xếp "airport" vào nhóm
   `NECESSITY_CATEGORIES` của `weather.py`: không ai hoãn ra sân bay vì trời
   mưa ở đầu tìm kiếm.
3. Migration này: gieo Tân Sơn Nhất làm dữ liệu DEMO (`source = 'seed'`),
   đúng lý do và đúng giới hạn đã ghi ở `0015_cinema_pois` cho rạp chiếu
   phim — lặp lại ở đây vì áp dụng nguyên vẹn:
   - Toạ độ lấy từ vị trí công khai của nhà ga, làm tròn 4 chữ số (~11 m),
     không phải đo đạc thực địa.
   - `rating` để NULL, `review_count`/`popularity_score` bằng 0 — POI demo
     không được có điểm bịa ra thắng POI thật (xem `0008`).
   - `opening_hours` để rỗng: sân bay hoạt động 24/7 nhưng từng nhà ga có
     giờ làm thủ tục riêng theo hãng bay, bịa một khung giờ chung sẽ sai.
   - Mô tả không nhắc tên loại địa điểm khác, tránh khớp nhầm qua đường dự
     phòng `description ILIKE '%<truy vấn>%'` của PostGIS.

   Nguồn có thẩm quyền vẫn là lần nhập OSM; hàng chỉ được chèn khi CHƯA có
   sân bay nào trong bán kính 1500 m (rộng hơn ngưỡng 150 m của rạp chiếu
   phim vì khuôn viên sân bay lớn hơn nhiều — nhà ga quốc tế và quốc nội của
   Tân Sơn Nhất cách nhau hơn 300 m).
"""

from __future__ import annotations

import hashlib
import json
import math

import sqlalchemy as sa
from alembic import op

from app.poi_features import h3_cells, normalize_text


revision = "0017_airport_pois"
down_revision = "0016_saved_places"
branch_labels = None
depends_on = None


AIRPORT_LABEL = "Sân bay"
EMBEDDING_DIMENSION = 64
EMBEDDING_MODEL = "hashing-v2-64"

# Khuôn viên sân bay rộng hơn nhiều so với một cụm rạp; 150 m (ngưỡng của
# 0015_cinema_pois) không đủ để nhận ra một sân bay thật đã có trong DB.
DUPLICATE_RADIUS_M = 1500

# (id, name, description, address, longitude, latitude, district, brand)
AIRPORTS = [
    (
        "10000000-0000-0000-0000-000000000035",
        "Sân bay quốc tế Tân Sơn Nhất",
        "Sân bay lớn nhất Việt Nam theo lượng khách, phục vụ cả chuyến bay quốc nội và quốc tế.",
        "Trường Sơn, Quận Tân Bình",
        106.6520,
        10.8188,
        "Quận Tân Bình",
        None,
    ),
]


def _embedding(name: str, description: str, tags: list[str]) -> list[float]:
    """Bản sao ĐÓNG BĂNG của `poi_features.text_embedding` (hashing-v2-64).

    Chép thay vì import, cùng lý do đã ghi ở `0015_cinema_pois`: migration
    phải cho cùng một kết quả ở mọi thời điểm dù hàm của app có đổi.
    """
    joined = " ".join(part or "" for part in (name, description, " ".join(tags)))
    vector = [0.0] * EMBEDDING_DIMENSION
    for token in normalize_text(joined).split():
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=16).digest()
        first = int.from_bytes(digest[0:4], "big") % EMBEDDING_DIMENSION
        second = (
            int.from_bytes(digest[4:8], "big") % (EMBEDDING_DIMENSION - 1) + first + 1
        ) % EMBEDDING_DIMENSION
        for offset, index in ((0, first), (4, second)):
            vector[index] += 1.0 if digest[offset + 8] & 1 else -1.0
    norm = math.sqrt(sum(value * value for value in vector))
    return [round(value / norm, 8) for value in vector] if norm else vector


def _fingerprint(name: str, latitude: float, longitude: float) -> str:
    payload = f"{normalize_text(name)}|airport|{latitude:.5f}|{longitude:.5f}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_INSERT_AIRPORT = sa.text(
    """
    INSERT INTO pois (
        id, name, normalized_name, description, category, category_label,
        address, normalized_address, location, rating, review_count,
        popularity_score, tags, brand, district, source, source_id,
        canonical_id, h3_r7, h3_r8, h3_r9, embedding, embedding_model,
        dedupe_fingerprint
    )
    SELECT
        CAST(:id AS uuid), :name, :normalized_name, :description, 'airport',
        :category_label, :address, :normalized_address,
        ST_SetSRID(ST_Point(:longitude, :latitude), 4326)::geography,
        NULL, 0, 0, ARRAY['aerodrome']::text[], :brand, :district, 'seed', :id,
        CAST(:id AS uuid), :h3_r7, :h3_r8, :h3_r9,
        ARRAY(
            SELECT value::real
            FROM jsonb_array_elements_text(CAST(:embedding_json AS jsonb)) AS value
        ),
        :embedding_model, :fingerprint
    WHERE NOT EXISTS (
        SELECT 1 FROM pois existing
        WHERE existing.category = 'airport'
          AND ST_DWithin(
              existing.location,
              ST_SetSRID(ST_Point(:longitude, :latitude), 4326)::geography,
              CAST(:duplicate_radius AS double precision)
          )
    )
    ON CONFLICT (id) DO NOTHING
    """
)

_INSERT_LINEAGE = sa.text(
    """
    INSERT INTO poi_source_records (
        canonical_poi_id, source, source_type, source_id, raw_payload
    )
    SELECT id, source, 'seed', source_id,
           jsonb_build_object('name', name, 'address', address)
    FROM pois
    WHERE id = ANY(CAST(:ids AS uuid[]))
    ON CONFLICT (source, source_type, source_id) DO NOTHING
    """
)


def _ids_literal() -> str:
    return "{" + ",".join(row[0] for row in AIRPORTS) + "}"


def upgrade() -> None:
    connection = op.get_bind()

    payloads = []
    for poi_id, name, description, address, longitude, latitude, district, brand in AIRPORTS:
        cells = h3_cells(latitude, longitude)
        payloads.append(
            {
                "id": poi_id,
                "name": name,
                "normalized_name": normalize_text(name),
                "description": description,
                "category_label": AIRPORT_LABEL,
                "address": address,
                "normalized_address": normalize_text(address),
                "longitude": longitude,
                "latitude": latitude,
                "brand": brand,
                "district": district,
                "h3_r7": cells["r7"],
                "h3_r8": cells["r8"],
                "h3_r9": cells["r9"],
                "embedding_json": json.dumps(_embedding(name, description, ["aerodrome"])),
                "embedding_model": EMBEDDING_MODEL,
                "fingerprint": _fingerprint(name, latitude, longitude),
                "duplicate_radius": DUPLICATE_RADIUS_M,
            }
        )
    # Từng câu một, không executemany: xem lý do ở 0015_cinema_pois — mỗi lần
    # chèn đổi luôn kết quả của NOT EXISTS cho hàng sau.
    for payload in payloads:
        connection.execute(_INSERT_AIRPORT, payload)

    connection.execute(_INSERT_LINEAGE, {"ids": _ids_literal()})


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "DELETE FROM poi_source_records "
            "WHERE canonical_poi_id = ANY(CAST(:ids AS uuid[]))"
        ),
        {"ids": _ids_literal()},
    )
    connection.execute(
        sa.text("DELETE FROM pois WHERE id = ANY(CAST(:ids AS uuid[]))"),
        {"ids": _ids_literal()},
    )

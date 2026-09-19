"""Nha khoa và Tiệc cưới & sự kiện: mở rộng bộ lọc, gieo POI demo.

Revision ID: 0019_dentist_event_venue_pois
Revises: 0018_spa_pois

Cùng một lớp lỗi với sân bay/spa (`0017_airport_pois`/`0018_spa_pois`): tìm
"nha khoa" hay "tiệc cưới" trả về địa điểm gần nhất bất kể loại gì, vì hai
nguyên nhân cộng dồn giống hệt hai lần trước:

1. Không POI nào mang `category` tương ứng — `amenity=dentist` (phòng khám
   nha khoa) và `amenity=events_venue` (trung tâm tiệc cưới/hội nghị, tag
   chuẩn của OSM cho loại hình này) đều chưa nằm trong
   `poi_import.OSM_FILTERS["amenity"]`.
2. BM25 khớp RỖNG cho cả hai truy vấn. `search.retrieval.
   _gate_by_text_relevance` cố ý không chặn khi BM25 rỗng (coi là truy vấn
   lạ, trả gần nhất còn hơn trả rỗng) — nên rơi thẳng về RRF không gian và
   trả POI gần nhất, y hệt ca "spa" đã sửa.

Bản vá:

- `poi_import.OSM_FILTERS["amenity"]` thêm `dentist` và `events_venue`.
- `poi_features.CATEGORY_MAP` thêm hai ánh xạ:
  - `("amenity", "dentist") -> ("dentist", "Nha khoa")` — nhãn riêng, không
    gộp vào "Y tế" chung với bệnh viện/nhà thuốc, để chip lọc "Nha khoa" tách
    biệt được (đúng lý do đã tách "Xem phim" khỏi "Giải trí" ở `0015`).
  - `("amenity", "events_venue") -> ("event_venue", "Tiệc cưới & sự kiện")`.
  Nhãn mới kéo theo `CATEGORY_KEYWORDS["dentist"]`/`["event_venue"]` để
  `search_keywords` khớp được các cụm "nha khoa", "khám răng", "tiệc cưới",
  "sảnh tiệc"...
- `weather.py`: `dentist` vào `NECESSITY_CATEGORIES` (không ai hoãn khám răng
  vì trời mưa, cùng nhóm với bệnh viện/nhà thuốc); `event_venue` vào
  `INDOOR_CATEGORIES` (trung tâm tiệc cưới luôn trong nhà).
- Icon `Smile`/`Cake` ở `poi-cover.tsx`/`location-explorer.tsx`.
- Migration này: gieo một phòng khám nha khoa và một trung tâm tiệc cưới có
  thật (`source = 'seed'`), đúng giới hạn đã ghi ở `0015`/`0017`/`0018`:
  - Toạ độ lấy từ địa chỉ công khai, làm tròn 4 chữ số (~11 m), không phải
    đo đạc thực địa.
  - `rating` để NULL, `review_count`/`popularity_score` bằng 0.
  - `opening_hours` để rỗng.
  - Mô tả không nhắc tên loại địa điểm khác.

  Nguồn có thẩm quyền vẫn là lần nhập OSM; mỗi hàng chỉ được chèn khi CHƯA có
  POI cùng category trong bán kính 150 m.
"""

from __future__ import annotations

import hashlib
import json
import math

import sqlalchemy as sa
from alembic import op

from app.poi_features import h3_cells, normalize_text


revision = "0019_dentist_event_venue_pois"
down_revision = "0018_spa_pois"
branch_labels = None
depends_on = None


EMBEDDING_DIMENSION = 64
EMBEDDING_MODEL = "hashing-v2-64"
DUPLICATE_RADIUS_M = 150

# (id, name, description, address, longitude, latitude, district, brand, category, label)
POIS = [
    (
        "10000000-0000-0000-0000-000000000038",
        "Nha Khoa Kim - Chi nhánh Hai Bà Trưng",
        "Phòng khám nha khoa trên đường Hai Bà Trưng, Quận 1.",
        "150-152 Hai Bà Trưng, Quận 1",
        106.6935,
        10.7857,
        "Quận 1",
        "Nha Khoa Kim",
        "dentist",
        "Nha khoa",
    ),
    (
        "10000000-0000-0000-0000-000000000039",
        "White Palace Hoàng Văn Thụ",
        "Trung tâm hội nghị và tiệc cưới trên đường Hoàng Văn Thụ, Quận Phú Nhuận.",
        "194 Hoàng Văn Thụ, Quận Phú Nhuận",
        106.6790,
        10.7975,
        "Quận Phú Nhuận",
        "White Palace",
        "event_venue",
        "Tiệc cưới & sự kiện",
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


def _fingerprint(name: str, category: str, latitude: float, longitude: float) -> str:
    payload = f"{normalize_text(name)}|{category}|{latitude:.5f}|{longitude:.5f}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_INSERT_POI = sa.text(
    """
    INSERT INTO pois (
        id, name, normalized_name, description, category, category_label,
        address, normalized_address, location, rating, review_count,
        popularity_score, tags, brand, district, source, source_id,
        canonical_id, h3_r7, h3_r8, h3_r9, embedding, embedding_model,
        dedupe_fingerprint
    )
    SELECT
        CAST(:id AS uuid), :name, :normalized_name, :description, :category,
        :category_label, :address, :normalized_address,
        ST_SetSRID(ST_Point(:longitude, :latitude), 4326)::geography,
        NULL, 0, 0, ARRAY[:category]::text[], :brand, :district, 'seed', :id,
        CAST(:id AS uuid), :h3_r7, :h3_r8, :h3_r9,
        ARRAY(
            SELECT value::real
            FROM jsonb_array_elements_text(CAST(:embedding_json AS jsonb)) AS value
        ),
        :embedding_model, :fingerprint
    WHERE NOT EXISTS (
        SELECT 1 FROM pois existing
        WHERE existing.category = :category
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
    return "{" + ",".join(row[0] for row in POIS) + "}"


def upgrade() -> None:
    connection = op.get_bind()

    payloads = []
    for (
        poi_id,
        name,
        description,
        address,
        longitude,
        latitude,
        district,
        brand,
        category,
        category_label,
    ) in POIS:
        cells = h3_cells(latitude, longitude)
        payloads.append(
            {
                "id": poi_id,
                "name": name,
                "normalized_name": normalize_text(name),
                "description": description,
                "category": category,
                "category_label": category_label,
                "address": address,
                "normalized_address": normalize_text(address),
                "longitude": longitude,
                "latitude": latitude,
                "brand": brand,
                "district": district,
                "h3_r7": cells["r7"],
                "h3_r8": cells["r8"],
                "h3_r9": cells["r9"],
                "embedding_json": json.dumps(_embedding(name, description, [category])),
                "embedding_model": EMBEDDING_MODEL,
                "fingerprint": _fingerprint(name, category, latitude, longitude),
                "duplicate_radius": DUPLICATE_RADIUS_M,
            }
        )
    # Từng câu một, không executemany: xem lý do ở 0015_cinema_pois — mỗi lần
    # chèn đổi luôn kết quả của NOT EXISTS cho hàng sau.
    for payload in payloads:
        connection.execute(_INSERT_POI, payload)

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

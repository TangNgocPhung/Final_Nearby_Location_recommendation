"""Cắt tóc: thêm `shop=hairdresser` vào bộ lọc và gieo một tiệm demo.

Revision ID: 0020_hairdresser_pois
Revises: 0019_dentist_event_venue_pois

Cùng lớp lỗi với sân bay/spa/nha khoa/tiệc cưới đã sửa ở ba migration trước:
tìm "cắt tóc" trả về quán cà phê gần nhất, vì `shop=hairdresser` (thẻ OSM cho
tiệm cắt tóc/salon tóc) chưa từng nằm trong `poi_import.OSM_FILTERS["shop"]`,
nên không có POI nào thuộc loại này — BM25 khớp rỗng và
`search.retrieval._gate_by_text_relevance` rơi về ứng viên gần nhất bất kể
loại gì (đúng thiết kế cho truy vấn LẠ, nhưng "cắt tóc" không lạ, chỉ thiếu
dữ liệu).

Bản vá:

- `poi_import.OSM_FILTERS["shop"]` thêm giá trị `hairdresser`.
- `poi_features.CATEGORY_MAP` thêm `("shop", "hairdresser") -> ("hairdresser",
  "Cắt tóc")`; `CATEGORY_KEYWORDS["hairdresser"]` thêm các cụm "cắt tóc",
  "tiệm tóc", "hớt tóc", "làm tóc"... để `search_keywords` khớp được.
- `weather.py`: xếp `hairdresser` vào `INDOOR_CATEGORIES` (tiệm cắt tóc luôn
  trong nhà).
- Icon `Scissors` ở `poi-cover.tsx`/`location-explorer.tsx`.
- Migration này: gieo một tiệm tóc có thật (`source = 'seed'`), đúng giới hạn
  đã ghi ở các migration trước (toạ độ từ địa chỉ công khai, làm tròn 4 chữ
  số; `rating` NULL; `opening_hours` rỗng; mô tả không nhắc loại địa điểm
  khác). Nguồn có thẩm quyền vẫn là lần nhập OSM; hàng chỉ được chèn khi CHƯA
  có tiệm tóc nào trong bán kính 150 m.
"""

from __future__ import annotations

import hashlib
import json
import math

import sqlalchemy as sa
from alembic import op

from app.poi_features import h3_cells, normalize_text


revision = "0020_hairdresser_pois"
down_revision = "0019_dentist_event_venue_pois"
branch_labels = None
depends_on = None


HAIRDRESSER_LABEL = "Cắt tóc"
EMBEDDING_DIMENSION = 64
EMBEDDING_MODEL = "hashing-v2-64"
DUPLICATE_RADIUS_M = 150

# (id, name, description, address, longitude, latitude, district, brand)
HAIRDRESSERS = [
    (
        "10000000-0000-0000-0000-000000000040",
        "30Shine Nguyễn Thị Minh Khai",
        "Tiệm cắt tóc nam trên đường Nguyễn Thị Minh Khai, phường Đa Kao, Quận 1.",
        "2 Nguyễn Thị Minh Khai, Quận 1",
        106.6975,
        10.7885,
        "Quận 1",
        "30Shine",
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
    payload = f"{normalize_text(name)}|hairdresser|{latitude:.5f}|{longitude:.5f}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_INSERT_HAIRDRESSER = sa.text(
    """
    INSERT INTO pois (
        id, name, normalized_name, description, category, category_label,
        address, normalized_address, location, rating, review_count,
        popularity_score, tags, brand, district, source, source_id,
        canonical_id, h3_r7, h3_r8, h3_r9, embedding, embedding_model,
        dedupe_fingerprint
    )
    SELECT
        CAST(:id AS uuid), :name, :normalized_name, :description, 'hairdresser',
        :category_label, :address, :normalized_address,
        ST_SetSRID(ST_Point(:longitude, :latitude), 4326)::geography,
        NULL, 0, 0, ARRAY['hairdresser']::text[], :brand, :district, 'seed', :id,
        CAST(:id AS uuid), :h3_r7, :h3_r8, :h3_r9,
        ARRAY(
            SELECT value::real
            FROM jsonb_array_elements_text(CAST(:embedding_json AS jsonb)) AS value
        ),
        :embedding_model, :fingerprint
    WHERE NOT EXISTS (
        SELECT 1 FROM pois existing
        WHERE existing.category = 'hairdresser'
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
    return "{" + ",".join(row[0] for row in HAIRDRESSERS) + "}"


def upgrade() -> None:
    connection = op.get_bind()

    payloads = []
    for poi_id, name, description, address, longitude, latitude, district, brand in HAIRDRESSERS:
        cells = h3_cells(latitude, longitude)
        payloads.append(
            {
                "id": poi_id,
                "name": name,
                "normalized_name": normalize_text(name),
                "description": description,
                "category_label": HAIRDRESSER_LABEL,
                "address": address,
                "normalized_address": normalize_text(address),
                "longitude": longitude,
                "latitude": latitude,
                "brand": brand,
                "district": district,
                "h3_r7": cells["r7"],
                "h3_r8": cells["r8"],
                "h3_r9": cells["r9"],
                "embedding_json": json.dumps(_embedding(name, description, ["hairdresser"])),
                "embedding_model": EMBEDDING_MODEL,
                "fingerprint": _fingerprint(name, latitude, longitude),
                "duplicate_radius": DUPLICATE_RADIUS_M,
            }
        )
    # Từng câu một, không executemany: xem lý do ở 0015_cinema_pois — mỗi lần
    # chèn đổi luôn kết quả của NOT EXISTS cho hàng sau.
    for payload in payloads:
        connection.execute(_INSERT_HAIRDRESSER, payload)

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

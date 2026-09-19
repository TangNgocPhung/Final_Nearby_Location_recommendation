"""Spa: thêm `leisure=spa` vào bộ lọc và gieo hai spa demo ở Quận 1.

Revision ID: 0018_spa_pois
Revises: 0017_airport_pois

Cùng một lớp lỗi với sân bay (`0017_airport_pois`): tìm "spa" trả về quán cà
phê gần nhất chứ không phải "không có kết quả", vì hai nguyên nhân cộng dồn:

1. Không có POI nào mang `category = "spa"` trong dữ liệu — `leisure=spa` là
   thẻ OSM cho cơ sở spa, nhưng `poi_import.OSM_FILTERS["leisure"]` trước đây
   chỉ nhận `park|garden|fitness_centre|sports_centre|playground`. Không thẻ
   thì không POI, đúng như Tân Sơn Nhất trước khi có `aeroway`.
2. BM25 vì vậy khớp RỖNG cho truy vấn "spa". `search.retrieval.
   _gate_by_text_relevance` cố ý KHÔNG chặn khi BM25 rỗng — coi đó là "truy
   vấn quá lạ, trả thứ gần nhất còn hơn trả rỗng" — nên toàn bộ pipeline rơi
   thẳng về RRF thuần không gian/trending, và ứng viên gần nhất (một quán cà
   phê) thắng. Hành vi (2) là ĐÚNG THIẾT KẾ cho truy vấn thật sự lạ; vấn đề
   nằm ở (1) — "spa" không lạ, chỉ là chưa có dữ liệu.

Bản vá:

- `poi_import.OSM_FILTERS["leisure"]` thêm giá trị `spa`.
- `poi_features.CATEGORY_MAP` thêm `("leisure", "spa") -> ("spa", "Spa")`
  (khoá `leisure` đã có sẵn trong vòng lặp của `osm_category`, không cần sửa
  hàm đó). Nhãn mới kéo theo `CATEGORY_KEYWORDS["spa"]` để truy vấn "spa",
  "mát xa", "massage" khớp được qua `search_keywords` — cùng cơ chế đã dùng
  cho "xem phim" ở `0015_cinema_pois`.
- `weather.py` xếp `spa` vào `INDOOR_CATEGORIES`: cơ sở spa luôn trong nhà,
  nên trời mưa được ưu tiên nhẹ thay vì trung tính hay bị hạ điểm.
- Icon `Flower2` ở `poi-cover.tsx`/`location-explorer.tsx`.
- Migration này: gieo hai spa demo (`source = 'seed'`) tại Quận 1, đúng giới
  hạn đã ghi ở `0015_cinema_pois`/`0017_airport_pois`:
  - Toạ độ lấy từ địa chỉ công khai, làm tròn 4 chữ số (~11 m), không phải
    đo đạc thực địa.
  - `rating` để NULL, `review_count`/`popularity_score` bằng 0.
  - `opening_hours` để rỗng.
  - Mô tả không nhắc tên loại địa điểm khác, tránh khớp nhầm qua đường dự
    phòng `description ILIKE '%<truy vấn>%'` của PostGIS.

  Nguồn có thẩm quyền vẫn là lần nhập OSM; mỗi hàng chỉ được chèn khi CHƯA có
  spa nào trong bán kính 150 m (cùng ngưỡng với rạp chiếu phim — spa là cơ sở
  quy mô cửa hàng, không rộng như khuôn viên sân bay).
"""

from __future__ import annotations

import hashlib
import json
import math

import sqlalchemy as sa
from alembic import op

from app.poi_features import h3_cells, normalize_text


revision = "0018_spa_pois"
down_revision = "0017_airport_pois"
branch_labels = None
depends_on = None


SPA_LABEL = "Spa"
EMBEDDING_DIMENSION = 64
EMBEDDING_MODEL = "hashing-v2-64"
DUPLICATE_RADIUS_M = 150

# (id, name, description, address, longitude, latitude, district, brand)
SPAS = [
    (
        "10000000-0000-0000-0000-000000000036",
        "L'Apothiquaire Artisan Beauté",
        "Spa Pháp lâu năm tại Diamond Plaza, đường Lê Duẩn, Quận 1.",
        "34 Lê Duẩn, Quận 1",
        106.6985,
        10.7813,
        "Quận 1",
        "L'Apothiquaire",
    ),
    (
        "10000000-0000-0000-0000-000000000037",
        "Miu Miu Spa 1",
        "Cơ sở spa và mát-xa trên đường Chu Mạnh Trinh, phường Bến Nghé, Quận 1.",
        "4 Chu Mạnh Trinh, Quận 1",
        106.7040,
        10.7842,
        "Quận 1",
        "Miu Miu Spa",
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
    payload = f"{normalize_text(name)}|spa|{latitude:.5f}|{longitude:.5f}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_INSERT_SPA = sa.text(
    """
    INSERT INTO pois (
        id, name, normalized_name, description, category, category_label,
        address, normalized_address, location, rating, review_count,
        popularity_score, tags, brand, district, source, source_id,
        canonical_id, h3_r7, h3_r8, h3_r9, embedding, embedding_model,
        dedupe_fingerprint
    )
    SELECT
        CAST(:id AS uuid), :name, :normalized_name, :description, 'spa',
        :category_label, :address, :normalized_address,
        ST_SetSRID(ST_Point(:longitude, :latitude), 4326)::geography,
        NULL, 0, 0, ARRAY['spa']::text[], :brand, :district, 'seed', :id,
        CAST(:id AS uuid), :h3_r7, :h3_r8, :h3_r9,
        ARRAY(
            SELECT value::real
            FROM jsonb_array_elements_text(CAST(:embedding_json AS jsonb)) AS value
        ),
        :embedding_model, :fingerprint
    WHERE NOT EXISTS (
        SELECT 1 FROM pois existing
        WHERE existing.category = 'spa'
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
    return "{" + ",".join(row[0] for row in SPAS) + "}"


def upgrade() -> None:
    connection = op.get_bind()

    payloads = []
    for poi_id, name, description, address, longitude, latitude, district, brand in SPAS:
        cells = h3_cells(latitude, longitude)
        payloads.append(
            {
                "id": poi_id,
                "name": name,
                "normalized_name": normalize_text(name),
                "description": description,
                "category_label": SPA_LABEL,
                "address": address,
                "normalized_address": normalize_text(address),
                "longitude": longitude,
                "latitude": latitude,
                "brand": brand,
                "district": district,
                "h3_r7": cells["r7"],
                "h3_r8": cells["r8"],
                "h3_r9": cells["r9"],
                "embedding_json": json.dumps(_embedding(name, description, ["spa"])),
                "embedding_model": EMBEDDING_MODEL,
                "fingerprint": _fingerprint(name, latitude, longitude),
                "duplicate_radius": DUPLICATE_RADIUS_M,
            }
        )
    # Từng câu một, không executemany: xem lý do ở 0015_cinema_pois — mỗi lần
    # chèn đổi luôn kết quả của NOT EXISTS cho hàng sau.
    for payload in payloads:
        connection.execute(_INSERT_SPA, payload)

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

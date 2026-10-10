"""Gieo "Quán Phở 32" để stack sạch có đủ dữ liệu cho test hồi quy "quan pho".

Revision ID: 0038_quan_pho_32_seed
Revises: 0037_tiffany_jewelry_override

`tests/integration/test_retrieval_regression.py::test_quan_pho_khong_dau_van_
tim_duoc_quan_pho` (thêm ở ae9a1fa, đo trên DB dev 2026-10-08) đòi cả "Phở Nhà
Mình" lẫn "Quán Phở 32" có mặt trong top 10 của "quan pho". Phở Nhà Mình là
POI seed của `0002_seed_demo_data`, còn Quán Phở 32 là POI OSM
(``node/5830786091``) — chỉ có sau lần nhập OSM. Stack của CI chỉ chạy
migration, không nhập OSM, nên test đỏ ngay lần đầu stack khởi động được
(run 38008518855, merge ref của PR #14): không phải lỗi xếp hạng, mà POI cần
tìm không hề có trong chỉ mục.

Quán Phở 32 không thay được bằng một quán seed bất kỳ: nó là ca mà clause
``match_phrase`` của `search.query.bm25_body` tồn tại để giữ — tên chứa NGUYÊN
cụm "quán phở", cách tâm đo ~1 km, nên chỉ thứ tự liền nhau của hai token mới
đưa nó lên trên các POI khớp rời "quận"/"thành phố". Phở Nhà Mình (tên không
có "quán") khoá vế kia: "quan" không bắt buộc.

Hàng chép từ chính bản ghi OSM trên DB dev (tên, địa chỉ, loại, tags; mô tả
OSM rỗng nên để rỗng), với cùng giới hạn đã ghi ở `0015_cinema_pois`: toạ độ
làm tròn 4 chữ số (~11 m), `rating` NULL, `opening_hours` rỗng. Chỉ chèn khi
CHƯA có nhà hàng cùng tên chuẩn hoá trong 75 m — đúng điều kiện gộp trùng của
`poi_import._find_existing` — nên DB đã nhập OSM giữ nguyên hàng thật, và lần
nhập OSM sau trên DB sạch gộp vào hàng này thay vì sinh bản trùng.
"""

from __future__ import annotations

import hashlib
import json
import math

import sqlalchemy as sa
from alembic import op

from app.poi_features import h3_cells, normalize_text


revision = "0038_quan_pho_32_seed"
down_revision = "0037_tiffany_jewelry_override"
branch_labels = None
depends_on = None


RESTAURANT_LABEL = "Ăn uống"
EMBEDDING_DIMENSION = 64
EMBEDDING_MODEL = "hashing-v2-64"
# Ngưỡng gộp trùng của `poi_import._find_existing`.
DUPLICATE_RADIUS_M = 75

# (id, name, description, address, longitude, latitude, district, brand)
RESTAURANTS = [
    (
        "10000000-0000-0000-0000-000000000041",
        "Quán Phở 32",
        "",
        "32, Lê Thị Riêng, Quận 1",
        106.6923,
        10.7714,
        "Quận 1",
        "",
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
    payload = f"{normalize_text(name)}|restaurant|{latitude:.5f}|{longitude:.5f}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_INSERT_RESTAURANT = sa.text(
    """
    INSERT INTO pois (
        id, name, normalized_name, description, category, category_label,
        address, normalized_address, location, rating, review_count,
        popularity_score, tags, brand, district, source, source_id,
        canonical_id, h3_r7, h3_r8, h3_r9, embedding, embedding_model,
        dedupe_fingerprint
    )
    SELECT
        CAST(:id AS uuid), :name, :normalized_name, :description, 'restaurant',
        :category_label, :address, :normalized_address,
        ST_SetSRID(ST_Point(:longitude, :latitude), 4326)::geography,
        NULL, 0, 0, ARRAY['restaurant']::text[], :brand, :district, 'seed', :id,
        CAST(:id AS uuid), :h3_r7, :h3_r8, :h3_r9,
        ARRAY(
            SELECT value::real
            FROM jsonb_array_elements_text(CAST(:embedding_json AS jsonb)) AS value
        ),
        :embedding_model, :fingerprint
    WHERE NOT EXISTS (
        SELECT 1 FROM pois existing
        WHERE existing.category = 'restaurant'
          AND existing.normalized_name = :normalized_name
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
    return "{" + ",".join(row[0] for row in RESTAURANTS) + "}"


def upgrade() -> None:
    connection = op.get_bind()

    for poi_id, name, description, address, longitude, latitude, district, brand in RESTAURANTS:
        cells = h3_cells(latitude, longitude)
        connection.execute(
            _INSERT_RESTAURANT,
            {
                "id": poi_id,
                "name": name,
                "normalized_name": normalize_text(name),
                "description": description,
                "category_label": RESTAURANT_LABEL,
                "address": address,
                "normalized_address": normalize_text(address),
                "longitude": longitude,
                "latitude": latitude,
                "brand": brand,
                "district": district,
                "h3_r7": cells["r7"],
                "h3_r8": cells["r8"],
                "h3_r9": cells["r9"],
                "embedding_json": json.dumps(_embedding(name, description, ["restaurant"])),
                "embedding_model": EMBEDDING_MODEL,
                "fingerprint": _fingerprint(name, latitude, longitude),
                "duplicate_radius": DUPLICATE_RADIUS_M,
            },
        )

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

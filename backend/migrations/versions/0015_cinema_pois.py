"""Rạp chiếu phim: tách nhãn riêng "Xem phim" và gieo POI demo cho nhóm này.

Revision ID: 0015_cinema_pois
Revises: 0014_district_boundaries

Hai việc, cùng một nguyên nhân: truy vấn "xem phim" không trả về rạp nào (đo
19/09/2026 — hai kết quả đầu là Bảo tàng Thành phố và Phở Nhà Mình).

**1. Nhãn.** `amenity=cinema` trước đây gộp vào nhãn "Giải trí" chung với
bar/pub/playground. Nhãn là một trong những trường BM25 chấm điểm cao nhất
(`category_label^2`) và cũng là thứ người dùng bấm trên chip lọc, nên gộp như
vậy vừa làm mất một chip có ích vừa xoá luôn manh mối văn bản duy nhất nối
truy vấn "xem phim" với rạp chiếu phim — tên rạp ở TP.HCM gần như không bao
giờ chứa chữ "phim" (CGV, Lotte Cinema, BHD Star, Galaxy, Mega GS, Cinestar).
"Xem phim" cũng đúng lối đặt tên của các nhãn sẵn có ("Ăn uống", "Mua sắm",
"Lưu trú"): cụm động từ mô tả việc người dùng định làm.

Đổi nhãn KHÔNG phải tính lại `embedding`: vector sinh từ tên + mô tả + tags,
không có `category_label` (xem `poi_features.normalize_osm_element`). Nhưng
PHẢI dựng lại chỉ mục OpenSearch, vì nhãn nằm trong document đã index.

**2. Dữ liệu.** Cụm rạp phía dưới là dữ liệu DEMO (`source = 'seed'`), để một
lần `docker compose up` sạch — chỉ chạy migration, chưa nhập OSM — vẫn có gì
đó cho nhóm "Xem phim", giống 28 POI seed của `0002_seed_demo_data`. Giới hạn
của nó phải nói rõ:

- Toạ độ lấy từ địa chỉ công khai và làm tròn 4 chữ số (~11 m), KHÔNG phải đo
  đạc thực địa. Sai số cỡ vài chục mét là chuyện bình thường ở đây.
- `rating` để NULL chứ không gán điểm tự nghĩ ra: migration `0008` đã chỉ rõ
  rating seed bịa làm POI demo luôn thắng POI thật trong công thức xếp hạng.
  Vì vậy `review_count`/`popularity_score` cũng bằng 0.
- `opening_hours` để rỗng. Giờ chiếu là thông tin thay đổi theo tuần; bịa ra
  một khung giờ rồi hiện "Đang mở" cho người dùng còn tệ hơn là để trống.
- Mô tả CỐ Ý không nhắc tên một loại địa điểm khác. Đường dự phòng PostGIS có
  điều kiện `description ILIKE '%<truy vấn>%'`, nên một câu mô tả kiểu "cạnh
  công viên Tao Đàn" là đủ để rạp lọt vào kết quả của truy vấn "công viên" —
  đo được đúng như vậy ở bản nháp của chính migration này.

Nguồn có thẩm quyền vẫn là lần nhập OSM (`amenity=cinema` đã nằm sẵn trong
`poi_import.OSM_FILTERS`). Nên mỗi hàng chỉ được chèn khi CHƯA có rạp nào
trong bán kính 150 m — chạy migration trên một database đã nhập OSM thì các
rạp thật giữ nguyên chỗ của chúng, không sinh ra bản trùng.
"""

from __future__ import annotations

import hashlib
import json
import math

import sqlalchemy as sa
from alembic import op

from app.poi_features import h3_cells, normalize_text


revision = "0015_cinema_pois"
down_revision = "0014_district_boundaries"
branch_labels = None
depends_on = None


CINEMA_LABEL = "Xem phim"
PREVIOUS_LABEL = "Giải trí"
EMBEDDING_DIMENSION = 64
EMBEDDING_MODEL = "hashing-v2-64"

# Khoảng cách coi như "đã có rạp ở đây rồi". Rộng hơn ngưỡng gộp trùng 75 m của
# `poi_import._find_existing` vì ở đây không so tên: một cụm rạp trong trung
# tâm thương mại có thể được OSM đặt điểm ở lối vào hay ở giữa toà nhà, cách
# địa chỉ mặt đường cả trăm mét.
DUPLICATE_RADIUS_M = 150

# (id, name, description, address, longitude, latitude, district, brand)
CINEMAS = [
    (
        "10000000-0000-0000-0000-000000000029",
        "CGV Vincom Đồng Khởi",
        "Cụm rạp nhiều phòng chiếu tại Vincom Center, Lê Thánh Tôn, Quận 1.",
        "72 Lê Thánh Tôn, Quận 1",
        106.7029,
        10.7789,
        "Quận 1",
        "CGV",
    ),
    (
        "10000000-0000-0000-0000-000000000030",
        "Lotte Cinema Diamond",
        "Rạp chiếu phim tại Diamond Plaza, đường Lê Duẩn, Quận 1.",
        "34 Lê Duẩn, Quận 1",
        106.6985,
        10.7813,
        "Quận 1",
        "Lotte Cinema",
    ),
    (
        "10000000-0000-0000-0000-000000000031",
        "BHD Star Bitexco",
        "Cụm rạp trên tầng cao toà nhà Bitexco Financial Tower.",
        "2 Hải Triều, Quận 1",
        106.7043,
        10.7717,
        "Quận 1",
        "BHD Star",
    ),
    (
        "10000000-0000-0000-0000-000000000032",
        "Galaxy Nguyễn Du",
        "Rạp chiếu phim lâu năm trên đường Nguyễn Du, Quận 1.",
        "116 Nguyễn Du, Quận 1",
        106.6934,
        10.7744,
        "Quận 1",
        "Galaxy Cinema",
    ),
    (
        "10000000-0000-0000-0000-000000000033",
        "Mega GS Cao Thắng",
        "Rạp chiếu phim trên đường Cao Thắng, Quận 3.",
        "19 Cao Thắng, Quận 3",
        106.6816,
        10.7706,
        "Quận 3",
        "Mega GS",
    ),
    (
        "10000000-0000-0000-0000-000000000034",
        "Cinestar Quốc Thanh",
        "Rạp chiếu phim Quốc Thanh trên đường Nguyễn Trãi.",
        "271 Nguyễn Trãi, Quận 1",
        106.6853,
        10.7658,
        "Quận 1",
        "Cinestar",
    ),
]


def _embedding(name: str, description: str, tags: list[str]) -> list[float]:
    """Bản sao ĐÓNG BĂNG của `poi_features.text_embedding` (hashing-v2-64).

    Chép vào đây thay vì import, đúng bài học đã ghi trong `0005_recompute_
    embeddings_v2`: migration phải cho cùng một kết quả ở mọi thời điểm, mà
    hàm của app thì được phép đổi (chính nó đã đổi một lần từ v1 sang v2). Nếu
    sau này app lên v3, một migration tính lại sẽ quét theo `embedding_model`
    và nhặt các hàng này lên như mọi hàng khác.
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
    payload = f"{normalize_text(name)}|cinema|{latitude:.5f}|{longitude:.5f}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_INSERT_CINEMA = sa.text(
    """
    INSERT INTO pois (
        id, name, normalized_name, description, category, category_label,
        address, normalized_address, location, rating, review_count,
        popularity_score, tags, brand, district, source, source_id,
        canonical_id, h3_r7, h3_r8, h3_r9, embedding, embedding_model,
        dedupe_fingerprint
    )
    SELECT
        CAST(:id AS uuid), :name, :normalized_name, :description, 'cinema',
        :category_label, :address, :normalized_address,
        ST_SetSRID(ST_Point(:longitude, :latitude), 4326)::geography,
        NULL, 0, 0, ARRAY['cinema']::text[], :brand, :district, 'seed', :id,
        CAST(:id AS uuid), :h3_r7, :h3_r8, :h3_r9,
        ARRAY(
            SELECT value::real
            FROM jsonb_array_elements_text(CAST(:embedding_json AS jsonb)) AS value
        ),
        :embedding_model, :fingerprint
    WHERE NOT EXISTS (
        SELECT 1 FROM pois existing
        WHERE existing.category = 'cinema'
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
    return "{" + ",".join(row[0] for row in CINEMAS) + "}"


def upgrade() -> None:
    connection = op.get_bind()

    connection.execute(
        sa.text(
            "UPDATE pois SET category_label = :label "
            "WHERE category = 'cinema' AND category_label IS DISTINCT FROM :label"
        ),
        {"label": CINEMA_LABEL},
    )

    payloads = []
    for poi_id, name, description, address, longitude, latitude, district, brand in CINEMAS:
        cells = h3_cells(latitude, longitude)
        payloads.append(
            {
                "id": poi_id,
                "name": name,
                "normalized_name": normalize_text(name),
                "description": description,
                "category_label": CINEMA_LABEL,
                "address": address,
                "normalized_address": normalize_text(address),
                "longitude": longitude,
                "latitude": latitude,
                "brand": brand,
                "district": district,
                "h3_r7": cells["r7"],
                "h3_r8": cells["r8"],
                "h3_r9": cells["r9"],
                "embedding_json": json.dumps(_embedding(name, description, ["cinema"])),
                "embedding_model": EMBEDDING_MODEL,
                "fingerprint": _fingerprint(name, latitude, longitude),
                "duplicate_radius": DUPLICATE_RADIUS_M,
            }
        )
    # Từng câu một, không executemany: mỗi lần chèn đổi luôn kết quả của
    # `NOT EXISTS` cho hàng sau (hai rạp cách nhau dưới 150 m thì chỉ hàng đầu
    # được vào). Gộp lô thì thứ tự đánh giá không còn bảo đảm.
    for payload in payloads:
        connection.execute(_INSERT_CINEMA, payload)

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
    connection.execute(
        sa.text(
            "UPDATE pois SET category_label = :previous "
            "WHERE category = 'cinema' AND category_label = :label"
        ),
        {"label": CINEMA_LABEL, "previous": PREVIOUS_LABEL},
    )

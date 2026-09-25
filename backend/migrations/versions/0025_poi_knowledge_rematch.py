"""POI Knowledge: gắn lại nội dung đã biên soạn (0022/0023) vào POI hiện tại theo tên + loại + vị trí.

Revision ID: 0025_poi_knowledge_rematch
Revises: 0024_parking_facilities

0021–0023 gắn `poi_knowledge` bằng UUID POI viết cứng. UUID của POI nhập từ
OSM được sinh MỚI mỗi lần nhập lại, nên sau lần mất dữ liệu Postgres ngày
2026-09-25 (Docker Desktop reset, nhập lại toàn bộ OSM) 11/16 dòng bị bỏ qua
trong im lặng (`WHERE EXISTS` / `UPDATE ... WHERE poi_id`) — chỉ còn 5 POI
seed (`10000000-...`, UUID cố định, gieo lại y hệt) là còn kiến thức.

Migration này tìm lại POI hiện tại cho 11 địa danh đó bằng thứ ỔN ĐỊNH qua
các lần nhập lại: `normalized_name` (pg_trgm similarity) + `category` + vị trí
trong bán kính nhỏ quanh toạ độ tham chiếu. Toạ độ tham chiếu là hình học OSM
đo được ngày 2026-09-25, làm tròn 4 chữ số (~10 m); bán kính 300 m đủ nuốt
chênh lệch node/way/centroid giữa các lần nhập nhưng loại được POI trùng tên
ở tỉnh khác (Bệnh viện Da liễu Đồng Nai, Bưu điện Trung tâm Bà Rịa...).

Nội dung KHÔNG chép lại ở đây mà nạp thẳng `ROWS` từ file 0022/0023 — bản
biên soạn đã đối chiếu nguồn chỉ có MỘT chỗ, không thể lệch nhau. Giá trị
ghi vào giống hệt trạng thái cuối cùng mà 0021→0022 (hoặc 0023) để lại khi
UUID còn khớp, kể cả quy tắc `source = context_source or intro_source`.

Chỉ INSERT khi POI khớp chưa có kiến thức (`ON CONFLICT DO NOTHING`) — chạy
lại hay chạy trên DB mà UUID cũ vẫn còn đều không ghi đè gì.

Địa đạo Phú Thọ Hòa vẫn có 2 bản ghi OSM (landmark + park) — giữ đúng quyết
định của 0023: chỉ gắn vào bản `landmark`.
"""

from __future__ import annotations

import importlib.util
import json
import logging
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0025_poi_knowledge_rematch"
down_revision = "0024_parking_facilities"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

_RADIUS_M = 300
_MIN_SIMILARITY = 0.6

# UUID cũ (khoá trong ROWS của 0022/0023) -> cách tìm lại POI hiện tại:
# (tên hiển thị, normalized_name, category chấp nhận, lat, lon)
MATCH_SPECS: dict[str, tuple[str, str, tuple[str, ...], float, float]] = {
    "0cf8a1c6-b4ac-4b36-af9c-a4d00e6b77b2": ("Bưu điện Trung tâm Sài Gòn", "buu dien trung tam sai gon", ("post_office", "landmark"), 10.7800, 106.7000),
    "b77eae42-8b8c-4c6d-a6f6-95dfb0b289a1": ("Bảo tàng Thành phố Hồ Chí Minh", "bao tang thanh pho ho chi minh", ("museum", "landmark"), 10.7759, 106.6997),
    "f1856c1d-1e4a-445b-8efa-5385cfe2525d": ("Công viên Lê Thị Riêng", "cong vien le thi rieng", ("park",), 10.7848, 106.6646),
    "95baf653-acf7-4076-bea9-3ff55b4c82dd": ("Công viên Tao Đàn", "cong vien tao dan", ("park",), 10.7748, 106.6931),
    "f6151ff6-cc7a-41cb-b702-dca51b0a8d68": ("Thảo Cầm Viên Sài Gòn", "thao cam vien sai gon", ("park", "zoo"), 10.7878, 106.7065),
    "d60b068b-37c2-4cef-8e5f-2e3074137201": ("Bệnh viện Nhi đồng 1", "benh vien nhi dong 1", ("hospital",), 10.7688, 106.6699),
    "a48cd510-b6c1-4ac3-93e1-07f9fe8cee13": ("Bệnh viện Nhi đồng 2", "benh vien nhi dong 2", ("hospital",), 10.7815, 106.7028),
    "eded28c9-3576-43c0-b720-81987d251c91": ("Bệnh viện Da liễu", "benh vien da lieu", ("hospital",), 10.7768, 106.6869),
    "d44f5761-9b5f-4a69-b9e3-d65cece3844c": ("Bệnh viện Chợ Rẫy", "benh vien cho ray", ("hospital",), 10.7570, 106.6597),
    "e7e46513-f93a-4344-9d86-73c45b0e99bd": ("Địa đạo Phú Thọ Hòa", "dia dao phu tho hoa", ("landmark",), 10.7842, 106.6313),
    "603f22b4-bb7f-426d-9d72-dd43ac0bad49": ("Bót Dây Thép", "bot day thep", ("museum", "landmark"), 10.8443, 106.7935),
}

# Similarity giảm dần rồi khoảng cách tăng dần: "Công viên Chung cư Lê Thị
# Riêng" (similarity 0.78) nằm cách "Công viên Lê Thị Riêng" chỉ ~200 m, nên
# bán kính một mình không đủ phân biệt.
_FIND_POI = sa.text(
    """
    SELECT p.id::text AS id, p.name
    FROM pois p
    WHERE p.category = ANY(CAST(:categories AS text[]))
      AND ST_DWithin(
          p.location,
          ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
          :radius_m
      )
      AND similarity(p.normalized_name, :normalized_name) >= :min_similarity
    ORDER BY
        similarity(p.normalized_name, :normalized_name) DESC,
        ST_Distance(p.location, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography),
        p.id
    LIMIT 1
    """
)

_INSERT_KNOWLEDGE = sa.text(
    """
    INSERT INTO poi_knowledge (
        poi_id, content_type, intro, specialty, historical_context,
        historical_events, interesting_facts, source, verified
    )
    VALUES (
        CAST(:poi_id AS uuid), :content_type, :intro, :specialty,
        :historical_context, CAST(:historical_events AS jsonb),
        CAST(:interesting_facts AS jsonb), :source, :verified
    )
    ON CONFLICT (poi_id) DO NOTHING
    RETURNING poi_id
    """
)


def _curated_rows() -> dict[str, tuple]:
    """ROWS của 0022 + 0023, khoá theo UUID cũ — nạp file, không chép nội dung."""
    rows: dict[str, tuple] = {}
    for filename in ("0022_poi_knowledge_verified.py", "0023_phu_tho_hoa_bot_day_thep.py"):
        path = Path(__file__).with_name(filename)
        spec = importlib.util.spec_from_file_location(f"_curated_{path.stem}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        rows.update({row[0]: row for row in module.ROWS})
    return rows


def _find_poi(connection, spec: tuple) -> sa.Row | None:
    _, normalized_name, categories, lat, lon = spec
    return connection.execute(
        _FIND_POI,
        {
            "normalized_name": normalized_name,
            "categories": list(categories),
            "lat": lat,
            "lon": lon,
            "radius_m": _RADIUS_M,
            "min_similarity": _MIN_SIMILARITY,
        },
    ).first()


def upgrade() -> None:
    connection = op.get_bind()
    curated = _curated_rows()
    for old_id, spec in MATCH_SPECS.items():
        label = spec[0]
        match = _find_poi(connection, spec)
        if match is None:
            logger.warning("poi_knowledge rematch: KHÔNG tìm thấy POI cho %s", label)
            continue
        (
            _, content_type, intro, intro_source, specialty, historical_context,
            context_source, historical_events, interesting_facts, verified,
        ) = curated[old_id]
        inserted = connection.execute(
            _INSERT_KNOWLEDGE,
            {
                "poi_id": match.id,
                "content_type": content_type,
                "intro": intro,
                "specialty": specialty,
                "historical_context": historical_context,
                "historical_events": json.dumps(historical_events, ensure_ascii=False),
                "interesting_facts": json.dumps(interesting_facts, ensure_ascii=False),
                "source": context_source or intro_source,
                "verified": verified,
            },
        ).first()
        logger.info(
            "poi_knowledge rematch: %s -> %s (%s)%s",
            label, match.id, match.name, "" if inserted else " — đã có kiến thức, bỏ qua",
        )


def downgrade() -> None:
    # Tìm lại cùng các POI và xoá kiến thức của chúng. Không đụng 5 POI seed —
    # kiến thức của chúng do 0021/0022 gắn qua UUID cố định, không phải ở đây.
    connection = op.get_bind()
    for spec in MATCH_SPECS.values():
        match = _find_poi(connection, spec)
        if match is not None:
            connection.execute(
                sa.text("DELETE FROM poi_knowledge WHERE poi_id = CAST(:poi_id AS uuid)"),
                {"poi_id": match.id},
            )

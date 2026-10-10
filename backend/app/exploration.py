"""Bản đồ sương mù: thành phố phủ sương, đi tới đâu sáng tới đó.

Giao diện gửi lên vị trí GPS khi người dùng BẬT chế độ sương mù hoặc đang ở màn
khám phá AR — không ghi ngầm lúc chỉ dùng bản đồ bình thường. Server đổi mỗi
điểm thành ô H3 r9 và chỉ giữ ô (xem migration 0033 về riêng tư).

Điểm có sai số GPS lớn bị bỏ: máy báo ±800 m mà vẫn tính thì một lần mở app
trong nhà mở luôn ô hàng xóm cách vài con phố — sương mù mất ý nghĩa "đã tới".

Đường bao trả về là đường bao HỢP NHẤT (`poi_features.h3_cells_geometry`), không
phải từng ô: giao diện không cần thư viện H3 và không phải vẽ hàng nghìn lục giác.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

import h3
import psycopg
from psycopg.rows import dict_row

from .config import settings
from .poi_features import h3_cells_geometry

DATABASE_URL = settings.database_url

RESOLUTION = 9
# Sai số tối đa còn được tính — một ô r9 rộng ~340 m giữa hai cạnh đối diện.
MAX_ACCURACY_METERS = 60
# Một request mang nhiều điểm (gửi bù khi mất mạng), có trần phòng thủ.
MAX_POINTS_PER_REQUEST = 200


def cells_for_points(points: Iterable[dict[str, Any]]) -> set[str]:
    """Tập ô H3 từ các điểm ``{latitude, longitude, accuracy_meters?}``; bỏ điểm
    sai số lớn hoặc toạ độ ngoài phạm vi. Hàm thuần để kiểm không cần database."""
    cells: set[str] = set()
    for point in points:
        accuracy = point.get("accuracy_meters")
        if accuracy is not None and accuracy > MAX_ACCURACY_METERS:
            continue
        latitude = point.get("latitude")
        longitude = point.get("longitude")
        if latitude is None or longitude is None:
            continue
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            continue
        cells.add(h3.latlng_to_cell(latitude, longitude, RESOLUTION))
    return cells


def area_km2(cell_count: int) -> float:
    """Diện tích xấp xỉ: số ô x diện tích trung bình một ô r9 (~0,105 km²)."""
    return round(cell_count * h3.average_hexagon_area(RESOLUTION, unit="km^2"), 2)


# Mốc theo DIỆN TÍCH đã mở. Như huy hiệu check-in (`checkins.BADGES`), mốc tính
# lúc ĐỌC từ số ô chứ không lưu thành bảng: đổi ngưỡng hay thêm mốc thì người cũ
# tự có ngay. Mốc đầu (0,1 km²) thấp hơn một ô r9 (~0,105 km²) nên đúng một ô là đạt.
MILESTONES: tuple[dict[str, Any], ...] = (
    {"id": "first_light", "title": "Tia sáng đầu tiên", "goal_km2": 0.1},
    {"id": "one_km2", "title": "Một cây số vuông", "goal_km2": 1},
    {"id": "five_km2", "title": "Người đi bộ cần mẫn", "goal_km2": 5},
    {"id": "twenty_five_km2", "title": "Quen mặt cả vùng", "goal_km2": 25},
    {"id": "fifty_km2", "title": "Thổ địa Sài Gòn", "goal_km2": 50},
    {"id": "hundred_km2", "title": "Phủ sáng thành phố", "goal_km2": 100},
)

# Ô cách POI gần nhất hơn mức này thì không gán quận: ngoài vùng có dữ liệu, đoán
# theo POI xa chỉ cho ra con số sai nhưng trông như thật.
DISTRICT_MAX_DISTANCE_METERS = 1500


def _avg_cell_km2() -> float:
    return h3.average_hexagon_area(RESOLUTION, unit="km^2")


def milestone_progress(cell_count: int) -> list[dict[str, Any]]:
    """Tiến độ từng mốc từ số ô đã mở. Hàm thuần để kiểm không cần database."""
    area = cell_count * _avg_cell_km2()
    return [
        {
            "id": milestone["id"],
            "title": milestone["title"],
            "description": f"Khám phá {_format_km2(milestone['goal_km2'])} km²",
            "goalKm2": milestone["goal_km2"],
            "progressKm2": round(min(area, milestone["goal_km2"]), 2),
            "earned": area >= milestone["goal_km2"],
        }
        for milestone in MILESTONES
    ]


def _format_km2(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value).replace(".", ",")


def newly_unlocked(cells_before: int, cells_after: int) -> list[dict[str, Any]]:
    """Mốc vừa đạt NHỜ lượt ghi này, để giao diện chúc mừng đúng lúc (cùng cách
    `checkins.check_in` trả ``unlocked``)."""
    earned_before = {m["id"] for m in milestone_progress(cells_before) if m["earned"]}
    return [m for m in milestone_progress(cells_after) if m["earned"] and m["id"] not in earned_before]


def _connect(database_url: str | None = None):
    return psycopg.connect(database_url or DATABASE_URL, row_factory=dict_row)


def _overview_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    cells = [row["cell"] for row in rows]
    return {
        "resolution": RESOLUTION,
        "cellCount": len(cells),
        "areaKm2": area_km2(len(cells)),
        "todayCount": sum(1 for row in rows if row.get("today")),
        "shape": h3_cells_geometry(cells),
        "milestones": milestone_progress(len(cells)),
    }


def group_by_district(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Gộp ``{cell, district, distanceMeters}`` thành thống kê theo quận.

    Ô không có quận (xa mọi POI) tính vào ``unassigned`` chứ không bị lờ đi, để
    tổng các quận cộng ``unassigned`` luôn khớp ``cellCount``. Hàm thuần.
    """
    counts: dict[str, int] = {}
    unassigned = 0
    for row in rows:
        district = row.get("district")
        distance = row.get("distanceMeters")
        if not district or distance is None or distance > DISTRICT_MAX_DISTANCE_METERS:
            unassigned += 1
            continue
        counts[district] = counts.get(district, 0) + 1
    districts = [
        {"district": name, "cellCount": count, "areaKm2": area_km2(count)}
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    return {"districts": districts, "districtCount": len(districts), "unassignedCells": unassigned}


# Dự án không có đường ranh giới quận (migration 0014 chỉ là dấu mốc, không có
# bảng), nên quận của một ô lấy theo POI GẦN NHẤT với tâm ô. Gần đúng ở sát ranh
# giới — đủ cho "bạn đã đi bao nhiêu ở Quận 1", không đủ cho đo đạc.
_DISTRICT_SQL = """
    SELECT c.cell, nearest.district, nearest.distance AS "distanceMeters"
    FROM unnest(%(cells)s::text[], %(lngs)s::float8[], %(lats)s::float8[]) AS c(cell, lng, lat)
    CROSS JOIN LATERAL (
        SELECT p.district,
               ST_Distance(p.location, ST_SetSRID(ST_MakePoint(c.lng, c.lat), 4326)::geography) AS distance
        FROM pois p
        WHERE p.district IS NOT NULL
        ORDER BY p.location <-> ST_SetSRID(ST_MakePoint(c.lng, c.lat), 4326)::geography
        LIMIT 1
    ) AS nearest
"""


def district_stats(owner_id: str, database_url: str | None = None) -> dict[str, Any]:
    cells = sorted(explored_cells(owner_id, database_url))
    if not cells:
        return group_by_district([])
    centers = [h3.cell_to_latlng(cell) for cell in cells]
    with _connect(database_url) as connection:
        rows = connection.execute(
            _DISTRICT_SQL,
            {
                "cells": cells,
                "lngs": [lng for _, lng in centers],
                "lats": [lat for lat, _ in centers],
            },
        ).fetchall()
    return group_by_district(rows)


_LIST_SQL = """
    SELECT cell, first_seen_on = CURRENT_DATE AS today
    FROM explored_cells
    WHERE owner_id = %(owner)s
"""


def overview(owner_id: str, database_url: str | None = None) -> dict[str, Any]:
    with _connect(database_url) as connection:
        rows = connection.execute(_LIST_SQL, {"owner": owner_id}).fetchall()
    return _overview_from_rows([dict(row) for row in rows])


def empty_overview() -> dict[str, Any]:
    return _overview_from_rows([])


def record(
    owner_id: str,
    points: Iterable[dict[str, Any]],
    database_url: str | None = None,
) -> dict[str, Any]:
    """Ghi các ô vừa đi qua. Trả tổng quan mới kèm ``added`` — số ô MỚI mở
    (0 khi chỉ đi lại chỗ cũ), để giao diện khỏi vẽ lại khi không có gì đổi."""
    cells = cells_for_points(points)
    with _connect(database_url) as connection:
        added = 0
        if cells:
            cursor = connection.execute(
                """
                INSERT INTO explored_cells (owner_id, cell)
                SELECT %(owner)s, unnest(%(cells)s::text[])
                ON CONFLICT DO NOTHING
                """,
                {"owner": owner_id, "cells": sorted(cells)},
            )
            added = cursor.rowcount
        rows = connection.execute(_LIST_SQL, {"owner": owner_id}).fetchall()
    overview_now = _overview_from_rows([dict(row) for row in rows])
    return {
        **overview_now,
        "added": added,
        "unlocked": newly_unlocked(overview_now["cellCount"] - added, overview_now["cellCount"]),
    }


def explored_cells(owner_id: str, database_url: str | None = None) -> set[str]:
    """Tập ô đã đi qua, không kèm đường bao — dùng để gợi ý, không để vẽ."""
    with _connect(database_url) as connection:
        rows = connection.execute(
            "SELECT cell FROM explored_cells WHERE owner_id = %(owner)s", {"owner": owner_id}
        ).fetchall()
    return {row["cell"] for row in rows}


def mix_unexplored(
    candidates: list[dict[str, Any]],
    explored: set[str],
    limit: int,
    min_share: float = 0.5,
) -> list[dict[str, Any]]:
    """Chọn ``limit`` gợi ý, dành ít nhất ``min_share`` chỗ cho địa điểm ở ô CHƯA đi.

    Gắn ``unexplored`` cho từng ứng viên rồi giữ nguyên thứ tự xếp hạng gốc trong
    kết quả: chỉ đổi chỗ nào được chọn, không đảo thứ tự giữa những chỗ được chọn, nên
    điểm liên quan vẫn là thứ quyết định. Chưa có ô nào (người dùng chưa từng bật
    sương mù/AR) thì không gắn gì — "mọi nơi đều chưa tới" không phải thông tin.
    """
    if not explored:
        return [{**poi, "unexplored": False} for poi in candidates[:limit]]

    tagged = []
    for poi in candidates:
        cell = h3.latlng_to_cell(poi["latitude"], poi["longitude"], RESOLUTION)
        tagged.append({**poi, "unexplored": cell not in explored})

    quota = min(sum(1 for poi in tagged if poi["unexplored"]), math.ceil(limit * min_share))
    chosen: set[int] = set()
    for index, poi in enumerate(tagged):
        if len(chosen) >= quota:
            break
        if poi["unexplored"]:
            chosen.add(index)
    for index in range(len(tagged)):
        if len(chosen) >= limit:
            break
        chosen.add(index)
    return [tagged[index] for index in sorted(chosen)]


def clear(owner_id: str, database_url: str | None = None) -> int:
    with _connect(database_url) as connection:
        return connection.execute(
            "DELETE FROM explored_cells WHERE owner_id = %(owner)s", {"owner": owner_id}
        ).rowcount


def transfer_owner(from_owner: str, to_owner: str, database_url: str | None = None) -> int:
    """Gộp ô của phiên ẩn danh vào tài khoản vừa đăng nhập (hợp hai tập, giữ ngày
    tới sớm hơn), rồi xoá bản của phiên — không để lại bản sao vị trí mồ côi."""
    with _connect(database_url) as connection:
        with connection.transaction():
            moved = connection.execute(
                """
                INSERT INTO explored_cells (owner_id, cell, first_seen_on)
                SELECT %(to_owner)s, cell, first_seen_on
                FROM explored_cells WHERE owner_id = %(from_owner)s
                ON CONFLICT (owner_id, cell) DO UPDATE
                SET first_seen_on = LEAST(explored_cells.first_seen_on, EXCLUDED.first_seen_on)
                """,
                {"from_owner": from_owner, "to_owner": to_owner},
            ).rowcount
            connection.execute(
                "DELETE FROM explored_cells WHERE owner_id = %(from_owner)s",
                {"from_owner": from_owner},
            )
    return moved

"""Check-in khi khám phá bằng camera (AR) và huy hiệu đi kèm.

Người dùng giơ camera, thấy thẻ địa điểm, đi tới nơi rồi bấm Check-in. Khác Săn
địa danh (`app/explore.py`): nhận MỌI POI, không cần ảnh — chỉ cần đứng đủ gần.

Khoảng cách tính bằng PostGIS từ ``pois.location``, KHÔNG nhận từ client: giao
diện AR đã tự tính khoảng cách để bật nút, nhưng con số đó chỉ để hiển thị. Toạ
độ người dùng vẫn do trình duyệt báo nên KHÔNG chống được giả lập vị trí —
cùng giới hạn đã ghi ở `app/explore.py`.

Huy hiệu tính lúc ĐỌC từ danh sách check-in, không lưu thành bảng: đổi ngưỡng
hay thêm huy hiệu mới thì người cũ tự có ngay, không cần chạy migration dữ liệu.
"""

from __future__ import annotations

from collections import Counter
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from .config import settings
from .poi_features import CATEGORY_MAP

DATABASE_URL = settings.database_url

# Toạ độ POI là MỘT điểm; với quán cà phê, đứng trong quán đã cách điểm đó vài
# chục mét. Khu đất rộng (công viên, trường đại học) thì đứng ở cổng đã cách
# tâm hàng trăm mét — cùng lý do với `explore.WIDE_CATEGORIES`.
CHECKIN_RADIUS_METERS = 50
WIDE_CATEGORY_RADIUS = {
    "park": 350,
    "theme_park": 350,
    "university": 200,
    "shopping_mall": 120,
    "sports_field": 120,
    "market": 100,
}
# Cộng thêm sai số GPS, có trần — thấp hơn Săn địa danh (60 m) vì bán kính gốc
# ở đây nhỏ: sai số 30 m đã gần gấp đôi bán kính một quán.
MAX_ACCURACY_ALLOWANCE_METERS = 30

# Không biến việc tới bệnh viện, nhà thuốc, đồn công an thành trò sưu tập —
# cùng nguyên tắc loại "medical" khỏi Săn địa danh.
EXCLUDED_CATEGORIES = frozenset({"hospital", "pharmacy", "dentist", "police"})

_CATEGORY_LABELS = {category: label for category, label in CATEGORY_MAP.values()}

# Huy hiệu: ``categories`` rỗng = đếm mọi check-in; ``distinct`` = đếm số LOẠI
# địa điểm khác nhau thay vì số lượt.
BADGES: tuple[dict[str, Any], ...] = (
    {
        "id": "first_step",
        "title": "Bước chân đầu tiên",
        "description": "Check-in địa điểm đầu tiên",
        "icon": "footprints",
        "goal": 1,
        "categories": (),
    },
    {
        "id": "coffee_hunter",
        "title": "Thợ săn cà phê",
        "description": "Check-in 3 quán cà phê",
        "icon": "coffee",
        "goal": 3,
        "categories": ("cafe",),
    },
    {
        "id": "foodie",
        "title": "Tín đồ ẩm thực",
        "description": "Check-in 5 quán ăn",
        "icon": "utensils",
        "goal": 5,
        "categories": ("restaurant", "bakery"),
    },
    {
        "id": "culture_lover",
        "title": "Người yêu văn hoá",
        "description": "Check-in 3 bảo tàng, nhà hát, thư viện hay địa danh",
        "icon": "landmark",
        "goal": 3,
        "categories": ("museum", "theatre", "library", "gallery", "landmark", "place_of_worship"),
    },
    {
        "id": "green_breath",
        "title": "Hít thở không khí",
        "description": "Check-in 2 công viên",
        "icon": "trees",
        "goal": 2,
        "categories": ("park", "theme_park", "playground"),
    },
    {
        "id": "variety",
        "title": "Đa sắc màu",
        "description": "Check-in 5 loại địa điểm khác nhau",
        "icon": "palette",
        "goal": 5,
        "categories": (),
        "distinct": True,
    },
    {
        "id": "explorer",
        "title": "Nhà thám hiểm",
        "description": "Check-in 10 địa điểm",
        "icon": "compass",
        "goal": 10,
        "categories": (),
    },
)


def is_uuid(value: str | None) -> bool:
    try:
        UUID(str(value))
    except (ValueError, TypeError):
        return False
    return True


def allowed_distance(category: str | None, accuracy_meters: float | None) -> float:
    base = WIDE_CATEGORY_RADIUS.get(category or "", CHECKIN_RADIUS_METERS)
    allowance = min(max(accuracy_meters or 0.0, 0.0), MAX_ACCURACY_ALLOWANCE_METERS)
    return float(base + allowance)


def badge_progress(categories: list[str]) -> list[dict[str, Any]]:
    """Tiến độ từng huy hiệu từ danh sách ``category`` của các lượt check-in.

    Hàm thuần để kiểm được không cần database; ``summary`` và ``check_in`` đều
    đi qua đây nên giao diện và lượt check-in luôn thấy cùng một kết quả.
    """
    counts = Counter(categories)
    result = []
    for badge in BADGES:
        if badge.get("distinct"):
            value = len(counts)
        elif badge["categories"]:
            value = sum(counts[category] for category in badge["categories"])
        else:
            value = len(categories)
        result.append(
            {
                "id": badge["id"],
                "title": badge["title"],
                "description": badge["description"],
                "icon": badge["icon"],
                "goal": badge["goal"],
                "progress": min(value, badge["goal"]),
                "earned": value >= badge["goal"],
            }
        )
    return result


def _connect(database_url: str | None = None):
    return psycopg.connect(database_url or DATABASE_URL, row_factory=dict_row)


_POI_SQL = """
    SELECT p.id::text AS "poiId", p.name, p.category,
           ST_Distance(p.location, ST_SetSRID(ST_MakePoint(%(lng)s, %(lat)s), 4326)::geography)
               AS "distanceMeters"
    FROM pois p
    WHERE p.id = %(poi)s
"""

_INSERT_SQL = """
    INSERT INTO poi_checkins (owner_id, poi_id, name, category, location, distance_meters, accuracy_meters)
    SELECT %(owner)s, p.id, p.name, p.category, p.location, %(distance)s, %(accuracy)s
    FROM pois p
    WHERE p.id = %(poi)s
    ON CONFLICT (owner_id, poi_id) WHERE poi_id IS NOT NULL DO NOTHING
    RETURNING checked_in_at AS "checkedInAt"
"""

_LIST_SQL = """
    SELECT poi_id::text AS "poiId", name, category,
           ST_Y(location::geometry) AS latitude,
           ST_X(location::geometry) AS longitude,
           checked_in_at AS "checkedInAt"
    FROM poi_checkins
    WHERE owner_id = %(owner)s
    ORDER BY checked_in_at DESC
"""


def _rows_to_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    checkins = [
        {**row, "categoryLabel": _CATEGORY_LABELS.get(row["category"], row["category"])}
        for row in rows
    ]
    return {
        "total": len(checkins),
        "checkins": checkins,
        "badges": badge_progress([row["category"] for row in rows]),
    }


def badge_summary_empty() -> dict[str, Any]:
    return _rows_to_summary([])


def summary(owner_id: str, database_url: str | None = None) -> dict[str, Any]:
    with _connect(database_url) as connection:
        rows = connection.execute(_LIST_SQL, {"owner": owner_id}).fetchall()
    return _rows_to_summary([dict(row) for row in rows])


def check_in(
    owner_id: str,
    poi_id: str,
    latitude: float,
    longitude: float,
    accuracy_meters: float | None,
    database_url: str | None = None,
) -> dict[str, Any]:
    """Một lượt check-in. Luôn trả dict có ``status``:

    ``not_found`` · ``not_allowed`` (loại bị loại trừ) · ``too_far`` ·
    ``checked_in`` (lần đầu) · ``already`` (đã check-in POI này trước đó).

    Lần đầu thì kèm ``unlocked``: huy hiệu vừa đạt NHỜ lượt này, để giao diện
    chúc mừng đúng lúc thay vì tự so hai danh sách.
    """
    if not is_uuid(poi_id):
        return {"status": "not_found"}
    with _connect(database_url) as connection:
        with connection.transaction():
            poi = connection.execute(
                _POI_SQL, {"lat": latitude, "lng": longitude, "poi": poi_id}
            ).fetchone()
            if poi is None:
                return {"status": "not_found"}

            distance = float(poi["distanceMeters"])
            allowed = allowed_distance(poi["category"], accuracy_meters)
            base = {
                "poiId": poi_id,
                "name": poi["name"],
                "distanceMeters": round(distance, 1),
                "allowedMeters": round(allowed, 1),
            }
            if poi["category"] in EXCLUDED_CATEGORIES:
                return {**base, "status": "not_allowed"}
            if distance > allowed:
                return {**base, "status": "too_far"}

            before = connection.execute(
                "SELECT category FROM poi_checkins WHERE owner_id = %(owner)s", {"owner": owner_id}
            ).fetchall()
            inserted = connection.execute(
                _INSERT_SQL,
                {"owner": owner_id, "poi": poi_id, "distance": distance, "accuracy": accuracy_meters},
            ).fetchone()
            rows = connection.execute(_LIST_SQL, {"owner": owner_id}).fetchall()

    result = _rows_to_summary([dict(row) for row in rows])
    if inserted is None:
        return {**base, **result, "status": "already", "unlocked": []}
    earned_before = {
        badge["id"] for badge in badge_progress([row["category"] for row in before]) if badge["earned"]
    }
    unlocked = [badge for badge in result["badges"] if badge["earned"] and badge["id"] not in earned_before]
    return {**base, **result, "status": "checked_in", "unlocked": unlocked}


def transfer_owner(from_owner: str, to_owner: str, database_url: str | None = None) -> int:
    """Chuyển check-in của phiên ẩn danh sang tài khoản vừa đăng nhập. Bỏ qua POI
    tài khoản đã check-in — mỗi người một lượt cho mỗi POI."""
    with _connect(database_url) as connection:
        cursor = connection.execute(
            """
            UPDATE poi_checkins AS c SET owner_id = %(to_owner)s
            WHERE c.owner_id = %(from_owner)s
              AND NOT EXISTS (
                  SELECT 1 FROM poi_checkins AS t
                  WHERE t.owner_id = %(to_owner)s AND t.poi_id = c.poi_id
              )
            """,
            {"from_owner": from_owner, "to_owner": to_owner},
        )
        return cursor.rowcount

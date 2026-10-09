"""Tìm trạm xăng — theo hãng (Petrolimex, PVOIL, Saigon Petro, Comeco), đang mở
cửa, và THỜI GIAN CHẠY XE THẬT tới trạm.

Cây xăng là POI thường (``category = 'fuel'``, từ ``amenity=fuel`` của OSM),
không có bảng riêng như bãi xe/trạm sạc. Thẻ gốc (hãng, loại xăng, giờ mở) đọc
thẳng từ ``poi_source_records.raw_payload``. Cách xếp hạng giống trạm sạc (xem
`app/charging.py`): người tìm cây xăng CHẠY XE tới đó, nên thước đo đúng là thời
gian chạy xe theo đường thật (OSRM /table), không phải đường chim bay.

Trung thực về dữ liệu (đo 2026-10-09, 520 cây xăng ở TP.HCM): chỉ ~45% ghi hãng
trong thẻ ``brand`` (phần còn lại nhận theo tên trạm), 18 trạm ghi loại xăng,
45 trạm ghi giờ mở, 362 trạm KHÔNG có địa chỉ — địa chỉ khi đó là tên đường sát
trạm (OSRM /nearest), đánh dấu ``addressApprox`` để giao diện ghi "ước lượng".
"""

from __future__ import annotations

import unicodedata
from typing import Any

import psycopg
from psycopg.rows import dict_row

from . import charging, directions
from .config import settings
from .opening_hours import opening_status
from .spatio_temporal import DEFAULT_TIMEZONE

VEHICLES = ("motorbike", "car")
DEFAULT_RADIUS_METERS = 5_000
# Cây xăng dày hơn trạm sạc nhiều, 25 trạm gần nhất (chim bay) là đủ để thứ tự
# theo thời gian chạy xe có nghĩa.
MAX_ROUTED = 25

# (mã lọc, tên hiển thị, dấu hiệu nhận ra trong brand/operator/tên — đã bỏ dấu,
# viết thường, bỏ khoảng trắng và gạch nối).
BRANDS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("petrolimex", "Petrolimex", ("petrolimex",)),
    ("pvoil", "PVOIL", ("pvoil",)),
    ("saigon_petro", "Saigon Petro", ("saigonpetro",)),
    ("comeco", "Comeco", ("comeco",)),
    ("mipec", "Mipec", ("mipec",)),
)
BRAND_FILTERS = ("any", *(code for code, _, _ in BRANDS), "other")

# Thẻ `fuel:*` của OSM → tên người Việt quen gọi ở cột bơm.
FUEL_LABELS = (
    ("octane_95", "RON 95"),
    ("octane_92", "RON 92"),
    ("e5", "E5"),
    ("e10", "E10"),
    ("octane_98", "RON 98"),
    ("diesel", "Dầu DO"),
    ("biodiesel", "Dầu sinh học"),
    ("lpg", "LPG"),
)


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return "".join(ch for ch in stripped if ch.isalnum())


def brand_of(name: str | None, tags: dict[str, Any]) -> tuple[str, str | None]:
    """``(mã hãng, tên hiển thị)``. Nhận theo thẻ ``brand``/``operator`` HOẶC
    tên trạm — OSM ghi tuỳ người nhập ("Petrolimex", "Cửa hàng xăng dầu
    Petrolimex số 12", "PV Oil"). Không khớp hãng lớn nào: mã ``other``, tên
    hiển thị là ``brand``/``operator`` thô nếu có."""
    text = _fold(" ".join(str(tags.get(key) or "") for key in ("brand", "operator")) + " " + (name or ""))
    for code, label, markers in BRANDS:
        if any(marker in text for marker in markers):
            return code, label
    return "other", (tags.get("brand") or tags.get("operator") or None)


def fuels_of(tags: dict[str, Any]) -> list[str]:
    return [label for key, label in FUEL_LABELS if tags.get(f"fuel:{key}") == "yes"]


def filter_stations(stations: list[dict[str, Any]], brand: str = "any", open_now: bool = False) -> list[dict[str, Any]]:
    kept = []
    for station in stations:
        if brand != "any" and station["brandCode"] != brand:
            continue
        # Như trạm sạc: "Đang mở" chỉ loại trạm CHẮC CHẮN đang đóng — đa số
        # cây xăng không ghi giờ, giao diện ghi "chưa rõ giờ".
        if open_now and station["hours"]["openNow"] is False:
            continue
        kept.append(station)
    return kept


_SEARCH_QUERY = """
SELECT p.id::text AS id, p.name, p.address, p.district, p.opening_hours, p.timezone,
       ST_Y(p.location::geometry) AS latitude, ST_X(p.location::geometry) AS longitude,
       ST_Distance(p.location, ST_SetSRID(ST_Point(%(lng)s, %(lat)s), 4326)::geography) AS "distanceMeters",
       COALESCE(
           (SELECT r.raw_payload->'tags' FROM poi_source_records r
            WHERE r.canonical_poi_id = p.id AND r.source = 'openstreetmap' LIMIT 1),
           '{}'::jsonb
       ) AS tags
FROM pois p
WHERE p.category = 'fuel'
  AND ST_DWithin(p.location, ST_SetSRID(ST_Point(%(lng)s, %(lat)s), 4326)::geography, %(radius)s)
ORDER BY "distanceMeters"
LIMIT 300
"""


def build_station(row: dict[str, Any]) -> dict[str, Any]:
    tags = row["tags"] or {}
    brand_code, brand_label = brand_of(row["name"], tags)
    status = opening_status(row["opening_hours"], row["timezone"] or DEFAULT_TIMEZONE)
    return {
        "id": row["id"],
        "name": row["name"],
        "address": (row["address"] or "").strip() or None,
        "streetAddress": None,
        "district": row["district"],
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "distanceMeters": round(row["distanceMeters"]),
        "brandCode": brand_code,
        "brand": brand_label,
        "fuels": fuels_of(tags),
        "compressedAir": tags.get("compressed_air") == "yes",
        "hours": {
            "raw": (row["opening_hours"] or {}).get("raw"),
            "openNow": status["openNow"],
            "closesInMinutes": status["closesInMinutes"],
        },
    }


def search_stations(
    *,
    latitude: float,
    longitude: float,
    vehicle: str = "motorbike",
    brand: str = "any",
    open_now: bool = False,
    radius: int = DEFAULT_RADIUS_METERS,
    limit: int = 20,
) -> dict[str, Any]:
    if vehicle not in VEHICLES:
        raise ValueError(f"vehicle phải là một trong {VEHICLES}")
    if brand not in BRAND_FILTERS:
        raise ValueError(f"brand phải là một trong {BRAND_FILTERS}")
    with psycopg.connect(settings.database_url, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(_SEARCH_QUERY, {"lat": latitude, "lng": longitude, "radius": radius})
            rows = cursor.fetchall()

    candidates = filter_stations([build_station(row) for row in rows], brand, open_now)
    routed = candidates[:MAX_ROUTED]
    table = (
        directions.duration_table(
            [(latitude, longitude)], [(item["latitude"], item["longitude"]) for item in routed], vehicle
        )
        if routed
        else None
    )
    approximate = charging.attach_drive_times(routed, table, vehicle)
    routed.sort(key=lambda item: (item["driveMinutes"] is None, item["driveMinutes"] or 0, item["distanceMeters"]))
    results = routed[:limit]
    # Chỉ tra tên đường cho trạm SẼ hiển thị (có cache Redis, gọi lại gần như
    # miễn phí).
    for station in results:
        if station["address"] is None:
            station["streetAddress"] = directions.nearest_streets(station["latitude"], station["longitude"])
    return {
        "vehicle": vehicle,
        "brand": brand,
        "openNow": open_now,
        "radius": radius,
        "approximate": approximate,
        "candidates": len(candidates),
        "results": results,
    }

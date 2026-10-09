"""Tìm cửa hàng tiện lợi — theo chuỗi (Circle K, FamilyMart, GS25, 7-Eleven,
Ministop, WinMart+…), đang mở cửa, và THỜI GIAN ĐI THẬT tới cửa hàng.

Cửa hàng tiện lợi là POI thường (``category = 'convenience'``, từ
``shop=convenience|variety_store`` của OSM). Khác cây xăng: cửa hàng tiện lợi dày
đặc và thường ở ngay quanh người dùng, nên mặc định xếp theo thời gian ĐI BỘ
(OSRM hồ sơ foot); chọn "Xe máy" thì xếp theo thời gian chạy xe.

Trung thực về dữ liệu (đo 2026-10-10, 2.921 cửa hàng ở TP.HCM): chỉ ~640 thuộc
chuỗi lớn — phần còn lại là tạp hoá, bách hoá nhỏ ("Tạp hóa cô Mai"), nên có lựa
chọn "Chuỗi tiện lợi" để chỉ giữ chuỗi. 115 cửa hàng ghi giờ mở (53 ghi 24/7),
2.088 KHÔNG có địa chỉ — địa chỉ khi đó là tên đường sát cửa hàng (ước lượng),
như `app/fuel.py`.
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row

from . import charging
from .config import settings
from .fuel import _fold
from .opening_hours import opening_status
from .spatio_temporal import DEFAULT_TIMEZONE

MODES = ("foot", "motorbike")
DEFAULT_RADIUS_METERS = 3_000
MAX_ROUTED = 25

# (mã lọc, tên hiển thị, dấu hiệu nhận ra trong brand/operator/tên — đã bỏ dấu,
# viết thường, bỏ khoảng trắng và ký tự đặc biệt: "7-Eleven" → "7eleven",
# "B's Mart" → "bsmart", "Co.op Food" → "coopfood").
CHAINS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("circle_k", "Circle K", ("circlek",)),
    ("familymart", "FamilyMart", ("familymart",)),
    ("gs25", "GS25", ("gs25",)),
    ("seven_eleven", "7-Eleven", ("7eleven", "seveneleven")),
    ("ministop", "Ministop", ("ministop",)),
    ("winmart", "WinMart+", ("winmart", "vinmart")),
    ("bach_hoa_xanh", "Bách Hóa Xanh", ("bachhoaxanh",)),
    ("coop_food", "Co.op Food", ("coopfood",)),
    ("bsmart", "B's mart", ("bsmart",)),
    ("shop_go", "Shop&Go", ("shopgo",)),
    ("satrafoods", "Satrafoods", ("satrafood",)),
)
# Chuỗi đồ gia dụng / lifestyle mà OSM gắn `shop=variety_store` (→ danh mục
# convenience): không bán đồ ăn uống, người tìm "cửa hàng tiện lợi" không cần.
NOT_CONVENIENCE = ("miniso", "daiso", "muji")
# "chain" = mọi chuỗi ở trên; "other" = tạp hoá / cửa hàng nhỏ không thuộc chuỗi.
BRAND_FILTERS = ("any", "chain", *(code for code, _, _ in CHAINS), "other")


def chain_of(name: str | None, tags: dict[str, Any]) -> tuple[str, str | None]:
    """``(mã chuỗi, tên hiển thị)`` theo thẻ ``brand``/``operator`` HOẶC tên
    cửa hàng. Không thuộc chuỗi nào: mã ``other``, tên hiển thị ``None``."""
    text = _fold(" ".join(str(tags.get(key) or "") for key in ("brand", "operator")) + " " + (name or ""))
    for code, label, markers in CHAINS:
        if any(marker in text for marker in markers):
            return code, label
    return "other", None


def is_convenience(name: str | None, tags: dict[str, Any]) -> bool:
    text = _fold(" ".join(str(tags.get(key) or "") for key in ("brand", "operator")) + " " + (name or ""))
    return not any(marker in text for marker in NOT_CONVENIENCE)


def filter_stores(stores: list[dict[str, Any]], brand: str = "any", open_now: bool = False) -> list[dict[str, Any]]:
    kept = []
    for store in stores:
        if brand == "chain" and store["brandCode"] == "other":
            continue
        if brand not in ("any", "chain") and store["brandCode"] != brand:
            continue
        # "Đang mở" chỉ loại cửa hàng CHẮC CHẮN đang đóng — đa số không ghi giờ.
        if open_now and store["hours"]["openNow"] is False:
            continue
        kept.append(store)
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
WHERE p.category = 'convenience'
  AND ST_DWithin(p.location, ST_SetSRID(ST_Point(%(lng)s, %(lat)s), 4326)::geography, %(radius)s)
ORDER BY "distanceMeters"
LIMIT 400
"""


def build_store(row: dict[str, Any]) -> dict[str, Any]:
    tags = row["tags"] or {}
    brand_code, brand_label = chain_of(row["name"], tags)
    hours = row["opening_hours"] or {}
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
        "hours": {
            "raw": hours.get("raw"),
            "openNow": status["openNow"],
            "closesInMinutes": status["closesInMinutes"],
            "alwaysOpen": bool(hours.get("alwaysOpen")),
        },
    }


def search_stores(
    *,
    latitude: float,
    longitude: float,
    mode: str = "foot",
    brand: str = "any",
    open_now: bool = False,
    radius: int = DEFAULT_RADIUS_METERS,
    limit: int = 20,
) -> dict[str, Any]:
    if mode not in MODES:
        raise ValueError(f"mode phải là một trong {MODES}")
    if brand not in BRAND_FILTERS:
        raise ValueError(f"brand phải là một trong {BRAND_FILTERS}")
    with psycopg.connect(settings.database_url, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(_SEARCH_QUERY, {"lat": latitude, "lng": longitude, "radius": radius})
            rows = cursor.fetchall()

    stores = [build_store(row) for row in rows if is_convenience(row["name"], row["tags"] or {})]
    candidates = filter_stores(stores, brand, open_now)
    results, approximate = charging.rank_by_travel_time(latitude, longitude, candidates, mode, limit, MAX_ROUTED)
    return {
        "mode": mode,
        "brand": brand,
        "openNow": open_now,
        "radius": radius,
        "approximate": approximate,
        "candidates": len(candidates),
        "results": results,
    }

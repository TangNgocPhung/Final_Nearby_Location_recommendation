"""Tìm nhà vệ sinh — WC công cộng, cộng các nơi có WC cho khách (cây xăng,
trung tâm thương mại, quán ghi "có WC"), xếp theo THỜI GIAN ĐI THẬT tới nơi.

Trung thực về dữ liệu (đo 2026-10-10, bbox ``OSM_BBOX`` toàn vùng): OSM chỉ có
157 điểm ``amenity=toilets`` (~87 trong bán kính 12 km quanh trung tâm) — 147
không tên, 26 ghi miễn phí, 11 ghi lối xe lăn. Chừng đó
quá thưa để "tìm WC gần nhất" có ích, nên bổ sung các nguồn có WC thật nhưng
không phải WC công cộng, và LUÔN nói rõ nguồn của từng kết quả:

- ``public``: WC công cộng (``amenity=toilets``; ``access=private|no`` đã bị
  loại khi nhập, xem `poi_features.normalize_osm_element`).
- ``fuel``: cây xăng — đa số có WC cho khách, nhưng OSM hầu như không ghi, nên
  giao diện phải ghi "thường có", không khẳng định.
- ``mall``: trung tâm thương mại — CHỈ ``shop=mall`` hoặc bách hoá lớn có tên
  thật (xem ``poi_features.is_real_mall``). ``shop=department_store`` ở VN bị dùng tràn lan
  cho tạp hoá ("bách hoá" dịch thẳng): 520 điểm, gần hết là "Tạp hóa cô Mai",
  cả cửa hàng Tiffany (đo 2026-10-10) — coi hết là TTTM có WC là sai.
- ``venue``: địa điểm khác có thẻ ``toilets=yes`` (quán cà phê, siêu thị...) —
  thường chỉ dành cho khách.

Nơi có thẻ ``toilets=no`` bị loại ở mọi nguồn.
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row

from . import charging
from .config import settings
from .opening_hours import opening_status
from .poi_features import is_real_mall
from .spatio_temporal import DEFAULT_TIMEZONE

MODES = ("foot", "motorbike")
SOURCES = ("all", "public")
DEFAULT_RADIUS_METERS = 3_000
MAX_ROUTED = 25

KIND_LABELS = {
    "public": "WC công cộng",
    "fuel": "Cây xăng — thường có WC",
    "mall": "Trung tâm thương mại",
    "venue": "Có WC cho khách",
}


def kind_of(category: str, name: str | None = None, tags: dict[str, Any] | None = None) -> str | None:
    """Nguồn WC của một địa điểm; ``None`` khi không nhận nó là nơi có WC
    (``shop=department_store`` mà thật ra là tạp hoá, và không ghi
    ``toilets=yes``)."""
    tags = tags or {}
    if category == "toilets":
        return "public"
    if category == "fuel":
        return "fuel"
    if category == "shopping_mall" and is_real_mall(name, tags):
        return "mall"
    if tags.get("toilets") == "yes":
        return "venue"
    return None


def fee_of(tags: dict[str, Any]) -> bool | None:
    """``True`` thu phí, ``False`` miễn phí, ``None`` chưa rõ. OSM ghi phí ở
    ``fee`` hoặc gián tiếp qua ``charge`` (vd "2000 VND")."""
    fee = str(tags.get("fee") or "").lower()
    if fee in ("yes", "donation"):
        return True
    if fee == "no":
        return False
    return True if tags.get("charge") else None


def filter_toilets(
    items: list[dict[str, Any]],
    source: str = "all",
    free_only: bool = False,
    wheelchair: bool = False,
    open_now: bool = False,
) -> list[dict[str, Any]]:
    kept = []
    for item in items:
        if source == "public" and item["kind"] != "public":
            continue
        # Như "Đang mở" ở trạm xăng: các bộ lọc chỉ loại nơi CHẮC CHẮN không
        # đạt — phần lớn WC không ghi phí/lối xe lăn, loại hết thì gần như rỗng.
        if free_only and item["fee"] is True:
            continue
        if wheelchair and item["wheelchair"] == "no":
            continue
        if open_now and item["hours"]["openNow"] is False:
            continue
        kept.append(item)
    return kept


_SEARCH_QUERY = """
SELECT p.id::text AS id, p.name, p.address, p.district, p.category, p.opening_hours, p.timezone,
       p.amenities->>'toilets' AS "toiletsTag",
       ST_Y(p.location::geometry) AS latitude, ST_X(p.location::geometry) AS longitude,
       ST_Distance(p.location, ST_SetSRID(ST_Point(%(lng)s, %(lat)s), 4326)::geography) AS "distanceMeters",
       COALESCE(
           (SELECT r.raw_payload->'tags' FROM poi_source_records r
            WHERE r.canonical_poi_id = p.id AND r.source = 'openstreetmap' LIMIT 1),
           '{}'::jsonb
       ) AS tags
FROM pois p
WHERE (p.category IN ('toilets', 'fuel', 'shopping_mall') OR p.amenities->>'toilets' = 'yes')
  AND COALESCE(p.amenities->>'toilets', '') <> 'no'
  AND ST_DWithin(p.location, ST_SetSRID(ST_Point(%(lng)s, %(lat)s), 4326)::geography, %(radius)s)
ORDER BY "distanceMeters"
LIMIT 400
"""


def build_toilet(row: dict[str, Any]) -> dict[str, Any] | None:
    tags = row["tags"] or {}
    # POI không từ OSM không có thẻ gốc; `amenities.toilets` có ở mọi nguồn.
    kind = kind_of(row["category"], row["name"], {**tags, "toilets": row.get("toiletsTag") or tags.get("toilets")})
    if kind is None:
        return None
    status = opening_status(row["opening_hours"], row["timezone"] or DEFAULT_TIMEZONE)
    # Thẻ chi tiết của WC: với WC công cộng là thẻ gốc, với nơi khác là thẻ
    # `toilets:*` (vd `toilets:wheelchair=yes` ở một quán cà phê).
    prefix = "" if kind == "public" else "toilets:"
    wheelchair = tags.get(f"{prefix}wheelchair")
    return {
        "id": row["id"],
        "name": row["name"],
        "address": (row["address"] or "").strip() or None,
        "streetAddress": None,
        "district": row["district"],
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "distanceMeters": round(row["distanceMeters"]),
        "kind": kind,
        "kindLabel": KIND_LABELS[kind],
        # WC công cộng ghi rõ chỉ cho khách thì phải nói, đừng để người ta tới
        # rồi bị từ chối; nơi kinh doanh thì mặc định là cho khách.
        "customersOnly": kind == "venue" or tags.get("access") == "customers",
        "fee": fee_of({"fee": tags.get(f"{prefix}fee"), "charge": tags.get(f"{prefix}charge")}),
        "wheelchair": wheelchair if wheelchair in ("yes", "limited", "no") else None,
        "changingTable": tags.get("changing_table") == "yes",
        "hours": {
            "raw": (row["opening_hours"] or {}).get("raw"),
            "openNow": status["openNow"],
            "closesInMinutes": status["closesInMinutes"],
        },
    }


def search_toilets(
    *,
    latitude: float,
    longitude: float,
    mode: str = "foot",
    source: str = "all",
    free_only: bool = False,
    wheelchair: bool = False,
    open_now: bool = False,
    radius: int = DEFAULT_RADIUS_METERS,
    limit: int = 20,
) -> dict[str, Any]:
    if mode not in MODES:
        raise ValueError(f"mode phải là một trong {MODES}")
    if source not in SOURCES:
        raise ValueError(f"source phải là một trong {SOURCES}")
    with psycopg.connect(settings.database_url, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(_SEARCH_QUERY, {"lat": latitude, "lng": longitude, "radius": radius})
            rows = cursor.fetchall()

    built = [item for item in (build_toilet(row) for row in rows) if item is not None]
    candidates = filter_toilets(built, source, free_only, wheelchair, open_now)
    results, approximate = charging.rank_by_travel_time(latitude, longitude, candidates, mode, limit, MAX_ROUTED)
    return {
        "mode": mode,
        "source": source,
        "radius": radius,
        "approximate": approximate,
        "candidates": len(candidates),
        "publicCount": sum(1 for item in candidates if item["kind"] == "public"),
        "results": results,
    }

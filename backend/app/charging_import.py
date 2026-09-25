"""Nhập trạm sạc xe điện từ Open Charge Map (openchargemap.org).

OSM chỉ có 25 trạm sạc trong bbox TP.HCM (đo 2026-09-25) — quá ít so với thực
tế. Open Charge Map là cơ sở dữ liệu trạm sạc mở (giấy phép CC BY-SA 4.0),
có loại cổng sạc, công suất và giá. API cần key miễn phí: đăng ký tại
https://openchargemap.org → My Profile → My Apps, đặt vào biến môi trường
``OPENCHARGEMAP_API_KEY``.

Mỗi trạm OCM được chuyển thành một phần tử KIỂU OSM (``amenity=
charging_station``, ``socket:type2=2``, ``charge=...``) rồi đi qua đúng đường
chuẩn hoá của OSM — một bộ đọc duy nhất cho cả hai nguồn. Trạm OCM nằm trong
40 m quanh một trạm đã có được gộp vào trạm đó (hai nguồn thường cùng mô tả
một trạm thật, nhưng đặt tên khác nhau nên không gộp theo tên được).
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

import psycopg
from psycopg.rows import dict_row

from . import parking
from .poi_features import normalize_osm_element
from .poi_import import _insert_poi, _upsert_lineage

API_URL = "https://api.openchargemap.io/v3/poi"
MERGE_RADIUS_M = 40

# Tiêu đề loại cổng của OCM → khoá `socket:*` của OSM.
_CONNECTION_KEYS = (
    ("ccs (type 2)", "type2_combo"),
    ("ccs (type 1)", "type1_combo"),
    ("chademo", "chademo"),
    ("type 2", "type2"),
    ("type 1", "type1"),
    ("gb-t dc", "gb_dc"),
    ("gb-t ac", "gb_ac"),
    ("tesla", "tesla_supercharger"),
    ("schuko", "schuko"),
    ("europlug", "typee"),
)


def fetch(api_key: str, bbox: tuple[float, float, float, float], max_results: int = 5000) -> list[dict[str, Any]]:
    south, west, north, east = bbox
    params = urllib.parse.urlencode(
        {
            "output": "json",
            "boundingbox": f"({south},{west}),({north},{east})",
            "maxresults": max_results,
            "compact": "false",
            "verbose": "false",
        }
    )
    request = urllib.request.Request(
        f"{API_URL}?{params}",
        headers={"X-API-Key": api_key, "User-Agent": "nearby-location-recommendation/0.3 (educational project)"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


def _socket_key(title: str | None) -> str:
    lowered = (title or "").lower()
    for needle, key in _CONNECTION_KEYS:
        if needle in lowered:
            return key
    return "other"


def to_osm_element(item: dict[str, Any]) -> dict[str, Any] | None:
    """Một trạm OCM → phần tử kiểu Overpass (``type``, ``id``, ``lat``,
    ``lon``, ``tags``). ``None`` với trạm đã ngừng hoạt động."""
    status = item.get("StatusType") or {}
    if status.get("IsOperational") is False:
        return None
    address = item.get("AddressInfo") or {}
    if address.get("Latitude") is None or address.get("Longitude") is None:
        return None
    tags: dict[str, str] = {"amenity": "charging_station"}
    if address.get("Title"):
        tags["name"] = address["Title"]
    if address.get("AddressLine1"):
        tags["addr:street"] = address["AddressLine1"]
    operator = (item.get("OperatorInfo") or {}).get("Title")
    if operator and "unknown" not in operator.lower():
        tags["operator"] = operator
    if item.get("UsageCost"):
        tags["charge"] = item["UsageCost"]
    usage = ((item.get("UsageType") or {}).get("Title") or "").lower()
    if "private" in usage:
        tags["access"] = "private"
    elif "public" in usage:
        tags["access"] = "yes"

    counts: dict[str, int] = {}
    power: dict[str, float] = {}
    for connection in item.get("Connections") or []:
        key = _socket_key((connection.get("ConnectionType") or {}).get("Title"))
        counts[key] = counts.get(key, 0) + int(connection.get("Quantity") or 1)
        if connection.get("PowerKW"):
            power[key] = max(power.get(key, 0.0), float(connection["PowerKW"]))
    for key, count in counts.items():
        tags[f"socket:{key}"] = str(count)
        if key in power:
            tags[f"socket:{key}:output"] = f"{power[key]:g} kW"
    if any(key in counts for key in ("type2", "type2_combo", "chademo", "type1", "type1_combo", "gb_ac", "gb_dc")):
        tags["motorcar"] = "yes"
    return {
        "type": "ocm",
        "id": item["ID"],
        "lat": address["Latitude"],
        "lon": address["Longitude"],
        "tags": tags,
    }


def import_items(database_url: str, items: list[dict[str, Any]]) -> dict[str, int]:
    stats = {"fetched": len(items), "inserted": 0, "merged": 0, "skipped": 0}
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            for item in items:
                element = to_osm_element(item)
                poi = normalize_osm_element(element) if element else None
                if poi is None:
                    stats["skipped"] += 1
                    continue
                poi |= {"source": "openchargemap", "source_id": f"ocm/{item['ID']}"}
                cursor.execute(
                    """
                    SELECT p.id::text AS id FROM pois p
                    WHERE p.category = 'charging_station'
                      AND ST_DWithin(p.location,
                          ST_SetSRID(ST_Point(%(longitude)s, %(latitude)s), 4326)::geography, %(radius)s)
                    ORDER BY ST_Distance(p.location,
                          ST_SetSRID(ST_Point(%(longitude)s, %(latitude)s), 4326)::geography)
                    LIMIT 1
                    """,
                    poi | {"radius": MERGE_RADIUS_M},
                )
                existing = cursor.fetchone()
                if existing:
                    poi_id = existing["id"]
                    # Giữ tên/địa chỉ của bản đã có, chỉ bổ sung nguồn.
                    stats["merged"] += 1
                else:
                    poi_id = _insert_poi(cursor, poi)
                    stats["inserted"] += 1
                _upsert_lineage(cursor, poi_id, poi)
        connection.commit()
    parking.refresh_facilities(database_url)
    return stats

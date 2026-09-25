"""Tìm chỗ gửi xe theo loại xe, có giá & giờ mở cửa — điểm mới của đề tài.

Bài toán: dữ liệu mở về bãi xe ở Việt Nam RẤT THƯA. Đo thật (Overpass, bbox
TP.HCM, 2026-09-25): 824 bãi xe, chỉ 8 bãi có giá, 6 bãi có giờ mở cửa; 25
trạm sạc. Hiển thị thẳng dữ liệu OSM thì gần như bãi nào cũng "không rõ".
Module này giải quyết bằng ba lớp:

1. **Chuẩn hoá** thẻ OSM tự do thành dữ liệu có cấu trúc — loại xe phục vụ
   (xe máy / ô tô / xe đạp / sạc điện, dạng có–không–chưa rõ), giá theo loại
   xe và đơn vị (lượt/giờ/ngày/đêm) — xem `app/parking_tags.py`.
2. **Giá theo mức tin cậy**, luôn ghi rõ nguồn: (a) giá thật — người dùng
   báo (`parking_reports`) hoặc thẻ OSM; (b) giá niêm yết của đơn vị vận hành
   / phí theo quy định còn hiệu lực; (c) mức tham khảo từ văn bản đã bãi bỏ;
   (d) chưa rõ — xem `app/parking_pricing.py`. Không bao giờ trình bày một
   ước tính như giá thật.
3. **Xếp hạng theo chi phí + điểm đến**: người dùng chọn nơi muốn tới và thời
   gian gửi → điểm tổng hợp từ quãng đi bộ tới điểm đến, tiền gửi ước tính cho
   đúng thời gian đó, và độ chắc chắn của dữ liệu; bãi đã biết chắc sẽ ĐÓNG
   trong lúc gửi bị loại.
"""

from __future__ import annotations

import logging
import math
import statistics
from collections import Counter
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from . import parking_pricing
from .config import settings
from .opening_hours import _concrete_intervals, opening_status, parse_opening_hours
from .parking_tags import UNITS, VEHICLES, facility_from_osm_tags

logger = logging.getLogger("nearby-parking")

TIMEZONE = "Asia/Ho_Chi_Minh"
WALK_METERS_PER_MINUTE = 75.0  # ~4.5 km/h
REPORT_WINDOW_DAYS = 180
# Trọng số điểm xếp hạng (càng thấp càng tốt). Đi bộ nặng nhất: người gửi xe
# quan tâm trước hết là gần chỗ mình tới; tiền gửi xe ở VN chênh nhau vài
# nghìn đồng nên xếp sau; độ chắc chắn của dữ liệu là tiêu chí phụ để phân
# định các bãi ngang nhau.
WEIGHT_WALK = 0.5
WEIGHT_COST = 0.35
WEIGHT_UNCERTAINTY = 0.15


# --------------------------------------------------------------------------
# Dựng bảng parking_facilities từ dữ liệu nguồn
# --------------------------------------------------------------------------

_UPSERT_FACILITY = """
INSERT INTO parking_facilities (
    poi_id, kind, motorbike, car, bicycle, ev_charging, fee, price_raw, prices,
    capacity, parking_type, access, operator, sockets, source, updated_at
) VALUES (
    %(poi_id)s, %(kind)s, %(motorbike)s, %(car)s, %(bicycle)s, %(ev_charging)s,
    %(fee)s, %(price_raw)s, %(prices)s, %(capacity)s, %(parking_type)s,
    %(access)s, %(operator)s, %(sockets)s, %(source)s, NOW()
)
ON CONFLICT (poi_id) DO UPDATE SET
    kind = EXCLUDED.kind, motorbike = EXCLUDED.motorbike, car = EXCLUDED.car,
    bicycle = EXCLUDED.bicycle, ev_charging = EXCLUDED.ev_charging,
    fee = EXCLUDED.fee, price_raw = EXCLUDED.price_raw, prices = EXCLUDED.prices,
    capacity = EXCLUDED.capacity, parking_type = EXCLUDED.parking_type,
    access = EXCLUDED.access, operator = EXCLUDED.operator,
    sockets = EXCLUDED.sockets, source = EXCLUDED.source, updated_at = NOW()
"""


def upsert_facility(cursor: psycopg.Cursor[Any], poi_id: str, facility: dict[str, Any], source: str) -> None:
    cursor.execute(
        _UPSERT_FACILITY,
        facility
        | {
            "poi_id": poi_id,
            "prices": Jsonb(facility["prices"]),
            "sockets": Jsonb(facility["sockets"]),
            "source": source,
        },
    )


def merge_facilities(facilities: list[dict[str, Any]]) -> dict[str, Any]:
    """Gộp thông tin của cùng một bãi/trạm từ nhiều nguồn (OSM, Open Charge
    Map): mỗi trường lấy giá trị ĐÃ BIẾT đầu tiên theo thứ tự nguồn."""
    merged = dict(facilities[0])
    for other in facilities[1:]:
        for key, value in other.items():
            current = merged.get(key)
            if current in (None, "unknown", [], "") and value not in (None, "unknown", [], ""):
                merged[key] = value
            elif key == "ev_charging":
                merged[key] = bool(current) or bool(value)
    return merged


def refresh_facilities(database_url: str | None = None) -> dict[str, int]:
    """Dựng lại `parking_facilities` từ thẻ gốc đã lưu trong
    `poi_source_records` (OSM, và Open Charge Map — xem
    `app/charging_import.py`, lưu dưới dạng thẻ kiểu OSM) — không cần tải lại
    dữ liệu nguồn."""
    stats = {"parking": 0, "charging_station": 0}
    by_poi: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    with psycopg.connect(database_url or settings.database_url, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT r.canonical_poi_id::text AS poi_id, r.source, r.raw_payload
                FROM poi_source_records r
                JOIN pois p ON p.id = r.canonical_poi_id
                WHERE r.source IN ('openstreetmap', 'openchargemap')
                  AND p.category IN ('parking', 'charging_station')
                ORDER BY r.source DESC  -- openstreetmap trước openchargemap
                """
            )
            for row in cursor.fetchall():
                tags = (row["raw_payload"] or {}).get("tags") or {}
                facility = facility_from_osm_tags(tags)
                if facility is not None:
                    by_poi.setdefault(row["poi_id"], []).append((row["source"], facility))
            for poi_id, entries in by_poi.items():
                facility = merge_facilities([facility for _, facility in entries])
                source = "+".join(dict.fromkeys(source for source, _ in entries))
                upsert_facility(cursor, poi_id, facility, source)
                stats[facility["kind"]] += 1
        connection.commit()
    return stats


# --------------------------------------------------------------------------
# Giá: gom báo cáo người dùng, chọn mức tin cậy, ước tính tiền theo thời gian
# --------------------------------------------------------------------------


def _consensus(reports: list[dict[str, Any]], vehicle: str) -> dict[str, Any] | None:
    """Trung vị các báo cáo giá gần đây của MỘT loại xe, theo đơn vị được báo
    nhiều nhất (không trộn giá theo lượt với giá theo giờ)."""
    priced = [r for r in reports if r["vehicle"] == vehicle and r["amount_vnd"] is not None]
    if not priced:
        return None
    unit = Counter(r["unit"] for r in priced).most_common(1)[0][0]
    same_unit = [r for r in priced if r["unit"] == unit]
    amounts = [r["amount_vnd"] for r in same_unit]
    return {
        "amountVnd": int(statistics.median(amounts)),
        "unit": unit,
        "reports": len(same_unit),
        # Cùng một giá được báo nhiều lần = chắc hơn nhiều lần báo lệch nhau.
        "agreement": round(Counter(amounts).most_common(1)[0][1] / len(amounts), 2),
        "lastReportedAt": max(r["created_at"] for r in same_unit).isoformat(),
    }


def _stay_cost(amount: int, unit: str, start: datetime, minutes: int) -> int | None:
    """Tiền gửi cho đúng khoảng thời gian gửi. ``None`` khi đơn vị không quy
    được ra một lượt gửi (giá tháng, giá theo kWh)."""
    if unit == "turn":
        return amount
    if unit == "hour":
        return amount * max(1, math.ceil(minutes / 60))
    if unit == "day":
        return amount * max(1, math.ceil(minutes / 1440))
    if unit == "night":
        end = start + timedelta(minutes=minutes)
        return amount if parking_pricing.crosses_night(start, end) else None
    return None


def resolve_price(
    facility: dict[str, Any],
    reports: list[dict[str, Any]],
    vehicle: str,
    start: datetime,
    minutes: int,
) -> dict[str, Any]:
    """Giá cho một loại xe, kèm MỨC TIN CẬY và nguồn:

    - ``community``: trung vị giá người dùng báo trong 180 ngày.
    - ``openstreetmap``: thẻ ``charge``/``fee`` trên OSM.
    - ``published``: giá niêm yết của đơn vị vận hành (V-Green cho trạm VinFast).
    - ``regulated``: phí đỗ ô tô lòng đường theo NQ 01/2018 (còn hiệu lực).
    - ``reference``: bảng giá QĐ 35/2018 — ĐÃ BÃI BỎ, chỉ để tham khảo.
    - ``unknown``.
    Ba mức giữa xem `app/parking_pricing.py`.

    Ưu tiên: ≥2 báo cáo cộng đồng > OSM > 1 báo cáo cộng đồng > dự phòng.
    Một báo cáo đơn lẻ có thể là nhầm/cố tình sai, nên xếp sau OSM.
    """
    community = _consensus(reports, vehicle)
    osm_prices = [
        p for p in facility.get("prices") or [] if p["vehicle"] in (vehicle, "any")
    ]
    osm = min(osm_prices, key=lambda p: UNITS.index(p["unit"])) if osm_prices else None

    chosen: dict[str, Any] | None = None
    if community and community["reports"] >= 2:
        chosen = {"tier": "community", **community}
    elif osm:
        chosen = {
            "tier": "openstreetmap",
            "amountVnd": osm["amountVnd"],
            "unit": osm["unit"],
            "unitAssumed": osm["unitAssumed"],
            "raw": facility.get("price_raw"),
        }
    elif community:
        chosen = {"tier": "community", **community}
    elif facility.get("fee") == "no":
        chosen = {"tier": "openstreetmap", "amountVnd": 0, "unit": "turn", "free": True}

    if chosen is not None:
        chosen["estimatedCost"] = _stay_cost(chosen["amountVnd"], chosen["unit"], start, minutes)
        return chosen

    fallback = parking_pricing.fallback_price(facility, vehicle, start, minutes)
    if fallback is not None:
        return fallback
    return {"tier": "unknown", "amountVnd": None, "unit": None, "estimatedCost": None}


# --------------------------------------------------------------------------
# Giờ mở cửa trong suốt thời gian gửi
# --------------------------------------------------------------------------


def open_throughout(schedule: dict[str, Any] | None, start: datetime, end: datetime) -> bool | None:
    """Bãi có mở LIÊN TỤC từ lúc gửi tới lúc lấy xe không. ``None`` = không đủ
    dữ liệu để kết luận (khác hẳn ``False``)."""
    if not schedule:
        return None
    if schedule.get("alwaysOpen"):
        return True
    if schedule.get("parseStatus") != "parsed":
        return None
    zone = ZoneInfo(TIMEZONE)
    intervals = sorted(_concrete_intervals(schedule, zone, start.astimezone(zone)))
    if end - start > timedelta(hours=20):
        # _concrete_intervals chỉ trải hôm qua → ngày mai quanh lúc bắt đầu.
        intervals += _concrete_intervals(schedule, zone, (start + timedelta(days=1)).astimezone(zone))
        intervals.sort()
    covered_until = start
    for opens, closes in intervals:
        if opens <= covered_until < closes:
            covered_until = closes
            if covered_until >= end:
                return True
    return False


def _hours(poi_opening: dict[str, Any] | None, reports: list[dict[str, Any]], start: datetime, end: datetime) -> dict[str, Any]:
    reported = [r["opening_hours"] for r in reports if r["opening_hours"]]
    schedule, source = None, None
    if reported:
        candidate = parse_opening_hours(Counter(reported).most_common(1)[0][0])
        if candidate.get("alwaysOpen") or candidate.get("parseStatus") == "parsed":
            schedule, source = candidate, "community"
    if schedule is None and poi_opening:
        schedule, source = poi_opening, "openstreetmap"
    status = opening_status(schedule, TIMEZONE, start)
    return {
        "raw": (schedule or {}).get("raw"),
        "source": source,
        "openNow": status["openNow"],
        "closesInMinutes": status["closesInMinutes"],
        "opensInMinutes": status["opensInMinutes"],
        "openThroughout": open_throughout(schedule, start, end),
    }


# --------------------------------------------------------------------------
# Tìm kiếm + xếp hạng
# --------------------------------------------------------------------------

_SEARCH_QUERY = """
SELECT p.id::text AS id, p.name, p.address, p.category,
       ST_Y(p.location::geometry) AS latitude, ST_X(p.location::geometry) AS longitude,
       p.opening_hours,
       ST_Distance(p.location, ST_SetSRID(ST_Point(%(lng)s, %(lat)s), 4326)::geography) AS "distanceMeters",
       ST_Distance(p.location, ST_SetSRID(ST_Point(%(dest_lng)s, %(dest_lat)s), 4326)::geography) AS "walkMeters",
       f.kind, f.motorbike, f.car, f.bicycle, f.ev_charging, f.fee, f.price_raw,
       f.prices, f.capacity, f.parking_type, f.access, f.operator, f.sockets, f.source
FROM parking_facilities f
JOIN pois p ON p.id = f.poi_id
WHERE ST_DWithin(p.location, ST_SetSRID(ST_Point(%(dest_lng)s, %(dest_lat)s), 4326)::geography, %(radius)s)
  AND {vehicle_filter}
ORDER BY "walkMeters"
LIMIT 200
"""

_VEHICLE_FILTERS = {
    "motorbike": "f.kind = 'parking' AND f.motorbike <> 'no'",
    "car": "f.kind = 'parking' AND f.car <> 'no'",
    "bicycle": "f.kind = 'parking' AND f.bicycle <> 'no' AND f.motorbike <> 'no'",
    "ev": "f.ev_charging",
}

_REPORTS_QUERY = """
SELECT poi_id::text AS poi_id, vehicle, amount_vnd, unit, opening_hours, created_at
FROM parking_reports
WHERE poi_id = ANY(%(poi_ids)s::uuid[])
  AND created_at >= NOW() - make_interval(days => %(days)s)
"""


def _fetch_reports(cursor: psycopg.Cursor[Any], poi_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not poi_ids:
        return {}
    cursor.execute(_REPORTS_QUERY, {"poi_ids": poi_ids, "days": REPORT_WINDOW_DAYS})
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in cursor.fetchall():
        grouped.setdefault(row["poi_id"], []).append(row)
    return grouped


def _uncertainty(vehicle_support: str, price_tier: str, open_through: bool | None) -> float:
    price = {
        "community": 0.0,
        "openstreetmap": 0.0,
        "published": 0.2,
        "regulated": 0.3,
        "reference": 0.6,
        "unknown": 1.0,
    }[price_tier]
    return round((price + (0.0 if open_through is not None else 1.0) + (0.0 if vehicle_support == "yes" else 1.0)) / 3, 3)


def build_result(
    row: dict[str, Any],
    reports: list[dict[str, Any]],
    vehicle: str,
    start: datetime,
    minutes: int,
) -> dict[str, Any]:
    end = start + timedelta(minutes=minutes)
    support = "yes" if vehicle == "ev" else row[vehicle]
    price = resolve_price(row, reports, vehicle, start, minutes)
    hours = _hours(row["opening_hours"], reports, start, end)
    return {
        "id": row["id"],
        "name": row["name"],
        "address": row["address"],
        "category": row["category"],
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "distanceMeters": round(row["distanceMeters"]),
        "walkMeters": round(row["walkMeters"]),
        "walkMinutes": math.ceil(row["walkMeters"] / WALK_METERS_PER_MINUTE),
        "kind": row["kind"],
        "vehicles": {"motorbike": row["motorbike"], "car": row["car"], "bicycle": row["bicycle"]},
        "vehicleSupport": support,
        "evCharging": row["ev_charging"],
        "price": price,
        "hours": hours,
        "capacity": row["capacity"],
        "parkingType": row["parking_type"],
        "operator": row["operator"],
        "sockets": row["sockets"],
        "dataSource": row["source"],
        "reportCount": len(reports),
        "uncertainty": _uncertainty(support, price["tier"], hours["openThroughout"]),
    }


def rank(results: list[dict[str, Any]], radius: int) -> list[dict[str, Any]]:
    """Điểm = 0.5·đi_bộ + 0.35·chi_phí + 0.15·độ_không_chắc (chuẩn hoá về
    [0, 1], thấp là tốt). Bãi CHẮC CHẮN đóng trong lúc gửi bị loại hẳn."""
    kept = [r for r in results if r["hours"]["openThroughout"] is not False]
    costs = [r["price"]["estimatedCost"] for r in kept if r["price"]["estimatedCost"] is not None]
    max_cost = max(costs) if costs else 0
    for r in kept:
        walk = min(1.0, r["walkMeters"] / max(radius, 1))
        cost_value = r["price"]["estimatedCost"]
        # Chưa biết giá: coi như đắt nhất trong nhóm (không thưởng cho việc
        # thiếu dữ liệu), cộng thêm phạt ở thành phần độ không chắc.
        cost = 1.0 if cost_value is None else (cost_value / max_cost if max_cost else 0.0)
        score = WEIGHT_WALK * walk + WEIGHT_COST * cost + WEIGHT_UNCERTAINTY * r["uncertainty"]
        r["score"] = round(score, 4)
        r["scoreBreakdown"] = {"walk": round(walk, 3), "cost": round(cost, 3), "uncertainty": r["uncertainty"]}
    kept.sort(key=lambda r: r["score"])
    return kept


def search(
    *,
    latitude: float,
    longitude: float,
    vehicle: str,
    minutes: int,
    destination: tuple[float, float] | None = None,
    radius: int = 1000,
    limit: int = 20,
    start: datetime | None = None,
) -> dict[str, Any]:
    if vehicle not in VEHICLES:
        raise ValueError(f"vehicle phải là một trong {VEHICLES}")
    start = start or datetime.now(ZoneInfo(TIMEZONE))
    dest_lat, dest_lng = destination or (latitude, longitude)
    query = _SEARCH_QUERY.replace("{vehicle_filter}", _VEHICLE_FILTERS[vehicle])
    with psycopg.connect(settings.database_url, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                query,
                {"lat": latitude, "lng": longitude, "dest_lat": dest_lat, "dest_lng": dest_lng, "radius": radius},
            )
            rows = cursor.fetchall()
            reports = _fetch_reports(cursor, [row["id"] for row in rows])
    results = [build_result(row, reports.get(row["id"], []), vehicle, start, minutes) for row in rows]
    ranked = rank(results, radius)
    return {
        "vehicle": vehicle,
        "minutes": minutes,
        "startAt": start.isoformat(),
        "destination": {"latitude": dest_lat, "longitude": dest_lng},
        "radius": radius,
        "candidates": len(results),
        "excludedClosed": len(results) - len(ranked),
        "weights": {"walk": WEIGHT_WALK, "cost": WEIGHT_COST, "uncertainty": WEIGHT_UNCERTAINTY},
        "results": ranked[:limit],
    }


# --------------------------------------------------------------------------
# Chi tiết một bãi + báo cáo của người dùng
# --------------------------------------------------------------------------


def facility_detail(poi_id: str, minutes: int = 120) -> dict[str, Any] | None:
    """Thông tin gửi xe của MỘT POI cho panel chi tiết — giá của từng loại xe
    bãi đó nhận, giờ mở cửa, cổng sạc. ``None`` khi POI không phải bãi xe."""
    start = datetime.now(ZoneInfo(TIMEZONE))
    with psycopg.connect(settings.database_url, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                _SEARCH_QUERY.replace("WHERE ST_DWithin", "WHERE p.id = %(poi_id)s AND ST_DWithin").replace(
                    "{vehicle_filter}", "TRUE"
                ),
                {"poi_id": poi_id, "lat": 0, "lng": 0, "dest_lat": 0, "dest_lng": 0, "radius": 1e9},
            )
            row = cursor.fetchone()
            if row is None:
                return None
            reports = _fetch_reports(cursor, [poi_id]).get(poi_id, [])
    vehicles = ["ev"] if row["kind"] == "charging_station" else [
        v for v in ("motorbike", "car", "bicycle") if row[v] != "no"
    ]
    end = start + timedelta(minutes=minutes)
    return {
        "poiId": poi_id,
        "kind": row["kind"],
        "vehicles": {"motorbike": row["motorbike"], "car": row["car"], "bicycle": row["bicycle"]},
        "prices": {v: resolve_price(row, reports, v, start, minutes) for v in vehicles},
        "hours": _hours(row["opening_hours"], reports, start, end),
        "capacity": row["capacity"],
        "parkingType": row["parking_type"],
        "access": row["access"],
        "operator": row["operator"],
        "sockets": row["sockets"],
        "priceRaw": row["price_raw"],
        "dataSource": row["source"],
        "reportCount": len(reports),
        "minutes": minutes,
    }


def add_report(
    poi_id: str,
    session_id: UUID,
    vehicle: str,
    amount_vnd: int | None,
    unit: str | None,
    opening_hours: str | None,
) -> str:
    """Lưu một báo cáo. Trả ``"ok"``, ``"not_parking"`` hoặc ``"duplicate"``
    (phiên này đã báo cho bãi + loại xe này hôm nay)."""
    with psycopg.connect(settings.database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM parking_facilities WHERE poi_id = %s", (poi_id,))
            if cursor.fetchone() is None:
                return "not_parking"
            try:
                cursor.execute(
                    """
                    INSERT INTO parking_reports (poi_id, session_id, vehicle, amount_vnd, unit, opening_hours)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (poi_id, session_id, vehicle, amount_vnd, unit, opening_hours),
                )
            except psycopg.errors.UniqueViolation:
                return "duplicate"
        connection.commit()
    return "ok"

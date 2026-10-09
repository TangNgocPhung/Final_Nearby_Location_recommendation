"""Tìm trạm sạc xe điện — xe máy điện hay ô tô điện, mạng VinFast/V-Green,
đang mở cửa, và THỜI GIAN CHẠY XE THẬT tới trạm.

Dữ liệu dùng chung bảng ``parking_facilities`` với module gửi xe (xem
`app/parking.py`): trạm sạc là một dòng ``kind = 'charging_station'``. Khác
biệt nằm ở cách xếp hạng. Người tìm trạm sạc KHÔNG đi bộ từ trạm tới điểm đến
như người gửi xe — họ CHẠY XE tới trạm, nên thước đo đúng là thời gian chạy xe
theo đường thật (OSRM /table: một lần gọi cho mọi trạm), không phải khoảng cách
đi bộ.

Trung thực về dữ liệu: trạm sạc trên OSM ở TP.HCM rất thưa (25 trạm, đo
2026-09-28) và phần lớn KHÔNG ghi loại xe, cổng sạc hay công suất. Loại xe "chưa
rõ" vẫn được giữ lại khi lọc (không có nghĩa là không sạc được) và giao diện
phải nói rõ "chưa rõ" thay vì ngầm coi là có.
"""

from __future__ import annotations

from typing import Any

from . import directions, parking

EV_VEHICLES = ("any", "motorbike", "car")
NETWORKS = ("any", "vinfast", "other")
DEFAULT_RADIUS_METERS = 10_000
# Chỉ hỏi OSRM thời gian cho chừng này trạm gần nhất (đường chim bay) — đủ để
# thứ tự theo thời gian chạy xe có nghĩa, không biến một lần tìm thành ma trận
# hàng trăm ô.
MAX_ROUTED = 25
# Không có OSRM: ước tính từ đường chim bay × hệ số đường vòng, tốc độ nội đô.
DETOUR_FACTOR = 1.3
# Đi bộ ~4,5 km/h — cho tìm cửa hàng tiện lợi / nhà vệ sinh (`app/convenience.py`,
# `app/toilets.py`).
FALLBACK_SPEED_M_PER_MIN = {"motorbike": 350.0, "car": 300.0, "foot": 75.0}

_VINFAST_MARKERS = ("vinfast", "v-green", "vgreen", "v green")


def network_of(result: dict[str, Any]) -> str | None:
    """Tên mạng sạc để hiển thị. VinFast/V-Green nhận theo operator HOẶC tên
    trạm — OSM ghi tuỳ người nhập ("VinFast", "V-GREEN", "Trạm sạc VinFast…")."""
    text = f"{result.get('operator') or ''} {result.get('name') or ''}".lower()
    if any(marker in text for marker in _VINFAST_MARKERS):
        return "VinFast / V-Green"
    return result.get("operator") or None


def vehicle_ok(result: dict[str, Any], vehicle: str) -> bool:
    """Giữ trạm có thể phục vụ loại xe: "yes" hoặc "chưa rõ" — chỉ loại khi dữ
    liệu nói rõ "no"."""
    if vehicle == "any":
        return True
    return (result.get("vehicles") or {}).get(vehicle) != "no"


def filter_stations(
    results: list[dict[str, Any]], vehicle: str = "any", network: str = "any", open_now: bool = False
) -> list[dict[str, Any]]:
    kept = []
    for result in results:
        if not vehicle_ok(result, vehicle):
            continue
        is_vinfast = network_of(result) == "VinFast / V-Green"
        if network == "vinfast" and not is_vinfast:
            continue
        if network == "other" and is_vinfast:
            continue
        # "Đang mở" chỉ loại trạm CHẮC CHẮN đang đóng — trạm không có giờ mở
        # cửa (đa số) vẫn giữ, giao diện ghi "chưa rõ giờ".
        if open_now and (result.get("hours") or {}).get("openNow") is False:
            continue
        kept.append(result)
    return kept


def attach_drive_times(
    stations: list[dict[str, Any]],
    table: dict[str, Any] | None,
    mode: str,
) -> bool:
    """Gắn ``driveMinutes``/``driveMeters`` vào từng trạm. Trả ``True`` khi là
    số ƯỚC TÍNH (OSRM không trả lời), để giao diện ghi rõ.

    ``table`` là kết quả ``directions.duration_table`` với MỘT nguồn (người
    dùng) — ``durations[0][j]`` giây, ``distances[0][j]`` mét cho trạm thứ j.
    """
    durations = (table or {}).get("durations")
    distances = (table or {}).get("distances")
    if durations and durations[0] is not None and len(durations[0]) == len(stations):
        for index, station in enumerate(stations):
            seconds = durations[0][index]
            meters = distances[0][index] if distances and distances[0] else None
            station["driveMinutes"] = None if seconds is None else max(1, round(seconds / 60))
            station["driveMeters"] = None if meters is None else round(meters)
        return bool((table or {}).get("approximate"))
    speed = FALLBACK_SPEED_M_PER_MIN.get(mode, 300.0)
    for station in stations:
        meters = station["distanceMeters"] * DETOUR_FACTOR
        station["driveMinutes"] = max(1, round(meters / speed))
        station["driveMeters"] = round(meters)
    return True


def rank_by_travel_time(
    latitude: float,
    longitude: float,
    candidates: list[dict[str, Any]],
    mode: str,
    limit: int,
    max_routed: int = MAX_ROUTED,
) -> tuple[list[dict[str, Any]], bool]:
    """Xếp ``candidates`` (đã sắp theo đường chim bay) theo thời gian đi THẬT từ
    người dùng — OSRM /table một lần cho ``max_routed`` điểm gần nhất. Điểm
    không có địa chỉ được gắn ``streetAddress`` (tên đường sát nó, ước lượng);
    chỉ tra cho điểm SẼ hiển thị (có cache Redis). Trả ``(kết quả, ước tính?)``.
    """
    routed = candidates[:max_routed]
    table = (
        directions.duration_table(
            [(latitude, longitude)], [(item["latitude"], item["longitude"]) for item in routed], mode
        )
        if routed
        else None
    )
    approximate = attach_drive_times(routed, table, mode)
    routed.sort(key=lambda item: (item["driveMinutes"] is None, item["driveMinutes"] or 0, item["distanceMeters"]))
    results = routed[:limit]
    for item in results:
        if item.get("address") is None:
            item["streetAddress"] = directions.nearest_streets(item["latitude"], item["longitude"])
    return results, approximate


def search_stations(
    *,
    latitude: float,
    longitude: float,
    vehicle: str = "any",
    network: str = "any",
    open_now: bool = False,
    radius: int = DEFAULT_RADIUS_METERS,
    limit: int = 20,
) -> dict[str, Any]:
    if vehicle not in EV_VEHICLES:
        raise ValueError(f"vehicle phải là một trong {EV_VEHICLES}")
    if network not in NETWORKS:
        raise ValueError(f"network phải là một trong {NETWORKS}")
    # Tận dụng toàn bộ phần chuẩn hoá của module gửi xe: giá theo mức tin cậy
    # (V-Green 3.858 đ/kWh là giá niêm yết), giờ mở cửa, cổng sạc. Điểm đến =
    # vị trí người dùng, nên `walkMeters` ở đây chính là khoảng cách chim bay.
    found = parking.search(
        latitude=latitude, longitude=longitude, vehicle="ev", minutes=60, radius=radius, limit=200
    )
    candidates = filter_stations(found["results"], vehicle, network, open_now)
    candidates.sort(key=lambda item: item["distanceMeters"])
    routed = candidates[:MAX_ROUTED]

    mode = "car" if vehicle == "car" else "motorbike"
    table = (
        directions.duration_table(
            [(latitude, longitude)], [(item["latitude"], item["longitude"]) for item in routed], mode
        )
        if routed
        else None
    )
    approximate = attach_drive_times(routed, table, mode)
    for station in routed:
        station["network"] = network_of(station)
    routed.sort(key=lambda item: (item["driveMinutes"] is None, item["driveMinutes"] or 0, item["distanceMeters"]))
    return {
        "vehicle": vehicle,
        "network": network,
        "openNow": open_now,
        "mode": mode,
        "radius": radius,
        "approximate": approximate,
        "candidates": len(candidates),
        "results": routed[:limit],
    }

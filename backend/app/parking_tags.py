"""Đọc thẻ OSM của bãi xe / trạm sạc thành dữ liệu có cấu trúc.

Thẻ ``charge`` của OSM là CHỮ TỰ DO do người nhập gõ — dữ liệu thật ở TP.HCM
(Overpass, 2026-09-25) có đủ kiểu: ``"5000 VND/bike, 20000 VND/car"``,
``"2000 VND"``, ``"30k VND"``, ``"10000 VND"``. Module này đọc bảo thủ: chỉ
nhận chuỗi có số tiền rõ ràng, không đoán khi không chắc, và luôn giữ nguyên
bản gốc (``price_raw``) để hiển thị đối chiếu.

Đơn vị mặc định khi chuỗi không ghi là "lượt" (``unitAssumed=True``) — cách
tính phổ biến nhất của bãi giữ xe ở Việt Nam, nhưng vẫn đánh dấu là giả định
để giao diện nói rõ.
"""

from __future__ import annotations

import re
from typing import Any

VEHICLES = ("motorbike", "car", "bicycle", "ev")
UNITS = ("turn", "hour", "day", "night", "month", "kwh")

_VEHICLE_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("bicycle", ("bicycle", "xe đạp", "xe dap")),
    ("motorbike", ("motorbike", "motorcycle", "moto", "scooter", "bike", "xe máy", "xe may", "xe 2 bánh", "xe hai bánh")),
    ("car", ("car", "auto", "ô tô", "oto", "ôtô", "xe hơi", "xe 4 bánh", "4 chỗ", "7 chỗ")),
)
_UNIT_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("kwh", ("kwh",)),
    ("month", ("month", "tháng", "/th")),
    ("night", ("night", "đêm", "overnight")),
    ("day", ("day", "ngày", "24h")),
    ("hour", ("hour", "giờ", "/h", "/hr", " h", "tiếng")),
    ("turn", ("turn", "lượt", "luot", "lần", "time", "entry", "visit")),
)
# "5.000", "5,000", "20.000.000" → bỏ dấu phân cách hàng nghìn.
_THOUSANDS = re.compile(r"(?<=\d)[.,](?=\d{3}(?!\d))")
_AMOUNT = re.compile(r"(\d+(?:\.\d+)?)\s*(k|nghìn|ngàn|ngan)?", re.IGNORECASE)
_MIN_VND = 500  # nhỏ hơn thì gần như chắc là chuỗi đọc sai (vd "2 bánh")


def _find_word(text: str, table: tuple[tuple[str, tuple[str, ...]], ...]) -> str | None:
    for value, words in table:
        if any(word in text for word in words):
            return value
    return None


def parse_price(raw: str | None) -> list[dict[str, Any]]:
    """``"5000 VND/bike, 20000 VND/car"`` →
    ``[{vehicle: motorbike, amountVnd: 5000, unit: turn, unitAssumed: True}, ...]``.
    ``vehicle`` là ``"any"`` khi chuỗi không nói rõ loại xe."""
    if not raw:
        return []
    text = _THOUSANDS.sub("", raw.strip().lower())
    results: list[dict[str, Any]] = []
    # "Xe máy ban ngày 4.000đ, ban đêm 6.000đ": vế sau không nhắc lại loại xe
    # thì hiểu là cùng loại xe với vế trước.
    last_vehicle = "any"
    for part in re.split(r"[;,]|\s+\+\s+", text):
        part = part.strip()
        if not part:
            continue
        match = _AMOUNT.search(part)
        if not match:
            continue
        amount = float(match.group(1))
        if match.group(2):
            amount *= 1000
        amount_vnd = int(round(amount))
        if amount_vnd < _MIN_VND:
            continue
        # "ban ngày" là giá theo lượt ban ngày, không phải giá theo ngày.
        unit = _find_word(part.replace("ban ngày", "lượt"), _UNIT_WORDS)
        last_vehicle = _find_word(part, _VEHICLE_WORDS) or last_vehicle
        results.append(
            {
                "vehicle": last_vehicle,
                "amountVnd": amount_vnd,
                "unit": unit or "turn",
                "unitAssumed": unit is None,
            }
        )
    return results


def _yes_no(value: str | None) -> str:
    if value is None:
        return "unknown"
    value = value.strip().lower()
    if value in ("yes", "designated", "permissive", "customers", "destination"):
        return "yes"
    if value in ("no", "private"):
        return "no"
    return "unknown"


def _int_or_none(value: str | None) -> int | None:
    if value is None:
        return None
    match = re.match(r"\s*(\d+)", value)
    return int(match.group(1)) if match else None


_SOCKET_LABELS = {
    "type2": "Type 2 (AC)",
    "type2_combo": "CCS2 (DC)",
    "type2_cable": "Type 2 (AC)",
    "chademo": "CHAdeMO (DC)",
    "type1": "Type 1 (AC)",
    "type1_combo": "CCS1 (DC)",
    "gb_ac": "GB/T (AC)",
    "gb_dc": "GB/T (DC)",
    "schuko": "Ổ cắm dân dụng",
    "typee": "Ổ cắm dân dụng",
}


def parse_sockets(tags: dict[str, str]) -> list[dict[str, Any]]:
    sockets: list[dict[str, Any]] = []
    for key, value in tags.items():
        if not key.startswith("socket:") or key.count(":") != 1:
            continue
        socket_type = key.split(":", 1)[1]
        output = tags.get(f"{key}:output") or ""
        power = re.search(r"(\d+(?:\.\d+)?)\s*kw", output.lower())
        sockets.append(
            {
                "type": _SOCKET_LABELS.get(socket_type, socket_type),
                "count": _int_or_none(value),
                "powerKw": float(power.group(1)) if power else None,
            }
        )
    return sockets


def facility_from_osm_tags(tags: dict[str, str]) -> dict[str, Any] | None:
    """Thẻ OSM → một dòng `parking_facilities` (chưa có poi_id/source)."""
    amenity = tags.get("amenity")
    if amenity not in ("parking", "motorcycle_parking", "charging_station"):
        return None
    prices = parse_price(tags.get("charge"))
    priced_vehicles = {price["vehicle"] for price in prices}

    if amenity == "motorcycle_parking":
        motorbike, car = "yes", "no"
    elif amenity == "parking":
        motorbike = _yes_no(tags.get("motorcycle"))
        # amenity=parking theo định nghĩa OSM là chỗ đỗ xe cơ giới (mặc định ô
        # tô) — chỉ coi là "không nhận ô tô" khi có thẻ nói rõ.
        car = _yes_no(tags.get("motorcar")) if "motorcar" in tags else "yes"
    else:  # charging_station
        motorbike = _yes_no(tags.get("motorcycle") or tags.get("scooter"))
        car = _yes_no(tags.get("motorcar"))
    # Tên bãi thường nói luôn loại xe ("Bãi gửi xe hai bánh", "Bãi đỗ ô tô").
    named_vehicle = _find_word((tags.get("name") or "").lower(), _VEHICLE_WORDS)
    if named_vehicle == "motorbike" and motorbike == "unknown":
        motorbike = "yes"
        if "motorcar" not in tags:
            car = "unknown"  # "Bãi giữ xe máy" nhiều khả năng không nhận ô tô
    if named_vehicle == "car" and car == "unknown":
        car = "yes"
    if "motorbike" in priced_vehicles:
        motorbike = "yes"
    if "car" in priced_vehicles:
        car = "yes"

    fee = _yes_no(tags.get("fee"))
    if prices:
        fee = "yes"

    return {
        "kind": "charging_station" if amenity == "charging_station" else "parking",
        "motorbike": motorbike,
        "car": car,
        "bicycle": _yes_no(tags.get("bicycle")) if "bicycle" not in priced_vehicles else "yes",
        "ev_charging": amenity == "charging_station"
        or (_int_or_none(tags.get("capacity:charging")) or 0) > 0,
        "fee": fee,
        "price_raw": tags.get("charge"),
        "prices": prices,
        "capacity": _int_or_none(tags.get("capacity")),
        "parking_type": tags.get("parking"),
        "access": tags.get("access"),
        "operator": tags.get("operator") or tags.get("brand"),
        "sockets": parse_sockets(tags),
    }

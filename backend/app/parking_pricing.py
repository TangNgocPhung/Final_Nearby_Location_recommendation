"""Giá "không phải giá thật" cho bãi không có dữ liệu — mỗi mức ghi rõ bản chất.

Tra cứu văn bản gốc (Công báo TP.HCM, 2026-09-25):

- **QĐ 35/2018/QĐ-UBND** (giá TỐI ĐA trông giữ xe, bãi đầu tư bằng vốn ngoài
  ngân sách) đã bị **bãi bỏ toàn bộ** bởi QĐ 344/QĐ-UBND ngày 16/01/2026 —
  không tìm thấy văn bản thay thế; theo Luật Giá 2023, bãi tư nhân nay tự
  định giá và niêm yết. Bảng giá cũ CHỈ còn dùng làm mức THAM KHẢO (tier
  ``reference``), không được gọi là "theo quy định".
- **NQ 01/2018/NQ-HĐND** (phí đỗ ô tô dưới lòng đường, lũy tiến theo giờ,
  06:00–24:00) — vẫn đang áp dụng ở địa bàn TP.HCM cũ (Tuổi Trẻ 28/02/2026) →
  tier ``regulated``, chỉ cho chỗ đỗ ô tô ven đường (``parking=street_side``).
  NQ 07/2020 có sửa "một số nội dung" nhưng chưa đọc được toàn văn — ghi chú
  trong ``LEGAL`` để giao diện nói rõ.
- **V-Green** (mạng sạc VinFast): 3.858 đ/kWh đã gồm VAT, từ 19/03/2024 →
  tier ``published`` cho trạm có operator/brand VinFast/V-Green.

Mức giá phân theo khu vực (Quận 1/3/5 cũ vs quận khác) được trả về dạng
KHOẢNG (``amountMinVnd``–``amountVnd``) vì 809/813 bãi xe trên OSM không có
thông tin quận (đo 2026-09-25) — không đoán khu vực.
"""

from __future__ import annotations

import math
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")

LEGAL: dict[str, dict[str, str]] = {
    "qd35_2018": {
        "document": "QĐ 35/2018/QĐ-UBND (giá tối đa dịch vụ trông giữ xe)",
        "status": "Đã bãi bỏ từ 16/01/2026 (QĐ 344/QĐ-UBND) — chỉ để tham khảo",
        "url": "https://congbao.hochiminhcity.gov.vn/cong-bao/van-ban/quyet-dinh/so/344-qd-ubnd/ngay/16-01-2026/noi-dung/49047",
    },
    "nq01_2018": {
        "document": "NQ 01/2018/NQ-HĐND (phí đỗ ô tô dưới lòng đường)",
        "status": "Đang áp dụng tại địa bàn TP.HCM cũ; có sửa đổi bởi NQ 07/2020/NQ-HĐND",
        "url": "https://congbao.hochiminhcity.gov.vn/cong-bao/van-ban/nghi-quyet/so/01-2018-nq-hdnd/ngay/16-03-2018/noi-dung/42994",
    },
    "vgreen": {
        "document": "Bảng giá sạc V-Green",
        "status": "3.858 đ/kWh đã gồm VAT, áp dụng từ 19/03/2024",
        "url": "https://vgreen.net/vi/san-pham-dich-vu",
    },
}

# QĐ 35/2018: ban đêm 18:00 → 06:00 hôm sau.
DAY_STARTS = time(6, 0)
NIGHT_STARTS = time(18, 0)

# QĐ 35/2018 — đ/xe/lượt. Xe máy: nhóm 1 (trường học, bệnh viện, bến xe, chợ,
# siêu thị, nơi công cộng) 4.000/6.000; nhóm 2 (nơi khác) 6.000/9.000 — không
# biết bãi thuộc nhóm nào nên trả khoảng nhóm 1 → nhóm 2.
_QD35_PER_TURN: dict[str, dict[str, tuple[int, int]]] = {
    "bicycle": {"day": (2000, 2000), "night": (4000, 4000)},
    "motorbike": {"day": (4000, 6000), "night": (6000, 9000)},
}

# NQ 01/2018 — ô tô ≤ 9 chỗ, đ/giờ theo giờ thứ 1, 2, 3, 4, từ giờ 5.
# Khu vực 2 (quận khác) là cận dưới, khu vực 1 (Q1, Q3, Q5 cũ) là cận trên.
_NQ01_HOURLY_AREA2 = (20000, 20000, 25000, 25000, 30000)
_NQ01_HOURLY_AREA1 = (25000, 25000, 30000, 30000, 35000)
_NQ01_CHARGED_FROM = time(6, 0)  # thu phí 06:00–24:00

VGREEN_PRICE_PER_KWH = 3858
_STREET_PARKING_TYPES = {"street_side", "lane", "on_kerb", "on_street"}


def _local(moment: datetime) -> datetime:
    return moment.astimezone(TIMEZONE)


def _is_night(moment: datetime) -> bool:
    local = _local(moment).time()
    return local >= NIGHT_STARTS or local < DAY_STARTS


def crosses_night(start: datetime, end: datetime) -> bool:
    """Khoảng gửi có chạm khung ban đêm (18:00–06:00) không, lấy mẫu 15 phút."""
    moment = start
    while moment <= end:
        if _is_night(moment):
            return True
        moment += timedelta(minutes=15)
    return False


def _night_share(start: datetime, minutes: int) -> float:
    samples = [start + timedelta(minutes=m) for m in range(0, max(minutes, 1), 5)]
    return sum(_is_night(moment) for moment in samples) / len(samples)


def reference_estimate(vehicle: str, start: datetime, minutes: int) -> dict[str, Any] | None:
    """Mức THAM KHẢO từ bảng giá QĐ 35/2018 (đã bãi bỏ). Quy tắc tính của văn
    bản: gửi dưới 12 giờ tính theo khung (ngày/đêm) chiếm nhiều thời gian hơn;
    từ 12 giờ trở lên văn bản dùng giá "cả ngày và đêm" nhưng không ghi số —
    ở đây tính bằng một lượt ngày + một lượt đêm cho mỗi 24 giờ."""
    table = _QD35_PER_TURN.get(vehicle)
    if table is None:
        return None
    if minutes >= 12 * 60:
        days = math.ceil(minutes / 1440)
        low = (table["day"][0] + table["night"][0]) * days
        high = (table["day"][1] + table["night"][1]) * days
        period = "fullDay"
    else:
        period = "night" if _night_share(start, minutes) > 0.5 else "day"
        low, high = table[period]
    unit_low, unit_high = table[period if period != "fullDay" else "day"]
    return {
        "amountMinVnd": unit_low,
        "amountVnd": unit_high,
        "unit": "turn",
        "period": period,
        "estimatedCostMin": low,
        "estimatedCost": high,
        "legalReference": LEGAL["qd35_2018"],
    }


def street_parking_estimate(start: datetime, minutes: int) -> dict[str, Any]:
    """Phí đỗ ô tô dưới lòng đường theo NQ 01/2018: lũy tiến theo từng giờ,
    chỉ tính giờ nằm trong 06:00–24:00."""
    low = high = 0
    charged_hour = 0
    for hour_index in range(max(1, math.ceil(minutes / 60))):
        moment = _local(start + timedelta(hours=hour_index))
        if moment.time() < _NQ01_CHARGED_FROM:
            continue
        step = min(charged_hour, 4)
        low += _NQ01_HOURLY_AREA2[step]
        high += _NQ01_HOURLY_AREA1[step]
        charged_hour += 1
    return {
        "amountMinVnd": _NQ01_HOURLY_AREA2[0],
        "amountVnd": _NQ01_HOURLY_AREA1[0],
        "unit": "hour",
        "progressive": True,
        "estimatedCostMin": low,
        "estimatedCost": high,
        "legalReference": LEGAL["nq01_2018"],
    }


def is_vgreen(operator: str | None, name: str | None = None) -> bool:
    text = f"{operator or ''} {name or ''}".lower()
    return "vinfast" in text or "v-green" in text or "vgreen" in text


def fallback_price(facility: dict[str, Any], vehicle: str, start: datetime, minutes: int) -> dict[str, Any] | None:
    """Giá dự phòng khi bãi không có giá thật, theo thứ tự: giá niêm yết của
    đơn vị vận hành → phí theo quy định còn hiệu lực → mức tham khảo đã bãi
    bỏ. ``None`` = không có gì đáng tin để nói."""
    if vehicle == "ev":
        if is_vgreen(facility.get("operator"), facility.get("name")):
            return {
                "tier": "published",
                "amountVnd": VGREEN_PRICE_PER_KWH,
                "unit": "kwh",
                "estimatedCost": None,
                "legalReference": LEGAL["vgreen"],
            }
        return None
    if vehicle == "car" and facility.get("parking_type") in _STREET_PARKING_TYPES:
        return {"tier": "regulated", **street_parking_estimate(start, minutes)}
    reference = reference_estimate(vehicle, start, minutes)
    if reference is not None:
        return {"tier": "reference", **reference}
    return None

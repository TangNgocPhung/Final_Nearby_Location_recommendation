"""Âm lịch Việt Nam — đổi qua lại dương lịch ↔ âm lịch.

Dùng cho gợi ý "sắp diễn ra" của trợ lý (`app/assistant.py`): Tết, Rằm tháng
Giêng, Vu Lan, Trung Thu… đều tính theo âm lịch nên mỗi năm rơi vào một ngày
dương khác nhau. Ghi cứng bảng ngày thì hết hạn sau một năm và sai lặng lẽ.

Thuật toán của Hồ Ngọc Đức (amlich, công bố tự do), tính theo múi giờ +7. KHÔNG
dùng thư viện âm lịch Trung Quốc: lịch Việt tính theo kinh tuyến 105°Đ nên có
năm lệch một ngày/một tháng so với lịch Trung Quốc (múi +8) — ví dụ Tết 1985.

Chỉ có toán, không gọi mạng, không phụ thuộc gói ngoài.
"""

from __future__ import annotations

import math
from datetime import date

VIETNAM_TIMEZONE = 7.0


def _int(value: float) -> int:
    return math.floor(value)


def jd_from_date(day: int, month: int, year: int) -> int:
    """Số ngày Julius của một ngày dương lịch."""
    a = _int((14 - month) / 12)
    y = year + 4800 - a
    m = month + 12 * a - 3
    jd = day + _int((153 * m + 2) / 5) + 365 * y + _int(y / 4) - _int(y / 100) + _int(y / 400) - 32045
    if jd < 2299161:
        jd = day + _int((153 * m + 2) / 5) + 365 * y + _int(y / 4) - 32083
    return jd


def jd_to_date(jd: int) -> date:
    if jd > 2299160:
        a = jd + 32044
        b = _int((4 * a + 3) / 146097)
        c = a - _int((b * 146097) / 4)
    else:
        b = 0
        c = jd + 32082
    d = _int((4 * c + 3) / 1461)
    e = c - _int((1461 * d) / 4)
    m = _int((5 * e + 2) / 153)
    day = e - _int((153 * m + 2) / 5) + 1
    month = m + 3 - 12 * _int(m / 10)
    year = b * 100 + d - 4800 + _int(m / 10)
    return date(year, month, day)


def _new_moon(k: int) -> float:
    """Thời điểm (ngày Julius) của lần trăng non thứ k tính từ 1/1/1900."""
    t = k / 1236.85
    t2 = t * t
    t3 = t2 * t
    dr = math.pi / 180
    jd1 = 2415020.75933 + 29.53058868 * k + 0.0001178 * t2 - 0.000000155 * t3
    jd1 += 0.00033 * math.sin((166.56 + 132.87 * t - 0.009173 * t2) * dr)
    m = 359.2242 + 29.10535608 * k - 0.0000333 * t2 - 0.00000347 * t3
    mpr = 306.0253 + 385.81691806 * k + 0.0107306 * t2 + 0.00001236 * t3
    f = 21.2964 + 390.67050646 * k - 0.0016528 * t2 - 0.00000239 * t3
    c1 = (0.1734 - 0.000393 * t) * math.sin(m * dr) + 0.0021 * math.sin(2 * dr * m)
    c1 = c1 - 0.4068 * math.sin(mpr * dr) + 0.0161 * math.sin(dr * 2 * mpr)
    c1 = c1 - 0.0004 * math.sin(dr * 3 * mpr)
    c1 = c1 + 0.0104 * math.sin(dr * 2 * f) - 0.0051 * math.sin(dr * (m + mpr))
    c1 = c1 - 0.0074 * math.sin(dr * (m - mpr)) + 0.0004 * math.sin(dr * (2 * f + m))
    c1 = c1 - 0.0004 * math.sin(dr * (2 * f - m)) - 0.0006 * math.sin(dr * (2 * f + mpr))
    c1 = c1 + 0.0010 * math.sin(dr * (2 * f - mpr)) + 0.0005 * math.sin(dr * (2 * mpr + m))
    if t < -11:
        delta_t = 0.001 + 0.000839 * t + 0.0002261 * t2 - 0.00000845 * t3 - 0.000000081 * t * t3
    else:
        delta_t = -0.000278 + 0.000265 * t + 0.000262 * t2
    return jd1 + c1 - delta_t


def _sun_longitude(jdn: float) -> float:
    """Kinh độ mặt trời (radian, 0..2π) tại ngày Julius jdn."""
    t = (jdn - 2451545.0) / 36525
    t2 = t * t
    dr = math.pi / 180
    m = 357.52910 + 35999.05030 * t - 0.0001559 * t2 - 0.00000048 * t * t2
    l0 = 280.46645 + 36000.76983 * t + 0.0003032 * t2
    dl = (1.914600 - 0.004817 * t - 0.000014 * t2) * math.sin(dr * m)
    dl += (0.019993 - 0.000101 * t) * math.sin(dr * 2 * m) + 0.000290 * math.sin(dr * 3 * m)
    longitude = (l0 + dl) * dr
    return longitude - math.pi * 2 * _int(longitude / (math.pi * 2))


def _sun_longitude_sector(day_number: int, tz: float) -> int:
    """Kinh độ mặt trời lúc 0h ngày day_number, quy về 12 cung (0..11)."""
    return _int(_sun_longitude(day_number - 0.5 - tz / 24) / math.pi * 6)


def _new_moon_day(k: int, tz: float) -> int:
    return _int(_new_moon(k) + 0.5 + tz / 24)


def _lunar_month_11(year: int, tz: float) -> int:
    """Ngày bắt đầu tháng 11 âm lịch (tháng chứa Đông chí) của năm dương ``year``."""
    offset = jd_from_date(31, 12, year) - 2415021
    k = _int(offset / 29.530588853)
    new_moon = _new_moon_day(k, tz)
    if _sun_longitude_sector(new_moon, tz) >= 9:
        new_moon = _new_moon_day(k - 1, tz)
    return new_moon


def _leap_month_offset(a11: int, tz: float) -> int:
    k = _int((a11 - 2415021.076998695) / 29.530588853 + 0.5)
    i = 1
    arc = _sun_longitude_sector(_new_moon_day(k + i, tz), tz)
    while True:
        last = arc
        i += 1
        arc = _sun_longitude_sector(_new_moon_day(k + i, tz), tz)
        if arc == last or i >= 14:
            break
    return i - 1


def solar_to_lunar(day: date, tz: float = VIETNAM_TIMEZONE) -> tuple[int, int, int, bool]:
    """Dương → âm: ``(ngày, tháng, năm, là_tháng_nhuận)``."""
    day_number = jd_from_date(day.day, day.month, day.year)
    k = _int((day_number - 2415021.076998695) / 29.530588853)
    month_start = _new_moon_day(k + 1, tz)
    if month_start > day_number:
        month_start = _new_moon_day(k, tz)
    a11 = _lunar_month_11(day.year, tz)
    b11 = a11
    if a11 >= month_start:
        lunar_year = day.year
        a11 = _lunar_month_11(day.year - 1, tz)
    else:
        lunar_year = day.year + 1
        b11 = _lunar_month_11(day.year + 1, tz)
    lunar_day = day_number - month_start + 1
    diff = _int((month_start - a11) / 29)
    leap = False
    lunar_month = diff + 11
    if b11 - a11 > 365:
        leap_diff = _leap_month_offset(a11, tz)
        if diff >= leap_diff:
            lunar_month = diff + 10
            leap = diff == leap_diff
    if lunar_month > 12:
        lunar_month -= 12
    if lunar_month >= 11 and diff < 4:
        lunar_year -= 1
    return lunar_day, lunar_month, lunar_year, leap


def lunar_to_solar(
    lunar_day: int,
    lunar_month: int,
    lunar_year: int,
    leap: bool = False,
    tz: float = VIETNAM_TIMEZONE,
) -> date | None:
    """Âm → dương. ``None`` khi hỏi tháng nhuận mà năm đó không nhuận tháng ấy."""
    if lunar_month < 11:
        a11 = _lunar_month_11(lunar_year - 1, tz)
        b11 = _lunar_month_11(lunar_year, tz)
    else:
        a11 = _lunar_month_11(lunar_year, tz)
        b11 = _lunar_month_11(lunar_year + 1, tz)
    k = _int(0.5 + (a11 - 2415021.076998695) / 29.530588853)
    offset = lunar_month - 11
    if offset < 0:
        offset += 12
    if b11 - a11 > 365:
        leap_offset = _leap_month_offset(a11, tz)
        leap_month = leap_offset - 2
        if leap_month < 0:
            leap_month += 12
        if leap and lunar_month != leap_month:
            return None
        if leap or offset >= leap_offset:
            offset += 1
    elif leap:
        return None
    month_start = _new_moon_day(k + offset, tz)
    return jd_to_date(month_start + lunar_day - 1)


_CAN = ("Giáp", "Ất", "Bính", "Đinh", "Mậu", "Kỷ", "Canh", "Tân", "Nhâm", "Quý")
_CHI = ("Tý", "Sửu", "Dần", "Mão", "Thìn", "Tỵ", "Ngọ", "Mùi", "Thân", "Dậu", "Tuất", "Hợi")


def year_name(lunar_year: int) -> str:
    """Tên can chi của năm âm lịch, ví dụ 2026 → 'Bính Ngọ'."""
    return f"{_CAN[(lunar_year + 6) % 10]} {_CHI[(lunar_year + 8) % 12]}"

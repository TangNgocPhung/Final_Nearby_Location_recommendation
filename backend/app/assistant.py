"""Trợ lý trong khung chatbot: gợi ý theo ngữ cảnh, tour thuyết minh, hẹn nhóm.

Ba tính năng, chung một ý: chatbot không chỉ TRẢ LỜI mà còn CHỦ ĐỘNG gợi ý dựa
vào chỗ người dùng đang đứng và lúc này là lúc nào.

1. ``suggestions`` — chip gợi ý: sự kiện/lễ sắp tới (âm lịch tính bằng
   ``app/lunar.py``), dự báo mưa, giờ ăn, tour quanh đây, hẹn nhóm.
2. ``plan_tour`` — hướng dẫn viên AI: xếp các địa điểm CÓ bài thuyết minh đã
   kiểm chứng (``poi_knowledge``) thành một lộ trình đi bộ vừa thời lượng.
3. ``plan_meetup`` — điểm hẹn công bằng: chọn quán sao cho người đi XA NHẤT
   cũng không quá xa, theo thời gian đi xe máy THẬT (OSRM /table).

Trung thực về dữ liệu (cùng nguyên tắc với nhãn "Ảnh khu vực"):
- Lịch lễ chỉ có cho Việt Nam. Ở nước khác, trợ lý KHÔNG bịa lễ hội — chỉ còn
  gợi ý thời tiết/giờ ăn.
- Địa điểm gắn với lễ là phong tục HẰNG NĂM ("theo lệ hằng năm"), không phải
  lịch sự kiện đã xác nhận của năm nay — chữ hiển thị phải nói đúng như vậy.
- Tour chỉ gồm POI có ``poi_knowledge`` (đã kiểm chứng nguồn). Không để LLM tự
  kể về một địa điểm nó không có dữ liệu.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

from . import directions, explore, weather
from .config import settings
from .lunar import lunar_to_solar, solar_to_lunar, year_name

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

# Khung bao Việt Nam (xấp xỉ, gồm cả Phú Quốc). Ngoài khung thì không có lịch.
VIETNAM_BBOX = (8.0, 102.0, 23.5, 110.0)  # south, west, north, east

EVENT_HORIZON_DAYS = 60
MAX_EVENT_SUGGESTIONS = 4


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def in_vietnam(lat: float, lng: float) -> bool:
    south, west, north, east = VIETNAM_BBOX
    return south <= lat <= north and west <= lng <= east


# --- Lịch lễ ---------------------------------------------------------------------

# Địa điểm gắn với phong tục. `poi` = tên POI tra trong DB (lấy bản gần người
# dùng nhất — có nhiều "Chùa Vĩnh Nghiêm" trùng tên ở tỉnh khác). Điểm là CON
# PHỐ thì không có POI, ghi toạ độ trực tiếp:
# - Lương Nhữ Học (Q.5): trung bình toạ độ các POI có địa chỉ trên phố này
#   trong DB (2026-09-25).
# - Phố đi bộ Nguyễn Huệ (Q.1): theo các POI trên phố (Cà Phê Central Nguyễn Huệ,
#   chung cư 42 Nguyễn Huệ).
_PLACES: dict[str, dict[str, Any]] = {
    "luong_nhu_hoc": {
        "name": "Phố lồng đèn Lương Nhữ Học (Q.5)",
        "latitude": 10.75135,
        "longitude": 106.66036,
    },
    "nguyen_hue": {
        "name": "Phố đi bộ Nguyễn Huệ (Q.1)",
        "latitude": 10.77400,
        "longitude": 106.70380,
    },
    "tue_thanh": {"poi": "Hội quán Tuệ Thành"},
    "nghia_an": {"poi": "Hội quán Nghĩa An"},
    "vinh_nghiem": {"poi": "Chùa Vĩnh Nghiêm"},
    "duc_ba": {"poi": "Nhà thờ Đức Bà"},
    "tao_dan": {"poi": "Công viên Tao Đàn"},
    "dinh_doc_lap": {"poi": "Dinh Độc Lập"},
    "thao_cam_vien": {"poi": "Thảo Cầm Viên Sài Gòn"},
}

# `lunar=(ngày, tháng)` hoặc `solar=(ngày, tháng)`. `note` là câu mô tả phong tục
# — viết ở thể "thường/theo lệ", không khẳng định lịch cụ thể của năm nay.
# `ask` (tuỳ chọn) là câu hỏi gửi cho chatbot khi bấm "Gợi ý thêm".
# `shop` (tuỳ chọn) = khoá trong ``SHOPS``: lễ có tục mua/tặng một thứ cụ thể
# (hoa, vàng) thì gợi ý thẳng các cửa hàng THẬT theo category — tìm bằng
# pipeline xếp hạng, không đi qua LLM, nên vẫn chạy khi Ollama tắt.
CALENDAR: tuple[dict[str, Any], ...] = (
    {"id": "tet_duong_lich", "name": "Tết Dương lịch", "solar": (1, 1), "icon": "🎆",
     "note": "Ngày nghỉ lễ. Đêm 31/12 khu trung tâm Quận 1 thường rất đông người đón năm mới.",
     "places": ("nguyen_hue",)},
    {"id": "valentine", "name": "Lễ Tình nhân", "solar": (14, 2), "icon": "💝",
     "note": "Quán cà phê, nhà hàng thường đông khách buổi tối; nhiều người mua hoa tặng.",
     "ask": "Nhà hàng lãng mạn gần đây cho buổi tối", "shop": "florist"},
    {"id": "thay_thuoc", "name": "Ngày Thầy thuốc Việt Nam", "solar": (27, 2), "icon": "🩺",
     "note": "Nhiều người tặng hoa cảm ơn bác sĩ, điều dưỡng.", "shop": "florist"},
    {"id": "quoc_te_phu_nu", "name": "Quốc tế Phụ nữ", "solar": (8, 3), "icon": "🌷",
     "note": "Tiệm hoa, quán cà phê thường đông hơn ngày thường.",
     "ask": "Tiệm hoa gần đây", "shop": "florist"},
    {"id": "giai_phong", "name": "Ngày Giải phóng miền Nam, thống nhất đất nước", "solar": (30, 4),
     "icon": "🇻🇳", "note": "Ngày nghỉ lễ. Dinh Độc Lập là di tích gắn trực tiếp với sự kiện 30/4/1975.",
     "places": ("dinh_doc_lap",)},
    {"id": "lao_dong", "name": "Quốc tế Lao động", "solar": (1, 5), "icon": "🛠️",
     "note": "Ngày nghỉ lễ."},
    {"id": "thieu_nhi", "name": "Quốc tế Thiếu nhi", "solar": (1, 6), "icon": "🎈",
     "note": "Các khu vui chơi, công viên thường đông trẻ em.", "places": ("thao_cam_vien",)},
    {"id": "quoc_khanh", "name": "Quốc khánh", "solar": (2, 9), "icon": "🇻🇳",
     "note": "Ngày nghỉ lễ."},
    {"id": "phu_nu_vn", "name": "Ngày Phụ nữ Việt Nam", "solar": (20, 10), "icon": "🌹",
     "note": "Tiệm hoa, nhà hàng thường đông khách.", "ask": "Tiệm hoa gần đây", "shop": "florist"},
    {"id": "nha_giao", "name": "Ngày Nhà giáo Việt Nam", "solar": (20, 11), "icon": "📚",
     "note": "Tiệm hoa, quà tặng thường đông khách.", "ask": "Tiệm hoa gần đây", "shop": "florist"},
    {"id": "giang_sinh", "name": "Đêm Giáng sinh", "solar": (24, 12), "icon": "🎄",
     "note": "Theo lệ hằng năm, khu quanh Nhà thờ Đức Bà rất đông người đêm Noel.",
     "places": ("duc_ba",)},
    {"id": "ong_tao", "name": "Ông Công Ông Táo", "lunar": (23, 12), "icon": "🐟",
     "note": "Nhiều gia đình cúng tiễn Táo quân, chợ đông người mua cá chép, đồ cúng."},
    {"id": "tet_nguyen_dan", "name": "Tết Nguyên Đán", "lunar": (1, 1), "icon": "🧧",
     "note": "Theo lệ hằng năm, Đường hoa Nguyễn Huệ và Hội hoa xuân Tao Đàn mở dịp Tết. "
             "Nhiều quán ăn nghỉ Tết — nên kiểm tra giờ mở cửa.",
     "places": ("nguyen_hue", "tao_dan")},
    {"id": "than_tai", "name": "Ngày vía Thần Tài", "lunar": (10, 1), "icon": "🪙",
     "note": "Theo lệ hằng năm, tiệm vàng thường rất đông người mua lấy may từ sáng sớm.",
     "shop": "jewelry"},
    {"id": "nguyen_tieu", "name": "Rằm tháng Giêng (Tết Nguyên Tiêu)", "lunar": (15, 1), "icon": "🏮",
     "note": "Các hội quán người Hoa ở Chợ Lớn thường rất đông người đi lễ.",
     "places": ("tue_thanh", "nghia_an")},
    {"id": "gio_to", "name": "Giỗ Tổ Hùng Vương", "lunar": (10, 3), "icon": "🇻🇳",
     "note": "Ngày nghỉ lễ."},
    {"id": "via_ba", "name": "Vía Bà Thiên Hậu", "lunar": (23, 3), "icon": "🪔",
     "note": "Lễ lớn hằng năm của Hội quán Tuệ Thành (Chùa Bà Thiên Hậu) ở Chợ Lớn.",
     "places": ("tue_thanh",)},
    {"id": "phat_dan", "name": "Lễ Phật Đản", "lunar": (15, 4), "icon": "🪷",
     "note": "Các chùa lớn thường tổ chức đại lễ, đông phật tử.", "places": ("vinh_nghiem",)},
    {"id": "doan_ngo", "name": "Tết Đoan Ngọ", "lunar": (5, 5), "icon": "🍑",
     "note": "Tục ăn cơm rượu, trái cây đầu mùa."},
    {"id": "vu_lan", "name": "Lễ Vu Lan", "lunar": (15, 7), "icon": "🌹",
     "note": "Mùa báo hiếu; các chùa thường rất đông người đi lễ, theo tục cài bông hồng lên áo.",
     "places": ("vinh_nghiem",), "shop": "florist"},
    {"id": "trung_thu", "name": "Tết Trung Thu", "lunar": (15, 8), "icon": "🏮",
     "note": "Theo lệ hằng năm, phố lồng đèn Lương Nhữ Học (Quận 5) rực rỡ và rất đông "
             "người dạo chơi mấy tối quanh Rằm tháng Tám.",
     "places": ("luong_nhu_hoc", "tue_thanh")},
)


def _occurrences(event: dict[str, Any], start: date, end: date) -> list[date]:
    """Các ngày dương lịch của một lễ trong khoảng [start, end]."""
    days: list[date] = []
    for year in range(start.year - 1, end.year + 2):
        if "solar" in event:
            day, month = event["solar"]
            try:
                when: date | None = date(year, month, day)
            except ValueError:
                when = None
        else:
            day, month = event["lunar"]
            when = lunar_to_solar(day, month, year)
        if when is not None and start <= when <= end:
            days.append(when)
    return days


def upcoming_events(today: date, horizon_days: int = EVENT_HORIZON_DAYS) -> list[dict[str, Any]]:
    """Lễ trong ``horizon_days`` ngày tới (tính cả hôm nay), sớm nhất trước."""
    end = today + timedelta(days=horizon_days)
    found: list[dict[str, Any]] = []
    for event in CALENDAR:
        for when in _occurrences(event, today, end):
            found.append({**event, "date": when, "daysUntil": (when - today).days})
    found.sort(key=lambda item: item["daysUntil"])
    return found


def _when_label(days_until: int) -> str:
    if days_until == 0:
        return "Hôm nay"
    if days_until == 1:
        return "Ngày mai"
    return f"Còn {days_until} ngày"


def lunar_label(today: date) -> str:
    day, month, year, leap = solar_to_lunar(today)
    return f"{day}/{month}{' nhuận' if leap else ''} năm {year_name(year)}"


# Cửa hàng gắn với tục lệ của một ngày lễ. Chỉ gợi ý mua sắm trong
# ``SHOP_LEAD_DAYS`` ngày trước lễ — nhắc mua hoa 20/10 từ 21/9 là quá sớm để có
# ích, còn tuần cuối là lúc người ta thật sự đi tìm tiệm.
SHOPS: dict[str, dict[str, Any]] = {
    "florist": {"category": "florist", "icon": "💐", "noun": "Tiệm hoa"},
    "jewelry": {"category": "jewelry", "icon": "🪙", "noun": "Tiệm vàng"},
}
SHOP_LEAD_DAYS = 7
# Bán kính tìm cửa hàng: dữ liệu tiệm hoa THƯA (25 tiệm cho cả vùng nhập OSM,
# đo 2026-09-28) nên thử rộng dần thay vì báo "không có" khi 2 km quanh đây trống.
SHOP_RADII_METERS = (3_000, 6_000, 12_000)


def shop_search(
    shop_key: str, lat: float, lng: float, connection: psycopg.Connection | None = None
) -> dict[str, Any] | None:
    """Hành động "tìm cửa hàng" cho một lễ: category + bán kính NHỎ NHẤT còn có
    cửa hàng. ``None`` khi trong bán kính lớn nhất cũng không có tiệm nào — khi
    đó không hiện chip, thay vì dẫn người dùng tới một danh sách rỗng."""
    shop = SHOPS.get(shop_key)
    if shop is None:
        return None
    own = connection is None
    conn = connection or _connect()
    try:
        for radius in SHOP_RADII_METERS:
            row = conn.execute(
                """
                SELECT COUNT(*) AS n FROM pois
                WHERE category = %(cat)s
                  AND ST_DWithin(location, ST_SetSRID(ST_MakePoint(%(lng)s, %(lat)s), 4326)::geography, %(r)s)
                """,
                {"cat": shop["category"], "lat": lat, "lng": lng, "r": radius},
            ).fetchone()
            count = int(row["n"]) if row else 0
            if count:
                return {
                    "type": "search",
                    "title": f"{shop['noun']} gần bạn",
                    "category": shop["category"],
                    "query": None,
                    "latitude": lat,
                    "longitude": lng,
                    "radius": radius,
                    "count": count,
                }
        return None
    finally:
        if own:
            conn.close()


def home_place(owner_id: str | None, connection: psycopg.Connection | None = None) -> dict[str, Any] | None:
    """Địa chỉ "Nhà" người dùng đã lưu (``saved_places.kind = 'home'``)."""
    if not owner_id:
        return None
    own = connection is None
    conn = connection or _connect()
    try:
        return conn.execute(
            """
            SELECT label, ST_Y(location::geometry) AS latitude, ST_X(location::geometry) AS longitude
            FROM saved_places WHERE owner_id = %s AND kind = 'home'
            """,
            (owner_id,),
        ).fetchone()
    finally:
        if own:
            conn.close()


# Bán kính "gần nhà": đủ để đi bộ/chạy xe vài phút từ nhà.
HOME_RADIUS_METERS = 1_500
# Đang cách nhà dưới mức này thì "gần nhà" trùng với "gần bạn" — chip giờ ăn
# thường đã đủ, không lặp lại.
AT_HOME_METERS = 300


def home_meal_chip(
    home: dict[str, Any] | None, lat: float, lng: float, now: datetime
) -> dict[str, Any] | None:
    """Chip "quán ăn gần nhà" — tìm quanh toạ độ NHÀ chứ không quanh GPS hiện tại.

    Chưa lưu nhà thì trả chip mời đặt nhà: tính năng này vô dụng nếu người dùng
    không biết phải làm gì để bật nó.
    """
    if home is None:
        return {
            "id": "home:set",
            "kind": "home",
            "icon": "🏠",
            "title": "Gợi ý quán ăn gần nhà",
            "subtitle": "Lưu địa chỉ nhà để bật gợi ý này",
            "action": {"type": "set_home"},
        }
    home_lat, home_lng = float(home["latitude"]), float(home["longitude"])
    away = haversine_m(lat, lng, home_lat, home_lng)
    slot = _meal_slot(now)
    category = slot[5] if slot else "restaurant"
    title = f"{slot[6]} gần nhà" if slot else "Quán ăn gần nhà"
    subtitle = (
        "Bạn đang ở gần nhà"
        if away < AT_HOME_METERS
        else f"Quanh nhà · bạn đang cách nhà {away / 1000:.1f} km"
    )
    return {
        "id": "home:food",
        "kind": "home",
        "icon": "🏠",
        "title": title,
        "subtitle": subtitle,
        "action": {
            "type": "search",
            "title": title,
            "category": category,
            "query": None,
            "latitude": home_lat,
            "longitude": home_lng,
            "radius": HOME_RADIUS_METERS,
        },
    }


# --- Tra địa điểm ----------------------------------------------------------------


def _connect() -> psycopg.Connection:
    return psycopg.connect(settings.database_url, row_factory=dict_row)


def resolve_places(
    keys: tuple[str, ...], lat: float, lng: float, connection: psycopg.Connection | None = None
) -> list[dict[str, Any]]:
    """Đổi khoá trong ``_PLACES`` thành địa điểm cụ thể (có ``poiId`` nếu là POI)."""
    wanted = [key for key in keys if key in _PLACES]
    if not wanted:
        return []
    own = connection is None
    conn = connection or _connect()
    try:
        places: list[dict[str, Any]] = []
        for key in wanted:
            spec = _PLACES[key]
            if "poi" not in spec:
                places.append(
                    {
                        "poiId": None,
                        "name": spec["name"],
                        "latitude": spec["latitude"],
                        "longitude": spec["longitude"],
                        "distanceMeters": round(
                            haversine_m(lat, lng, spec["latitude"], spec["longitude"])
                        ),
                    }
                )
                continue
            row = conn.execute(
                """
                SELECT id::text AS "poiId", name,
                       ST_Y(location::geometry) AS latitude,
                       ST_X(location::geometry) AS longitude,
                       ST_Distance(location, ST_SetSRID(ST_MakePoint(%(lng)s, %(lat)s), 4326)::geography)
                           AS "distanceMeters"
                FROM pois WHERE name = %(name)s
                ORDER BY location <-> ST_SetSRID(ST_MakePoint(%(lng)s, %(lat)s), 4326)::geography
                LIMIT 1
                """,
                {"name": spec["poi"], "lat": lat, "lng": lng},
            ).fetchone()
            if row is not None:
                row["distanceMeters"] = round(float(row["distanceMeters"]))
                places.append(row)
        return places
    finally:
        if own:
            conn.close()


# --- Gợi ý ------------------------------------------------------------------------

TOUR_CONTENT_TYPES = (
    "historical", "cultural", "architectural", "nature", "food", "entertainment", "education",
)
TOUR_SEARCH_RADIUS_METERS = 6_000


# (giờ bắt đầu, giờ kết thúc, biểu tượng, tiêu đề, câu hỏi cho chatbot,
#  category khi tìm trực tiếp, nhãn bữa)
_MEAL_SLOTS = (
    (6, 9.5, "🥖", "Ăn sáng gần đây", "Quán ăn sáng gần tôi", "restaurant", "Ăn sáng"),
    (11, 13.5, "🍚", "Ăn trưa gần đây", "Quán cơm trưa ngon gần tôi", "restaurant", "Ăn trưa"),
    (14.5, 17, "🧋", "Giờ trà chiều", "Quán cà phê hoặc trà sữa gần tôi", "cafe", "Cà phê chiều"),
    (17.5, 21, "🍜", "Ăn tối gần đây", "Quán ăn tối ngon gần tôi", "restaurant", "Ăn tối"),
    (21, 24, "🌙", "Quán mở khuya", "Quán ăn đêm gần tôi", "restaurant", "Ăn khuya"),
)


def _meal_slot(now: datetime) -> tuple[Any, ...] | None:
    hour = now.hour + now.minute / 60
    for slot in _MEAL_SLOTS:
        if slot[0] <= hour < slot[1]:
            return slot
    return None


def _meal_search_action(
    title: str, prompt: str, category: str, lat: float, lng: float
) -> dict[str, Any]:
    return {
        "type": "search",
        "title": title,
        "query": prompt,
        "category": category,
        "latitude": lat,
        "longitude": lng,
        "radius": 3_000,
    }


def _meal_suggestion(now: datetime, lat: float, lng: float) -> dict[str, Any] | None:
    slot = _meal_slot(now)
    if slot is None:
        return None
    _start, _end, icon, title, prompt, category, label = slot
    return {
        "id": "meal",
        "kind": "time",
        "icon": icon,
        "title": title,
        # f-string chứ không phải strftime("Bây giờ %H:%M"): strftime trên Windows
        # từ chối chữ không phải ASCII trong chuỗi định dạng (UnicodeEncodeError).
        "subtitle": f"Bây giờ {now:%H:%M}",
        "action": _meal_search_action(label, prompt, category, lat, lng),
    }


def _upcoming_meal_suggestion(now: datetime, lat: float, lng: float) -> dict[str, Any]:
    """Gợi ý mốc ăn uống kế tiếp để người dùng lên kế hoạch trước."""
    hour = now.hour + now.minute / 60
    upcoming = next((slot for slot in _MEAL_SLOTS if slot[0] > hour), None)
    tomorrow = upcoming is None
    if upcoming is None:
        upcoming = _MEAL_SLOTS[0]
    start, _end, icon, _title, prompt, category, label = upcoming
    when = "sáng mai" if tomorrow else f"{int(start):02d}:{int((start % 1) * 60):02d} hôm nay"
    return {
        "id": "meal:next",
        "kind": "time",
        "icon": icon,
        "title": f"Gợi ý cho {label.lower()}",
        "subtitle": f"Sắp tới · {when}",
        "action": _meal_search_action(label, prompt, category, lat, lng),
    }


def suggestions(
    lat: float, lng: float, now: datetime | None = None, owner_id: str | None = None
) -> dict[str, Any]:
    """Chip gợi ý cho khung chatbot, theo vị trí + thời điểm hiện tại.

    ``owner_id`` (phiên trình duyệt) chỉ dùng để đọc địa chỉ "Nhà" đã lưu —
    không có thì bỏ qua gợi ý gần nhà, mọi chip khác vẫn như cũ.
    """
    now = (now or datetime.now(VN_TZ)).astimezone(VN_TZ)
    today = now.date()
    vietnam = in_vietnam(lat, lng)
    chips: list[dict[str, Any]] = []

    # 1) Lễ / sự kiện sắp tới (chỉ Việt Nam).
    if vietnam:
        with _connect() as connection:
            shop_chips: list[dict[str, Any]] = []
            for event in upcoming_events(today)[:MAX_EVENT_SUGGESTIONS]:
                places = resolve_places(tuple(event.get("places", ())), lat, lng, connection)
                shop_action = (
                    shop_search(event["shop"], lat, lng, connection) if event.get("shop") else None
                )
                # Chip mua sắm riêng, chỉ trong tuần cuối trước lễ và chỉ một chip
                # cho mỗi loại cửa hàng (8/3 và Valentine cùng là tiệm hoa).
                if (
                    shop_action
                    and event["daysUntil"] <= SHOP_LEAD_DAYS
                    and all(chip["action"]["category"] != shop_action["category"] for chip in shop_chips)
                ):
                    shop = SHOPS[event["shop"]]
                    shop_chips.append(
                        {
                            "id": f"shop:{event['id']}",
                            "kind": "shop",
                            "icon": shop["icon"],
                            "title": f"{shop['noun']} cho {event['name']}",
                            "subtitle": f"{_when_label(event['daysUntil'])} · "
                            f"{shop_action['count']} tiệm trong {shop_action['radius'] // 1000} km",
                            "action": shop_action,
                        }
                    )
                chips.append(
                    {
                        "id": f"event:{event['id']}",
                        "kind": "event",
                        "icon": event["icon"],
                        "title": event["name"],
                        "subtitle": f"{_when_label(event['daysUntil'])} · "
                        f"{event['date'].strftime('%d/%m')}"
                        + (" (âm lịch)" if "lunar" in event else ""),
                        "action": {
                            "type": "event",
                            "event": {
                                "name": event["name"],
                                "date": event["date"].isoformat(),
                                "daysUntil": event["daysUntil"],
                                "lunar": "lunar" in event,
                                "note": event["note"],
                                "places": places,
                                "ask": event.get("ask"),
                                # Tìm cửa hàng THẬT (không qua LLM) — nút "Xem
                                # tiệm hoa gần bạn" dưới câu trả lời của sự kiện.
                                "search": shop_action,
                            },
                        },
                    }
                )
            chips.extend(shop_chips)
            # Mùng 1 / Rằm: nhiều người ăn chay, đi chùa — gợi ý thực dụng.
            lunar_day = solar_to_lunar(today)[0]
            if lunar_day in (1, 15):
                chips.append(
                    {
                        "id": "chay",
                        "kind": "event",
                        "icon": "🥗",
                        "title": "Hôm nay " + ("mùng 1" if lunar_day == 1 else "Rằm") + " âm lịch",
                        "subtitle": "Nhiều người ăn chay — quán chay gần bạn",
                        "action": {"type": "ask", "prompt": "Quán chay gần tôi"},
                    }
                )

    # 2) Thời tiết: đang mưa hoặc sắp mưa.
    current = weather.current_weather(lat, lng) if settings.weather_enabled else None
    if current and current.get("isWet"):
        chips.append(
            {
                "id": "weather:now",
                "kind": "weather",
                "icon": "🌧️",
                "title": "Mưa to" if current.get("isHeavyRain") else "Đang mưa",
                "subtitle": "Tìm chỗ trong nhà gần bạn",
                "action": _meal_search_action(
                    "Chỗ trú mưa", "Quán cà phê trong nhà gần tôi để trú mưa", "cafe", lat, lng
                ),
            }
        )
    elif settings.weather_enabled:
        forecast = weather.rain_forecast(lat, lng)
        if forecast and forecast.get("time"):
            chips.append(
                {
                    "id": "weather:soon",
                    "kind": "weather",
                    "icon": "🌦️",
                    "title": f"Có thể mưa lúc {forecast['time']}",
                    "subtitle": f"Khả năng {forecast['probability']}% — nên chọn chỗ trong nhà",
                    "action": _meal_search_action(
                        "Chỗ trong nhà", "Quán cà phê trong nhà gần tôi", "cafe", lat, lng
                    ),
                }
            )

    # 3) Giờ ăn — quanh chỗ đang đứng, rồi quanh NHÀ nếu đã lưu.
    meal = _meal_suggestion(now, lat, lng)
    if meal:
        chips.append(meal)
    chips.append(_upcoming_meal_suggestion(now, lat, lng))
    if vietnam:
        home_chip = home_meal_chip(home_place(owner_id), lat, lng, now)
        if home_chip:
            chips.append(home_chip)

    # 4) Tour thuyết minh — chỉ khi quanh đây có địa điểm có bài thuyết minh.
    stops_nearby = _tour_candidates(lat, lng, TOUR_SEARCH_RADIUS_METERS)
    if stops_nearby:
        chips.append(
            {
                "id": "tour",
                "kind": "tour",
                "icon": "🎧",
                "title": "Tour đi bộ có thuyết minh",
                "subtitle": f"{len(stops_nearby)} điểm di tích quanh bạn",
                "action": {"type": "tour"},
            }
        )

    # 5) Săn địa danh — cùng tập POI có câu chuyện kiểm chứng với tour.
    hunt = explore.nearby_summary(owner_id, lat, lng, TOUR_SEARCH_RADIUS_METERS)
    if hunt["nearby"]:
        remaining = hunt["nearby"] - hunt["discoveredNearby"]
        chips.append(
            {
                "id": "explore",
                "kind": "explore",
                "icon": "🗺️",
                "title": "Săn địa danh Sài Gòn",
                "subtitle": (
                    f"{remaining} địa danh chờ khám phá · gần nhất {round(hunt['nearestMeters'])} m"
                    if remaining and hunt["nearestMeters"] is not None
                    else f"Đã khám phá {hunt['discovered']}/{hunt['total']} địa danh"
                ),
                "action": {"type": "explore"},
            }
        )

    # 6) Chế độ giọng nói cho người khiếm thị — luôn có, để ai cần là thấy.
    chips.append(
        {
            "id": "voice",
            "kind": "voice",
            "icon": "🎙️",
            "title": "Chế độ giọng nói",
            "subtitle": "Tìm và đi tới địa điểm chỉ bằng lời nói",
            "action": {"type": "voice"},
        }
    )

    # 7) Hẹn nhóm.
    chips.append(
        {
            "id": "meetup",
            "kind": "meetup",
            "icon": "🤝",
            "title": "Hẹn nhóm",
            "subtitle": "Tìm quán công bằng cho mọi người",
            "action": {"type": "meetup"},
        }
    )

    return {
        "date": today.isoformat(),
        "lunarDate": lunar_label(today) if vietnam else None,
        "country": "VN" if vietnam else None,
        "calendarAvailable": vietnam,
        "suggestions": chips,
    }


# --- Tour thuyết minh -------------------------------------------------------------

# Tốc độ đi bộ và hệ số đường vòng (đường thật dài hơn đường chim bay) — chỉ để
# XẾP điểm; thời gian hiển thị lấy từ OSRM foot khi có.
WALK_METERS_PER_MINUTE = 75.0
STREET_FACTOR = 1.3
DWELL_MINUTES = 12
MAX_TOUR_STOPS = 8
# Người dùng cách điểm đầu xa hơn mức này thì chặng tới điểm đầu tính bằng xe
# máy, không cộng vào thời lượng đi bộ của tour.
WALK_TO_START_MAX_METERS = 900
MOTORBIKE_METERS_PER_MINUTE = 350.0  # ~21 km/h nội thành, chỉ dùng khi OSRM tắt


def _tour_candidates(lat: float, lng: float, radius_m: float) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT p.id::text AS "poiId", p.name, p.category, k.content_type AS "contentType",
                   k.intro,
                   ST_Y(p.location::geometry) AS latitude,
                   ST_X(p.location::geometry) AS longitude,
                   ST_Distance(p.location, ST_SetSRID(ST_MakePoint(%(lng)s, %(lat)s), 4326)::geography)
                       AS "distanceMeters"
            FROM poi_knowledge k JOIN pois p ON p.id = k.poi_id
            WHERE k.content_type = ANY(%(types)s)
              AND ST_DWithin(p.location, ST_SetSRID(ST_MakePoint(%(lng)s, %(lat)s), 4326)::geography,
                             %(radius)s)
            ORDER BY "distanceMeters"
            """,
            {"lat": lat, "lng": lng, "radius": radius_m, "types": list(TOUR_CONTENT_TYPES)},
        ).fetchall()
    return [dict(row) for row in rows]


def _walk_minutes(a: dict[str, Any], b: dict[str, Any]) -> float:
    meters = haversine_m(a["latitude"], a["longitude"], b["latitude"], b["longitude"])
    return meters * STREET_FACTOR / WALK_METERS_PER_MINUTE


def order_stops(candidates: list[dict[str, Any]], budget_minutes: int) -> list[dict[str, Any]]:
    """Bắt đầu từ điểm gần người dùng nhất, mỗi bước đi tới điểm gần nhất còn
    lại, dừng khi (đi bộ + tham quan) vượt ``budget_minutes``.

    Tham lam láng giềng gần nhất: với ≤ 8 điểm trong một quận, lộ trình này đủ
    tốt và — quan trọng hơn — người nghe hiểu được vì sao đi thứ tự này.
    """
    if not candidates:
        return []
    remaining = list(candidates[1:])
    tour = [candidates[0]]
    used = DWELL_MINUTES
    while remaining and len(tour) < MAX_TOUR_STOPS:
        current = tour[-1]
        nearest = min(remaining, key=lambda item: _walk_minutes(current, item))
        cost = _walk_minutes(current, nearest) + DWELL_MINUTES
        if used + cost > budget_minutes:
            break
        tour.append(nearest)
        remaining.remove(nearest)
        used += cost
    return tour


def _first_sentence(text: str | None, limit: int = 160) -> str | None:
    if not text:
        return None
    sentence = text.strip().split(". ")[0].strip()
    if len(sentence) > limit:
        sentence = sentence[: limit - 1].rstrip() + "…"
    return sentence if sentence.endswith(("…", ".")) else sentence + "."


def plan_tour(lat: float, lng: float, minutes: int) -> dict[str, Any]:
    """Tour đi bộ có thuyết minh bắt đầu gần người dùng."""
    candidates = _tour_candidates(lat, lng, TOUR_SEARCH_RADIUS_METERS)
    if not candidates:
        return {"status": "none", "stops": []}
    stops = order_stops(candidates, minutes)

    walk_points = [(stop["latitude"], stop["longitude"]) for stop in stops]
    walked = directions.route_via(walk_points, "foot") if len(walk_points) > 1 else None
    if walked is not None:
        legs = walked["legs"]
        geometry = walked["geometry"]
        walk_meters = walked["distanceMeters"]
        walk_minutes = walked["durationSeconds"] / 60
        approximate = False
    else:
        # OSRM đi bộ không chạy: ước lượng đường chim bay × hệ số, VẼ đường
        # thẳng và đánh dấu approximate — không giả vờ là đường đi thật.
        legs = [
            {
                "distanceMeters": round(
                    haversine_m(a["latitude"], a["longitude"], b["latitude"], b["longitude"])
                    * STREET_FACTOR,
                    1,
                ),
                "durationSeconds": round(_walk_minutes(a, b) * 60, 1),
            }
            for a, b in zip(stops, stops[1:])
        ]
        geometry = {
            "type": "LineString",
            "coordinates": [[stop["longitude"], stop["latitude"]] for stop in stops],
        }
        walk_meters = sum(leg["distanceMeters"] for leg in legs)
        walk_minutes = sum(leg["durationSeconds"] for leg in legs) / 60
        approximate = True

    first = stops[0]
    to_start_meters = float(first["distanceMeters"])
    if to_start_meters <= WALK_TO_START_MAX_METERS:
        approach = {"mode": "foot", "minutes": max(1, round(to_start_meters * STREET_FACTOR / WALK_METERS_PER_MINUTE))}
    else:
        ride = directions.route(lat, lng, first["latitude"], first["longitude"], "motorbike")
        approach = {
            "mode": "motorbike",
            "minutes": ride["durationMinutes"]
            if ride
            else max(1, round(to_start_meters * STREET_FACTOR / MOTORBIKE_METERS_PER_MINUTE)),
            "approximate": ride is None or bool(ride.get("approximate")),
        }
    approach["distanceMeters"] = round(to_start_meters)

    shaped_stops = []
    for index, stop in enumerate(stops):
        leg = legs[index - 1] if index > 0 and index - 1 < len(legs) else None
        shaped_stops.append(
            {
                "order": index + 1,
                "poiId": stop["poiId"],
                "name": stop["name"],
                "category": stop["category"],
                "contentType": stop["contentType"],
                "latitude": stop["latitude"],
                "longitude": stop["longitude"],
                "teaser": _first_sentence(stop.get("intro")),
                "legMeters": leg["distanceMeters"] if leg else None,
                "legMinutes": max(1, round(leg["durationSeconds"] / 60)) if leg else None,
            }
        )

    return {
        "status": "ready",
        "budgetMinutes": minutes,
        "stops": shaped_stops,
        "geometry": geometry,
        "walkMeters": round(walk_meters),
        "walkMinutes": round(walk_minutes),
        "dwellMinutes": DWELL_MINUTES,
        "totalMinutes": round(walk_minutes + DWELL_MINUTES * len(stops)),
        "approach": approach,
        "approximate": approximate,
    }


# --- Hẹn nhóm ---------------------------------------------------------------------

MEETUP_CATEGORIES: dict[str, tuple[str, ...]] = {
    "cafe": ("cafe",),
    "food": ("restaurant", "fast_food", "food_court"),
    "bar": ("bar", "pub"),
}
MEETUP_CANDIDATES = 60
MEETUP_RESULTS = 5
PARKING_NEAR_METERS = 150


def _centroid(points: list[tuple[float, float]]) -> tuple[float, float]:
    return (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
    )


def _meetup_candidates(
    center: tuple[float, float], radius_m: float, categories: tuple[str, ...], need_parking: bool
) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            """
            WITH c AS (SELECT ST_SetSRID(ST_MakePoint(%(lng)s, %(lat)s), 4326)::geography AS g)
            SELECT p.id::text AS "poiId", p.name, p.category, p.address, p.rating,
                   ST_Y(p.location::geometry) AS latitude,
                   ST_X(p.location::geometry) AS longitude,
                   ST_Distance(p.location, c.g) AS "centerMeters",
                   park.name AS "parkingName", park.d AS "parkingMeters"
            FROM pois p CROSS JOIN c
            LEFT JOIN LATERAL (
                SELECT q.name, ST_Distance(q.location, p.location) AS d
                FROM pois q
                WHERE q.category = 'parking'
                  AND ST_DWithin(q.location, p.location, %(park)s)
                ORDER BY q.location <-> p.location
                LIMIT 1
            ) park ON TRUE
            WHERE p.category = ANY(%(cats)s)
              AND COALESCE(p.name, '') <> ''
              AND ST_DWithin(p.location, c.g, %(radius)s)
              AND (NOT %(need_parking)s OR park.name IS NOT NULL OR park.d IS NOT NULL)
            ORDER BY p.location <-> c.g
            LIMIT %(limit)s
            """,
            {
                "lat": center[0],
                "lng": center[1],
                "radius": radius_m,
                "cats": list(categories),
                "park": PARKING_NEAR_METERS,
                "need_parking": need_parking,
                "limit": MEETUP_CANDIDATES,
            },
        ).fetchall()
    return [dict(row) for row in rows]


def plan_meetup(
    participants: list[dict[str, Any]], category: str = "cafe", need_parking: bool = False
) -> dict[str, Any]:
    """Quán hẹn "công bằng": nhỏ nhất hoá thời gian của người đi XA NHẤT.

    Tiêu chí minimax chứ không phải tổng: tổng nhỏ nhất có thể bắt một người đi
    40 phút để ba người kia mỗi người đỡ 5 phút — đúng kiểu hẹn gây cãi nhau.
    Hoà thì so tổng thời gian. Kèm một phương án đối chứng: quán gần ĐIỂM GIỮA
    TRÊN BẢN ĐỒ nhất — cách mọi người vẫn hay chọn — để thấy chênh lệch thật.
    """
    points = [(float(p["latitude"]), float(p["longitude"])) for p in participants]
    center = _centroid(points)
    spread = max(haversine_m(center[0], center[1], lat, lng) for lat, lng in points)
    radius = min(6_000.0, max(1_200.0, spread * 0.5 + 800.0))
    categories = MEETUP_CATEGORIES.get(category, MEETUP_CATEGORIES["cafe"])

    candidates = _meetup_candidates(center, radius, categories, need_parking)
    if not candidates:
        return {"status": "none", "results": [], "center": {"latitude": center[0], "longitude": center[1]}}

    table = directions.duration_table(
        points, [(c["latitude"], c["longitude"]) for c in candidates], "motorbike"
    )
    approximate = table is None or bool(table.get("approximate"))
    scored: list[dict[str, Any]] = []
    for j, candidate in enumerate(candidates):
        minutes: list[float] = []
        for i, (lat, lng) in enumerate(points):
            seconds = None
            if table is not None:
                row = table["durations"][i] if i < len(table["durations"]) else []
                seconds = row[j] if j < len(row) else None
            if seconds is None:
                if table is not None:
                    break  # OSRM nói không có đường — bỏ ứng viên này
                seconds = (
                    haversine_m(lat, lng, candidate["latitude"], candidate["longitude"])
                    * STREET_FACTOR / MOTORBIKE_METERS_PER_MINUTE * 60
                )
            minutes.append(seconds / 60)
        if len(minutes) != len(points):
            continue
        scored.append(
            {
                **candidate,
                "minutes": [max(1, round(value)) for value in minutes],
                "maxMinutes": max(1, round(max(minutes))),
                "totalMinutes": round(sum(minutes)),
                "spreadMinutes": round(max(minutes) - min(minutes)),
                "_sort": (max(minutes), sum(minutes)),
            }
        )
    if not scored:
        return {"status": "none", "results": [], "center": {"latitude": center[0], "longitude": center[1]}}

    baseline = min(scored, key=lambda item: item["centerMeters"])
    scored.sort(key=lambda item: item["_sort"])

    def shape(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "poiId": item["poiId"],
            "name": item["name"],
            "category": item["category"],
            "address": item["address"],
            "rating": float(item["rating"]) if item["rating"] is not None else None,
            "latitude": item["latitude"],
            "longitude": item["longitude"],
            "minutes": item["minutes"],
            "maxMinutes": item["maxMinutes"],
            "totalMinutes": item["totalMinutes"],
            "spreadMinutes": item["spreadMinutes"],
            "parking": (
                {"name": item["parkingName"], "distanceMeters": round(float(item["parkingMeters"]))}
                if item["parkingMeters"] is not None
                else None
            ),
        }

    return {
        "status": "ready",
        "mode": "motorbike",
        "approximate": approximate,
        "center": {"latitude": center[0], "longitude": center[1]},
        "results": [shape(item) for item in scored[:MEETUP_RESULTS]],
        "baseline": shape(baseline),
        "candidateCount": len(scored),
    }

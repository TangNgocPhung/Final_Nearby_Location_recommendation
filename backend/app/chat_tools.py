"""Chat có ngữ cảnh — hỏi tiếp, bộ lọc và công cụ chuyên biệt, TOÀN BỘ bằng luật.

Ba việc, không việc nào gọi LLM (llama3.2:3b trên CPU mất 20-40s chỉ để trích
JSON, xem `chat.rule_based_intent`):

1. **Hỏi tiếp trên kết quả vừa tìm** — "quán thứ 2 mấy giờ đóng cửa?", "chỉ
   đường tới số 1", "còn chỗ khác không?", "gần hơn". Danh sách vừa hiển thị
   được lưu Redis theo phiên (``remember``/``recall``), câu sau tham chiếu
   vào đó thay vì search lại từ đầu với cả câu chữ "thứ 2 mấy giờ".
2. **Điều kiện lọc trong câu** — "đang mở cửa", "mở khuya", "có wifi", "có
   chỗ đậu xe", "xe lăn", "ngồi ngoài trời". Cụm lọc được cắt khỏi câu trước
   khi search (BM25 không phải khớp chữ "wifi"), rồi lọc trên dữ liệu thật.
   Chỉ giữ chỗ CHẮC CHẮN đạt; chỗ thiếu dữ liệu được đếm và nói rõ ra — đo
   2026-10-10: chỉ ~8% POI có giờ mở cửa, ~4% có thẻ wifi. "Rẻ"/"đánh giá
   cao" thì nói thẳng là chưa lọc được: ``price_level`` đang bằng 0 với mọi
   POI và chỉ 28 POI có rating — lọc theo đó sẽ ra danh sách rỗng hoặc sai.
3. **Chuyển sang công cụ chuyên biệt** — xăng, trạm sạc, WC, gửi xe, cửa hàng
   tiện lợi, thời tiết, xe buýt: gọi đúng module đã có (xếp theo thời gian đi
   thật qua OSRM, có giá gửi xe, giờ mở...) thay vì search chung chung.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from . import bus, charging, convenience, fuel, geo_cache, parking, toilets, weather
from .opening_hours import is_open_now
from .poi_features import CATEGORY_KEYWORDS, _has_vietnamese_marks, categories_for_query, normalize_text
from .voice import haversine_m

logger = logging.getLogger("nearby-chat")

TIMEZONE = "Asia/Ho_Chi_Minh"
LAST_KEY_PREFIX = "nearby:chat:last"
# Cùng TTL với lịch sử hội thoại (`chat.HISTORY_TTL_SECONDS`): hết lịch sử thì
# "quán thứ 2" cũng không còn gì để tham chiếu.
LAST_TTL_SECONDS = 30 * 60
# Khớp `MAX_RESULT_CARDS` của khung chat — "số 2" là thẻ thứ 2 người dùng THẤY.
PAGE_SIZE = 5
# Giữ đủ cho vài lần "còn chỗ khác không?" mà không phình Redis.
MAX_REMEMBERED = 40
# Lọc trên tập ứng viên rộng: chỉ ~8% POI có giờ mở cửa, lọc trên 20 kết quả
# đầu thì "cà phê đang mở cửa" gần như luôn rỗng.
FILTER_POOL = 100
SEARCH_MAX_RADIUS = 20_000

_WALK_M_PER_MIN = 75.0
_MOTORBIKE_M_PER_MIN = charging.FALLBACK_SPEED_M_PER_MIN["motorbike"]
_DETOUR = charging.DETOUR_FACTOR


# --- So khớp cụm từ -----------------------------------------------------------

_WORD_RE = re.compile(r"\w+")


def _words(text: str) -> tuple[list[str], list[str]]:
    """Từ gốc (giữ dấu) và từ đã bỏ dấu, song song từng vị trí."""
    pairs = [(word, normalize_text(word)) for word in _WORD_RE.findall(text or "")]
    pairs = [(word, folded) for word, folded in pairs if folded and " " not in folded]
    return [word for word, _ in pairs], [folded for _, folded in pairs]


def _accented(text: str) -> str:
    return " " + " ".join(_WORD_RE.findall(unicodedata.normalize("NFC", (text or "").lower()))) + " "


def _strip_phrases(words: list[str], folded: list[str], keep: list[bool], phrases: tuple[str, ...]) -> bool:
    """Đánh dấu bỏ mọi lần xuất hiện của ``phrases`` (dài trước) — trả True
    nếu có khớp. Từ đã bị cụm khác lấy thì không khớp lại."""
    matched = False
    for phrase in sorted(phrases, key=lambda value: len(value.split()), reverse=True):
        parts = phrase.split()
        size = len(parts)
        for start in range(0, len(folded) - size + 1):
            if all(keep[start + i] and folded[start + i] == parts[i] for i in range(size)):
                for i in range(size):
                    keep[start + i] = False
                matched = True
    return matched


# --- (2) Bộ lọc ----------------------------------------------------------------

_PARKING_OBJECTS = ("xe", "xe o to", "xe oto", "xe hoi", "xe may", "o to", "oto")
_PARKING_PHRASES = tuple(
    f"{head} {verb} {obj}"
    for head in ("co cho", "co bai", "co noi", "co")
    for verb in ("dau", "do", "gui", "giu", "de")
    for obj in _PARKING_OBJECTS
) + ("co bai xe", "co parking", "co bai do xe", "co bai giu xe")

# (khoá, nhãn hiển thị, cụm từ đã bỏ dấu). Thứ tự quan trọng: "còn mở khuya"
# phải thành "mở khuya" chứ không bị "còn mở" (= đang mở) ăn mất.
FILTERS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "open_late",
        "mở khuya",
        ("mo cua khuya", "mo khuya", "mo toi khuya", "mo den khuya", "mo dem", "mo xuyen dem",
         "xuyen dem", "thau dem", "24 7", "24h", "24 24", "mo 24 gio", "ca dem"),
    ),
    (
        "open_now",
        "đang mở cửa",
        ("dang mo cua", "dang mo", "con mo cua", "con mo", "mo cua luc nay", "mo cua bay gio",
         "dang hoat dong", "dang ban", "mo cua"),
    ),
    ("wifi", "có wifi", ("co wifi", "co wi fi", "wifi", "wi fi", "co mang", "co internet")),
    ("parking", "có chỗ đậu xe", _PARKING_PHRASES),
    (
        "wheelchair",
        "có lối cho xe lăn",
        ("co loi di cho xe lan", "loi di cho xe lan", "cho xe lan", "xe lan",
         "cho nguoi khuyet tat", "nguoi khuyet tat", "khuyet tat"),
    ),
    ("outdoor", "có chỗ ngồi ngoài trời", ("cho ngoi ngoai troi", "ngoi ngoai troi", "ban ngoai troi", "ngoai troi", "ngoi via he")),
)
FILTER_LABELS = {key: label for key, label, _ in FILTERS}

# Điều kiện người dùng hay hỏi nhưng dữ liệu CHƯA đủ để lọc — cắt khỏi câu
# search và nói rõ là đã bỏ qua, không giả vờ đã lọc.
UNSUPPORTED: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("cheap", "giá rẻ", ("gia re", "re hon", "re re", "binh dan", "gia mem", "hat de", "re")),
    (
        "rating",
        "đánh giá cao",
        ("duoc danh gia cao", "danh gia cao", "danh gia tot", "rating cao", "review tot",
         "review cao", "nhieu sao", "tren 4 sao", "4 sao", "5 sao"),
    ),
)
UNSUPPORTED_LABELS = {key: label for key, label, _ in UNSUPPORTED}


@dataclass
class Filters:
    text: str  # câu đã cắt các cụm lọc (giữ dấu)
    keys: tuple[str, ...] = ()
    unsupported: tuple[str, ...] = ()
    leftover: list[str] = field(default_factory=list)  # từ còn lại, đã bỏ dấu

    def __bool__(self) -> bool:
        return bool(self.keys or self.unsupported)


def extract_filters(message: str) -> Filters:
    words, folded = _words(message)
    keep = [True] * len(words)
    keys = tuple(key for key, _, phrases in FILTERS if _strip_phrases(words, folded, keep, phrases))
    unsupported = tuple(key for key, _, phrases in UNSUPPORTED if _strip_phrases(words, folded, keep, phrases))
    if not keys and not unsupported:
        return Filters(text=message.strip(), leftover=folded)
    text = " ".join(word for word, flag in zip(words, keep) if flag)
    return Filters(
        text=text,
        keys=keys,
        unsupported=unsupported,
        leftover=[word for word, flag in zip(folded, keep) if flag],
    )


_WIFI_VALUES = frozenset({"wlan", "yes", "wifi", "wired", "free", "terminal"})
_WHEELCHAIR_VALUES = frozenset({"yes", "limited", "designated"})


def _late_moment(now: datetime) -> datetime:
    """Mốc "mở khuya": 22:30 tối nay. Đã quá giờ đó (hoặc đang rạng sáng) thì
    hỏi "mở khuya" nghĩa là còn mở ngay lúc này."""
    if now.hour >= 23 or now.hour < 4 or (now.hour == 22 and now.minute >= 30):
        return now
    return now.replace(hour=22, minute=30, second=0, microsecond=0)


def poi_passes(poi: dict[str, Any], key: str, now: datetime) -> bool | None:
    """True/False khi dữ liệu nói rõ; None = không có dữ liệu để kết luận."""
    amenities = poi.get("amenities") or {}
    if key == "open_now":
        return poi.get("openNow")
    if key == "open_late":
        schedule = poi.get("openingHours")
        if not isinstance(schedule, dict):
            return None
        return is_open_now(schedule, poi.get("timezone") or TIMEZONE, _late_moment(now))
    if key == "wifi":
        value = amenities.get("internet_access")
        return None if value is None else value in _WIFI_VALUES
    if key == "parking":
        value = amenities.get("parking")
        return None if value is None else value != "no"
    if key == "wheelchair":
        value = amenities.get("wheelchair")
        return None if value is None else value in _WHEELCHAIR_VALUES
    if key == "outdoor":
        value = amenities.get("outdoor_seating")
        return None if value is None else value == "yes"
    return None


def apply_filters(
    results: list[dict[str, Any]], keys: tuple[str, ...], now: datetime | None = None
) -> tuple[list[dict[str, Any]], int]:
    """``(chỗ chắc chắn đạt mọi điều kiện, số chỗ bị loại vì THIẾU dữ liệu)``."""
    if not keys:
        return results, 0
    now = now or datetime.now(ZoneInfo(TIMEZONE))
    kept: list[dict[str, Any]] = []
    unknown = 0
    for poi in results:
        verdicts = [poi_passes(poi, key, now) for key in keys]
        if all(verdict is True for verdict in verdicts):
            kept.append(poi)
        elif False not in verdicts:
            unknown += 1
    return kept, unknown


def filter_note(keys: tuple[str, ...], unsupported: tuple[str, ...] = (), unknown: int = 0) -> str | None:
    parts = []
    if keys:
        labels = _join_vi([FILTER_LABELS[key] for key in keys])
        sentence = f"Mình chỉ giữ chỗ ghi rõ là {labels}"
        if unknown:
            sentence += f"; {unknown} chỗ khác chưa có dữ liệu này nên chưa tính"
        parts.append(sentence + ".")
    if unsupported:
        labels = _join_vi([UNSUPPORTED_LABELS.get(key) or FILTER_LABELS[key] for key in unsupported])
        parts.append(f"Dữ liệu hiện chưa đủ để lọc theo {labels} nên mình bỏ qua điều kiện này.")
    return " ".join(parts) or None


def is_empty_subject(folded_words: list[str]) -> bool:
    """Câu không còn chủ đề tìm kiếm nào ("chỗ nào …" sau khi bỏ "có wifi")."""
    return all(word in _FILLER_WORDS for word in folded_words)


def plain_category(filters: Filters) -> str | None:
    """Phần câu còn lại sau khi cắt bộ lọc CHỈ là tên một loại địa điểm ("cà
    phê", "quán ăn") → trả loại đó để search lọc thẳng theo loại, không tạo
    embedding. Câu lọc phải xét cả trăm ứng viên, và đường BM25/Vector đo
    được thật (2026-10-10) mất tới 100s khi Ollama đang bận reindex."""
    categories = categories_for_query(filters.text)
    if len(categories) != 1:
        return None
    words = list(filters.leftover)
    keep = [True] * len(words)
    keywords = tuple(normalize_text(keyword) for keyword in CATEGORY_KEYWORDS[categories[0]])
    _strip_phrases(words, words, keep, keywords)
    rest = [word for word, flag in zip(words, keep) if flag]
    return categories[0] if is_empty_subject(rest) else None


# --- Định dạng câu trả lời ----------------------------------------------------


def _join_vi(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " và " + items[-1]


def format_distance(meters: Any) -> str | None:
    if not isinstance(meters, (int, float)):
        return None
    # Cùng cách viết với `chat._format_distance` — câu trả lời và thẻ khớp số.
    if round(meters) < 1000:
        return f"{round(meters)} m"
    return f"{meters / 1000:.1f}".replace(".", ",") + " km"


def _minutes(meters: float, speed: float) -> int:
    return max(1, round(meters * _DETOUR / speed))


def _clock(now: datetime, minutes: int) -> str:
    return (now + timedelta(minutes=minutes)).strftime("%H:%M")


def _vnd(amount: int) -> str:
    return f"{amount:,}".replace(",", ".") + "đ"


# --- (1) Ngữ cảnh lượt trước ---------------------------------------------------


def _key(session_id: str) -> str:
    return f"{LAST_KEY_PREFIX}:{session_id}"


def compact(poi: dict[str, Any], latitude: float | None = None, longitude: float | None = None) -> dict[str, Any]:
    """Đúng các trường cần để trả lời câu hỏi tiếp và vẽ thẻ — kết quả xếp hạng
    có cả trăm trường, lưu nguyên vào Redis là phí."""
    schedule = poi.get("openingHours")
    hours = poi.get("hours") or {}
    distance = poi.get("distanceMeters")
    if latitude is not None and poi.get("latitude") is not None:
        distance = round(haversine_m(latitude, longitude, float(poi["latitude"]), float(poi["longitude"])))
    open_now = poi.get("openNow", hours.get("openNow"))
    return {
        "id": poi["id"],
        "name": poi.get("name"),
        "category": poi.get("category"),
        "categoryLabel": poi.get("categoryLabel"),
        "address": poi.get("address") or poi.get("streetAddress"),
        "latitude": poi.get("latitude"),
        "longitude": poi.get("longitude"),
        "distanceMeters": distance,
        "rating": poi.get("rating"),
        "openNow": open_now,
        "closesInMinutes": poi.get("closesInMinutes", hours.get("closesInMinutes")),
        "opensInMinutes": poi.get("opensInMinutes"),
        "openingRaw": schedule.get("raw") if isinstance(schedule, dict) else hours.get("raw"),
        "alwaysOpen": bool(schedule.get("alwaysOpen")) if isinstance(schedule, dict) else bool(hours.get("alwaysOpen")),
        "amenities": poi.get("amenities") or {},
        "busyness": poi.get("busyness"),
        "detail": poi.get("detail"),
        "travelMinutes": poi.get("travelMinutes"),
    }


def remember(session_id: str, context: dict[str, Any]) -> None:
    client = geo_cache.get_client()
    if client is None:
        return
    context = {**context, "results": context.get("results", [])[:MAX_REMEMBERED]}
    try:
        client.set(_key(session_id), json.dumps(context, ensure_ascii=False, default=str), ex=LAST_TTL_SECONDS)
    except Exception:  # noqa: BLE001 - mất ngữ cảnh chỉ làm câu sau thành câu mới
        logger.warning("Không lưu được ngữ cảnh chat cho session %s", session_id)


def recall(session_id: str) -> dict[str, Any] | None:
    client = geo_cache.get_client()
    if client is None:
        return None
    try:
        raw = client.get(_key(session_id))
        return json.loads(raw) if raw else None
    except Exception:  # noqa: BLE001
        return None


def forget(session_id: str) -> None:
    client = geo_cache.get_client()
    if client is None:
        return
    try:
        client.delete(_key(session_id))
    except Exception:  # noqa: BLE001 - tự hết hạn sau LAST_TTL_SECONDS
        pass


# Từ "rỗng" còn lại sau khi bỏ cụm hỏi tiếp/lọc: câu chỉ còn những từ này
# nghĩa là KHÔNG nêu chủ đề mới ("còn chỗ nào khác không?") — khác với "còn
# quán phở nào khác" (còn "pho" → tìm mới).
_FILLER_WORDS = frozenset(
    """a ah a ak ba ban bai bay cai cay chi cho co con cu cua da day de den di dia diem do duoc gan giup gi
    hay hon k ko khong khac la loc luc ma may minh nao nay nha nhe nhi nhung no noi nua o oi quan roi
    sao so tai the thi them thoi tiem tiep toi tram trong va vay voi xem xin y goi""".split()
)

_MORE_PHRASES = (
    "cho khac", "quan khac", "noi khac", "cai khac", "tiem khac", "tram khac", "cay khac", "bai khac",
    "dia diem khac", "con nua", "xem them", "them nua", "goi y them", "con nao", "khac khong", "tiep theo",
    "them", "khac", "tiep",
)
_CLOSER_PHRASES = ("gan hon nua", "gan hon", "gan nhat", "gan thoi", "gan gan")
_FARTHER_PHRASES = ("xa hon nua", "xa hon", "rong hon", "mo rong", "xa them", "ban kinh lon hon")
_DIRECTIONS_PHRASES = (
    "chi duong", "duong di", "dan duong", "dan toi", "dan den", "di toi", "di den", "di the nao",
    "di sao", "di nhu the nao", "bao xa", "mat bao lau", "bao lau", "di bao lau",
)
_HOURS_PHRASES = (
    "may gio", "gio mo", "gio dong", "dong cua", "mo cua", "con mo", "dang mo", "mo den", "gio giac",
    "luc nao mo", "luc nao dong", "dong luc",
)
_ADDRESS_PHRASES = ("dia chi", "o dau", "nam o dau", "so nha", "duong nao")
_PRONOUN_PHRASES = (
    "quan do", "cho do", "cai do", "tiem do", "noi do", "dia diem do", "toi do", "den do",
    "tram do", "cay xang do", "quan nay", "cho nay", "cai nay", "o do",
)
_ORDINAL_WORDS = {
    "nhat": 1, "mot": 1, "1": 1, "nhi": 2, "hai": 2, "2": 2, "ba": 3, "3": 3, "tu": 4, "bon": 4, "4": 4,
    "nam": 5, "5": 5,
}
# "thứ 2"/"số 2"/"cái 2" — KHÔNG nhận "quán 1" (= Quận 1 khi bỏ dấu) hay "chỗ 2"
# ("cho 2 người").
_ORDINAL_RE = re.compile(r"\b(?:thu|so|cai)\s+(\d{1,2}|nhat|nhi|mot|hai|ba|tu|bon|nam)\b")
# Tên quán bắt đầu bằng hai từ này thì hai từ đầu không đủ để nhận ra quán.
_GENERIC_NAME_HEADS = frozenset(
    {"ca phe", "quan an", "nha hang", "cua hang", "banh mi", "com tam", "tra sua", "sieu thi", "nha thuoc", "cay xang", "tram sac"}
)


def _ordinal(folded: str, page_size: int) -> int | None:
    padded = f" {folded} "
    if " dau tien " in padded:
        return 1
    if " cuoi cung " in padded or " cai cuoi " in padded:
        return page_size
    match = _ORDINAL_RE.search(folded)
    if match is None:
        return None
    value = match.group(1)
    return int(value) if value.isdigit() else _ORDINAL_WORDS.get(value)


def _name_reference(folded: str, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    padded = f" {folded} "
    best: tuple[int, dict[str, Any]] | None = None
    for poi in candidates:
        name = normalize_text(poi.get("name"))
        if len(name) < 4:
            continue
        keys = [name]
        parts = name.split()
        head = " ".join(parts[:2])
        if len(parts) >= 3 and len(head) >= 6 and head not in _GENERIC_NAME_HEADS:
            keys.append(head)
        for key in keys:
            if f" {key} " in padded and (best is None or len(key) > best[0]):
                best = (len(key), poi)
    return best[1] if best else None


def _only_fillers(folded_words: list[str], phrases: tuple[str, ...]) -> bool:
    words = list(folded_words)
    keep = [True] * len(words)
    _strip_phrases(words, words, keep, phrases)
    return all(word in _FILLER_WORDS for word, flag in zip(words, keep) if flag)


def _question(folded: str) -> str:
    padded = f" {folded} "
    for kind, phrases in (
        ("directions", _DIRECTIONS_PHRASES),
        ("hours", _HOURS_PHRASES),
        ("address", _ADDRESS_PHRASES),
    ):
        if any(f" {phrase} " in padded for phrase in phrases):
            return kind
    return "details"


def answer_about(poi: dict[str, Any], question: str, now: datetime | None = None) -> str:
    """Trả lời một câu hỏi về MỘT địa điểm, chỉ từ dữ liệu đã có."""
    now = now or datetime.now(ZoneInfo(TIMEZONE))
    name = poi.get("name") or "Địa điểm này"
    distance = poi.get("distanceMeters")
    distance_text = format_distance(distance)

    if question == "directions":
        if distance_text is None:
            return f"Bấm “Chỉ đường” bên dưới để xem tuyến tới {name} trên bản đồ."
        walk = _minutes(distance, _WALK_M_PER_MIN)
        ride = _minutes(distance, _MOTORBIKE_M_PER_MIN)
        travel = f"khoảng {walk} phút đi bộ" if walk <= 20 else f"khoảng {ride} phút đi xe máy"
        return (
            f"{name} cách bạn {distance_text} đường chim bay, {travel} (ước tính). "
            "Bấm “Chỉ đường” bên dưới để xem tuyến thật trên bản đồ."
        )

    if question == "address":
        address = poi.get("address")
        where = f"Địa chỉ của {name}: {address}." if address else f"Bản đồ chưa ghi địa chỉ cụ thể của {name}."
        return f"{where} Cách bạn {distance_text}." if distance_text else where

    hours = _hours_sentence(poi, now)
    if question == "hours":
        return hours or f"Mình chưa có giờ mở cửa của {name} — dữ liệu bản đồ chưa ghi."

    parts = [name]
    if poi.get("categoryLabel"):
        parts[0] += f" ({poi['categoryLabel']})"
    if distance_text:
        parts[0] += f" cách bạn {distance_text}"
    sentences = [parts[0] + "."]
    if hours:
        sentences.append(hours)
    if poi.get("address"):
        sentences.append(f"Địa chỉ: {poi['address']}.")
    extras = _amenity_words(poi.get("amenities") or {})
    if extras:
        sentences.append(_join_vi(extras).capitalize() + ".")
    if isinstance(poi.get("rating"), (int, float)):
        sentences.append(f"Đánh giá {poi['rating']:.1f}/5.".replace(".", ",", 1))
    if poi.get("detail"):
        sentences.append(f"{poi['detail']}.")
    return " ".join(sentences)


def _hours_sentence(poi: dict[str, Any], now: datetime) -> str | None:
    name = poi.get("name") or "Chỗ này"
    raw = poi.get("openingRaw")
    raw_note = f" (giờ ghi trên bản đồ: {raw})" if raw else ""
    if poi.get("alwaysOpen"):
        return f"{name} mở cửa 24/7."
    if poi.get("openNow") is True:
        closes = poi.get("closesInMinutes")
        if closes is not None:
            return f"{name} đang mở, đóng cửa lúc {_clock(now, closes)} — còn khoảng {_say_duration(closes)}{raw_note}."
        return f"{name} đang mở cửa{raw_note}."
    if poi.get("openNow") is False:
        opens = poi.get("opensInMinutes")
        if opens is not None:
            return f"{name} đang đóng cửa, mở lại lúc {_clock(now, opens)}{raw_note}."
        return f"{name} đang đóng cửa{raw_note}."
    if raw:
        return f"Giờ mở cửa của {name} ghi trên bản đồ: {raw}."
    return None


def _say_duration(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} phút"
    hours, rest = divmod(minutes, 60)
    return f"{hours} giờ" + (f" {rest} phút" if rest else "")


def _amenity_words(amenities: dict[str, Any]) -> list[str]:
    words = []
    if amenities.get("internet_access") in _WIFI_VALUES:
        words.append("có wifi")
    if amenities.get("parking") not in (None, "no"):
        words.append("có chỗ đậu xe")
    if amenities.get("wheelchair") in _WHEELCHAIR_VALUES:
        words.append("có lối cho xe lăn")
    if amenities.get("outdoor_seating") == "yes":
        words.append("có chỗ ngồi ngoài trời")
    return words


def listing(results: list[dict[str, Any]], lead: str = "Gần bạn có") -> str:
    items = []
    for poi in results[:3]:
        if not poi.get("name"):
            continue
        minutes = poi.get("travelMinutes")
        extra = f"{minutes} phút" if minutes else format_distance(poi.get("distanceMeters"))
        items.append(f"{poi['name']} ({extra})" if extra else poi["name"])
    return f"{lead} {_join_vi(items)}." if items else "Bạn xem các thẻ bên dưới nhé."


def follow_up(message: str, last: dict[str, Any] | None, latitude: float, longitude: float) -> dict[str, Any] | None:
    """Câu này có phải câu hỏi tiếp trên danh sách vừa hiển thị không.

    Trả ``None`` (= tìm mới như bình thường) hoặc một kế hoạch:

    - ``{"type": "answer", "reply", "results", "focus", "directions"?}``
    - ``{"type": "page" | "reorder", "reply", "results", "page_start"}`` —
      trang kế / xếp lại theo khoảng cách
    - ``{"type": "rerun", "radius"?, "filters"?}`` — bên gọi chạy lại search/công cụ
    - ``{"type": "clarify", "reply"}``
    """
    if not last or not last.get("results"):
        return None
    folded = normalize_text(message)
    if not folded:
        return None
    words = folded.split()
    results: list[dict[str, Any]] = last["results"]
    page_start = int(last.get("page_start") or 0)
    page = results[page_start : page_start + PAGE_SIZE]
    padded = f" {folded} "

    # Tham chiếu một địa điểm cụ thể: số thứ tự, tên, hay "quán đó".
    target = None
    index = _ordinal(folded, len(page))
    if index is not None and 1 <= index <= len(page):
        target = page[index - 1]
    question = _question(folded)
    if target is None and (question != "details" or len(words) <= 6):
        # Nêu tên mà không hỏi gì ("Highlands Coffee gần đây") trong một câu
        # dài thì là tìm mới — có thể người dùng muốn chi nhánh khác.
        target = _name_reference(folded, page) or _name_reference(folded, results)
    if target is None and any(f" {phrase} " in padded for phrase in _PRONOUN_PHRASES):
        focus = last.get("focus")
        target = next((poi for poi in results if poi["id"] == focus), None)
        if target is None and len(page) == 1:
            target = page[0]

    if target is not None:
        target = {
            **target,
            "distanceMeters": round(
                haversine_m(latitude, longitude, float(target["latitude"]), float(target["longitude"]))
            )
            if target.get("latitude") is not None
            else target.get("distanceMeters"),
        }
        plan: dict[str, Any] = {
            "type": "answer",
            "reply": answer_about(target, question),
            "results": [target],
            "focus": target["id"],
            "question": question,
        }
        if question == "directions":
            plan["directions"] = {"poiId": target["id"], "name": target.get("name")}
        return plan

    filters = extract_filters(message)
    leftover = filters.leftover
    if _only_fillers(leftover, _MORE_PHRASES) and any(f" {phrase} " in padded for phrase in _MORE_PHRASES) and len(words) <= 8:
        next_start = page_start + PAGE_SIZE
        more = results[next_start : next_start + PAGE_SIZE]
        if not more:
            return {
                "type": "clarify",
                "reply": "Mình đã cho bạn xem hết các chỗ tìm được rồi. Bạn thử nói “xa hơn” để mở rộng bán kính nhé.",
            }
        return {"type": "page", "reply": listing(more, "Thêm vài chỗ nữa:"), "results": more, "page_start": next_start}

    if _only_fillers(leftover, _CLOSER_PHRASES) and any(f" {phrase} " in padded for phrase in _CLOSER_PHRASES):
        nearest = sorted(
            results,
            key=lambda poi: (poi.get("distanceMeters") is None, poi.get("distanceMeters") or 0),
        )
        return {
            "type": "reorder",
            "reply": listing(nearest, "Xếp lại theo khoảng cách, gần nhất là"),
            "results": nearest,
            "page_start": 0,
        }

    if _only_fillers(leftover, _FARTHER_PHRASES) and any(f" {phrase} " in padded for phrase in _FARTHER_PHRASES):
        return {"type": "rerun", "radius": int(last.get("radius") or 3000) * 2}

    if filters and _only_fillers(leftover, ()):
        merged = tuple(dict.fromkeys([*last.get("filters", []), *filters.keys]))
        return {"type": "rerun", "filters": merged, "unsupported": filters.unsupported}

    # "mấy giờ đóng cửa?" mà không nói chỗ nào.
    if question != "details" and _only_fillers(words, _DIRECTIONS_PHRASES + _HOURS_PHRASES + _ADDRESS_PHRASES):
        return {
            "type": "clarify",
            "reply": "Bạn hỏi chỗ nào vậy? Ví dụ “số 2 mấy giờ đóng cửa?” hoặc “chỉ đường tới số 1”.",
        }
    return None


# --- (3) Công cụ chuyên biệt --------------------------------------------------

_CAR_WORDS = ("o to", "oto", "xe hoi", "xe 4 banh", "xe bon banh")
_TOOL_PHRASES: dict[str, tuple[str, ...]] = {
    "charging": (
        # Không có "hết pin"/"sạc pin": "điện thoại hết pin" là tìm quán có ổ cắm.
        "tram sac", "tru sac", "sac xe", "sac dien", "cho sac", "sac pin xe", "sac oto", "sac o to",
        "v green", "vgreen",
    ),
    "fuel": ("xang", "cay xang", "tram xang", "do xang", "het xang", "bom xang", "xang dau"),
    "toilets": ("nha ve sinh", "di ve sinh", "ve sinh cong cong", "wc", "toilet", "toa let", "nha wc"),
    "convenience": (
        # Không có "tiện lợi" trần: "chỗ ngồi làm việc tiện lợi" không phải tìm Circle K.
        "cua hang tien loi", "tiem tien loi", "circle k", "circlek", "family mart", "familymart", "gs25", "gs 25", "7 eleven",
        "seven eleven", "7eleven", "ministop", "bach hoa xanh", "co op food", "coop food", "b s mart",
        "bsmart", "shop go", "satrafoods", "satra foods",
    ),
    "parking": ("gui xe", "giu xe", "do xe", "dau xe", "bai xe", "bai do", "bai giu xe", "parking"),
}
# Loại địa điểm "của" từng công cụ — câu nhắc thêm loại KHÁC ("quán cà phê
# gần cây xăng") là tìm quán, không phải tìm cây xăng.
_TOOL_CATEGORIES = {
    "charging": {"charging_station", "parking"},
    "fuel": {"fuel"},
    "toilets": {"toilets"},
    "convenience": {"convenience", "supermarket"},
    "parking": {"parking"},
}
# Cần dấu: bỏ dấu thì "mưa" trùng "mua" (mua sắm) — "chỗ nào có mua sim".
_WEATHER_ACCENTED = (
    "thời tiết", "trời mưa", "có mưa", "mưa không", "sẽ mưa", "sắp mưa", "mưa to", "nhiệt độ",
    "bao nhiêu độ", "trời nắng", "trời nóng", "dự báo",
)
_WEATHER_FOLDED = ("thoi tiet", "troi mua", "nhiet do", "du bao", "mua khong")

TOOL_TITLES = {
    "fuel": "Cây xăng",
    "charging": "Trạm sạc",
    "toilets": "Nhà vệ sinh",
    "convenience": "Cửa hàng tiện lợi",
    "parking": "Chỗ gửi xe",
}
_TOOL_LIMITS = {
    "fuel": (500, 30_000),
    "charging": (500, 30_000),
    "toilets": (300, 15_000),
    "convenience": (300, 15_000),
    "parking": (100, 5_000),
}
_STAY_RE = re.compile(r"\b(\d{1,3})\s*(tieng|gio|h|phut)\b")


def _brand(folded: str, table: tuple[tuple[str, str, tuple[str, ...]], ...]) -> str | None:
    compressed = folded.replace(" ", "")
    for code, _, markers in table:
        if any(marker in compressed for marker in markers):
            return code
    return None


def detect_tool(message: str, filters: Filters | None = None, radius_m: int | None = None) -> dict[str, Any] | None:
    """Câu này nên đi công cụ nào: ``{"tool", "params"}`` hoặc ``None``."""
    filters = filters or extract_filters(message)
    folded = normalize_text(message)
    if not folded:
        return None
    padded = f" {folded} "

    accented = _accented(message)
    weather_hit = any(f" {phrase} " in accented for phrase in _WEATHER_ACCENTED) or (
        not _has_vietnamese_marks(message) and any(f" {phrase} " in padded for phrase in _WEATHER_FOLDED)
    )
    if weather_hit and not categories_for_query(message):
        return {"tool": "weather", "params": {}}

    # "Quán có chỗ đậu xe" đã thành bộ lọc — đọc phần câu còn lại.
    rest_padded = f" {' '.join(filters.leftover)} "
    for tool, phrases in _TOOL_PHRASES.items():
        if not any(f" {phrase} " in rest_padded for phrase in phrases):
            continue
        other = set(categories_for_query(filters.text)) - _TOOL_CATEGORIES[tool]
        if other:
            continue
        return {"tool": tool, "params": _tool_params(tool, padded, filters, radius_m)}
    return None


def _tool_params(tool: str, padded: str, filters: Filters | None, radius_m: int | None) -> dict[str, Any]:
    keys = set(filters.keys) if filters else set()
    car = any(f" {word} " in padded for word in _CAR_WORDS)
    params: dict[str, Any] = {}
    if tool == "fuel":
        params = {"vehicle": "car" if car else "motorbike", "brand": _brand(padded, fuel.BRANDS) or "any", "open_now": "open_now" in keys}
    elif tool == "charging":
        vehicle = "car" if car else ("motorbike" if " xe may " in padded else "any")
        network = "vinfast" if any(f" {w} " in padded for w in ("vinfast", "v green", "vgreen")) else "any"
        params = {"vehicle": vehicle, "network": network, "open_now": "open_now" in keys}
    elif tool == "toilets":
        params = {
            "free_only": any(f" {w} " in padded for w in ("mien phi", "free", "khong mat tien", "khong ton tien")),
            "wheelchair": "wheelchair" in keys,
            "open_now": "open_now" in keys,
        }
    elif tool == "convenience":
        params = {"brand": _brand(padded, convenience.CHAINS) or "any", "open_now": "open_now" in keys}
    elif tool == "parking":
        vehicle = "car" if car else ("bicycle" if " xe dap " in padded else "motorbike")
        minutes = 120
        match = _STAY_RE.search(padded)
        if match:
            value = int(match.group(1))
            minutes = value if match.group(2) == "phut" else value * 60
        params = {"vehicle": vehicle, "minutes": min(max(minutes, 15), 24 * 60)}
    if radius_m is not None:
        low, high = _TOOL_LIMITS[tool]
        params["radius"] = min(max(radius_m, low), high)
    return params


def _open_word(open_now: Any, always: bool = False) -> str | None:
    if always:
        return "Mở 24/7"
    if open_now is True:
        return "Đang mở"
    if open_now is False:
        return "Đang đóng"
    return None


def _card(item: dict[str, Any], label: str, minutes: int | None, unit: str, extras: list[str | None]) -> dict[str, Any]:
    detail_parts = [f"{minutes} phút {unit}" if minutes else None, *extras]
    return {
        **item,
        "categoryLabel": label,
        "travelMinutes": minutes,
        "detail": " · ".join(part for part in detail_parts if part) or None,
    }


def _fuel_cards(found: dict[str, Any]) -> list[dict[str, Any]]:
    unit = "ô tô" if found.get("vehicle") == "car" else "xe máy"
    return [
        _card(
            item, item.get("brand") or "Cây xăng", item.get("driveMinutes"), unit,
            [", ".join(item.get("fuels", [])[:3]) or None, _open_word((item.get("hours") or {}).get("openNow"))],
        )
        for item in found["results"]
    ]


def _charging_cards(found: dict[str, Any]) -> list[dict[str, Any]]:
    unit = "ô tô" if found.get("mode") == "car" else "xe máy"
    cards = []
    for item in found["results"]:
        # `charging.network_of` trả tên hiển thị ("VinFast / V-Green", hoặc operator).
        network = item.get("network")
        hours = item.get("hours") or {}
        cards.append(
            _card(
                {**item, "openNow": hours.get("openNow")},
                f"Trạm sạc {network}" if network else "Trạm sạc",
                item.get("driveMinutes"),
                unit,
                [f"{len(item['sockets'])} loại cổng" if item.get("sockets") else None],
            )
        )
    return cards


def _toilet_cards(found: dict[str, Any]) -> list[dict[str, Any]]:
    unit = "xe máy" if found.get("mode") == "motorbike" else "đi bộ"
    cards = []
    for item in found["results"]:
        fee = {False: "Miễn phí", True: "Có phí"}.get(item.get("fee"))
        extras = [
            fee,
            "Chỉ cho khách" if item.get("customersOnly") else None,
            "Có lối xe lăn" if item.get("wheelchair") == "yes" else None,
            _open_word((item.get("hours") or {}).get("openNow")),
        ]
        cards.append(_card(item, item.get("kindLabel") or "Nhà vệ sinh", item.get("driveMinutes"), unit, extras))
    return cards


def _convenience_cards(found: dict[str, Any]) -> list[dict[str, Any]]:
    cards = []
    for item in found["results"]:
        hours = item.get("hours") or {}
        cards.append(
            _card(
                item, item.get("brand") or "Cửa hàng tiện lợi", item.get("driveMinutes"), "đi bộ",
                [_open_word(hours.get("openNow"), bool(hours.get("alwaysOpen")))],
            )
        )
    return cards


def _parking_cards(found: dict[str, Any]) -> list[dict[str, Any]]:
    hours_text = _say_duration(int(found.get("minutes") or 120))
    cards = []
    for item in found["results"]:
        price = item.get("price") or {}
        cost = price.get("estimatedCost")
        if price.get("free") or cost == 0:
            price_text = "Miễn phí"
        elif cost is not None:
            price_text = f"~{_vnd(int(cost))} cho {hours_text}"
            if price.get("tier") == "reference":
                price_text += " (tham khảo)"
        else:
            price_text = "Chưa rõ giá"
        cards.append(
            _card(
                {**item, "openNow": (item.get("hours") or {}).get("openNow")},
                "Bãi gửi xe", item.get("walkMinutes"), "đi bộ", [price_text],
            )
        )
    return cards


_TOOL_RUNNERS: dict[str, tuple[Callable[..., dict[str, Any]], Callable[[dict[str, Any]], list[dict[str, Any]]]]] = {
    "fuel": (fuel.search_stations, _fuel_cards),
    "charging": (charging.search_stations, _charging_cards),
    "toilets": (toilets.search_toilets, _toilet_cards),
    "convenience": (convenience.search_stores, _convenience_cards),
    "parking": (parking.search, _parking_cards),
}


def weather_reply(latitude: float, longitude: float) -> str:
    current = weather.current_weather(latitude, longitude)
    forecast = weather.rain_forecast(latitude, longitude)
    if current is None and forecast is None:
        return "Mình chưa lấy được dữ liệu thời tiết lúc này, bạn thử lại sau ít phút nhé."
    sentences = []
    if current is not None:
        temperature = current.get("temperatureC")
        state = "đang mưa to" if current.get("isHeavyRain") else "đang mưa" if current.get("isWet") else "đang khô ráo"
        head = f"Quanh bạn {state}"
        if isinstance(temperature, (int, float)):
            head += f", khoảng {round(temperature)}°C"
        sentences.append(head + ".")
    if forecast is not None:
        if forecast.get("time"):
            sentences.append(
                f"Dự báo có khả năng mưa {forecast['probability']}% vào khoảng {forecast['time']}."
            )
        else:
            sentences.append(f"{weather.FORECAST_HOURS} giờ tới ít khả năng mưa.")
    if (current or {}).get("isWet") or (forecast or {}).get("time"):
        sentences.append("Nếu cần chỗ trong nhà, bạn hỏi mình “quán cà phê gần đây” nhé.")
    return " ".join(sentences)


def run_tool(tool: str, params: dict[str, Any], latitude: float, longitude: float) -> tuple[list[dict[str, Any]], str]:
    """Chạy công cụ, trả ``(thẻ, câu trả lời)``. Lỗi DB/OSRM → câu báo lỗi
    thật thà, không bịa kết quả."""
    if tool == "weather":
        return [], weather_reply(latitude, longitude)
    search, to_cards = _TOOL_RUNNERS[tool]
    title = TOOL_TITLES[tool]
    try:
        found = search(latitude=latitude, longitude=longitude, limit=20, **params)
    except Exception:  # noqa: BLE001 - công cụ hỏng không được làm hỏng cả khung chat
        logger.exception("Công cụ %s lỗi trong lượt chat", tool)
        return [], f"Xin lỗi, mình chưa tra được {title.lower()} lúc này. Bạn thử lại sau ít phút nhé."
    cards = to_cards(found)
    radius = format_distance(found.get("radius") or params.get("radius"))
    if not cards:
        where = f" trong bán kính {radius}" if radius else ""
        return [], f"Chưa thấy {title.lower()} nào phù hợp{where}. Bạn thử nói “xa hơn” để mở rộng nhé."
    reply = listing(cards, f"{title} gần bạn nhất:")
    if found.get("approximate"):
        reply += " Thời gian đi là ước tính."
    return cards, reply


_TOOL_FILTER_PARAMS = {
    "open_now": ("fuel", "charging", "convenience", "toilets"),
    "wheelchair": ("toilets",),
}


def refine_tool_params(tool: str, params: dict[str, Any], keys: tuple[str, ...]) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Gắn bộ lọc vào tham số công cụ. Trả kèm các bộ lọc công cụ KHÔNG hỗ
    trợ (vd "có wifi" cho cây xăng) để nói rõ là đã bỏ qua."""
    refined = dict(params)
    ignored = []
    for key in keys:
        if tool in _TOOL_FILTER_PARAMS.get(key, ()):
            refined[key] = True
        else:
            ignored.append(key)
    return refined, tuple(ignored)


def tool_radius(tool: str, params: dict[str, Any], factor: float) -> dict[str, Any]:
    low, high = _TOOL_LIMITS[tool]
    defaults = {
        "fuel": fuel.DEFAULT_RADIUS_METERS,
        "charging": charging.DEFAULT_RADIUS_METERS,
        "toilets": toilets.DEFAULT_RADIUS_METERS,
        "convenience": convenience.DEFAULT_RADIUS_METERS,
        "parking": 1000,
    }
    current = params.get("radius") or defaults[tool]
    return {**params, "radius": int(min(max(current * factor, low), high))}


def quick_replies(kind: str, count: int, filters: tuple[str, ...] = ()) -> list[str]:
    """Câu gợi ý bấm-là-gửi dưới câu trả lời — cũng là cách người dùng biết
    trợ lý hiểu được câu hỏi tiếp."""
    if count == 0:
        return ["Xa hơn"] if kind != "weather" else []
    replies = ["Chỉ đường tới số 1"]
    if count > 1:
        replies.append("Số 2 mấy giờ đóng cửa?")
    if count > PAGE_SIZE:
        replies.append("Còn chỗ khác không?")
    if "open_now" not in filters and kind in ("search", "fuel", "convenience", "toilets", "charging"):
        replies.append("Chỗ nào đang mở cửa?")
    return replies[:4]


# --- (4) Xe buýt -----------------------------------------------------------------
#
# Chạy TRƯỚC câu hỏi tiếp (xem `api._plan_chat_turn`): "xe buýt số 2" là tuyến
# 02, không phải thẻ thứ 2 của danh sách vừa xem. Không có vị trí xe theo thời
# gian thực — chỉ nói giãn cách giữa hai chuyến, không bịa "xe tới sau 3 phút".

# Số tuyến như ghi trên OSM: "14", "01", "60-1", "156D", "72-2B", "D2", "TGC01", "TIA".
_BUS_REF = r"(\d{1,3}(?:-\d{1,2}[bc]?)?[dv]?|d\d|tgc ?\d{1,2}|tia)"
_BUS_REF_RE = re.compile(rf"\b(?:buyt|bus|tuyen|xe|so|chuyen)\s+(?:(?:xe|buyt|bus|tuyen|so)\s+)*{_BUS_REF}\b")
# Không nói "xe buýt" vẫn chắc là hỏi tuyến: "tuyến 52", "xe số 14", "xe 1 chạy
# mấy giờ" — nhưng không phải "thuê xe 7 chỗ".
_BUS_CONTEXT_RE = re.compile(
    rf"\b(?:tuyen|xe so)\s+{_BUS_REF}\b|\bxe\s+{_BUS_REF}\s+(?:chay|di qua|dung|may gio|co chuyen)\b"
)
# "Bến xe buýt" là loại `bus_station` — vẫn là hỏi xe buýt.
_BUS_CATEGORIES = {"bus_station"}
_BUS_STOP_PHRASES = ("tram", "diem dung", "nha cho")
_BUS_ARRIVAL_PHRASES = (
    "bao lau nua", "may phut nua", "con bao lau", "khi nao toi", "khi nao den", "bao gio toi",
    "bao gio den", "may gio toi", "may gio den", "sap toi", "sap den", "toi chua", "den chua", "xe toi", "xe den",
)
_BUS_ROUTE_PHRASES = (
    "di qua", "chay qua", "qua nhung", "lo trinh", "nhung tram", "tram nao", "dung o", "duong nao",
    "nhung duong", "nhung dau", "di dau", "chay dau",
)
# Từ bỏ đi khi lấy tên bến/đường trong câu ("xe buýt nào đi Suối Tiên" → "Suối Tiên").
_BUS_NOISE_WORDS = frozenset(
    """xe buyt bus tuyen so nao di qua chay toi den tu co khong may gio o dau gan day nhat tram diem dung
    nha cho don len xuong cua minh la gi nhung ve va hay lo trinh bao lau nua tim can muon bat giup oi a
    nhe vay nay quanh khu vuc tren duoc the ra sao hien luc bay cac voi""".split()
)
_BUS_LISTED_REFS = 8


def _bus_fold(text: str) -> str:
    """Như `normalize_text` nhưng giữ gạch nối — tuyến "60-1" khác "60 1"."""
    text = (text or "").replace("Đ", "D").replace("đ", "d")
    plain = "".join(char for char in unicodedata.normalize("NFKD", text) if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-z0-9-]+", " ", plain.lower()).split())


def detect_bus(message: str) -> dict[str, Any] | None:
    """Câu hỏi về xe buýt thì trả tham số cho ``bus_answer``:

    - ``{"mode": "line", "ref", "ask"}`` — một tuyến; ``ask`` là ``info``
      (giờ chạy, giá vé…), ``route`` (đi qua đâu) hoặc ``arrival`` (bao lâu
      nữa xe tới — không có dữ liệu thời gian thực, chỉ nói giãn cách)
    - ``{"mode": "lines", "query"}`` — tuyến theo bến/đường ("xe buýt đi Suối Tiên")
    - ``{"mode": "stops", "query"}`` — trạm gần bạn, hoặc trạm theo tên
    """
    folded = _bus_fold(message)
    padded = f" {folded} "
    if not (" buyt " in padded or " bus " in padded or _BUS_CONTEXT_RE.search(folded)):
        return None
    words, plain = _words(message)
    kept = [word for word, key in zip(words, plain) if key not in _BUS_NOISE_WORDS]
    # "Quán cà phê gần trạm xe buýt" là tìm quán.
    if set(categories_for_query(" ".join(kept))) - _BUS_CATEGORIES:
        return None
    match = _BUS_REF_RE.search(folded)
    if match:
        if any(f" {phrase} " in padded for phrase in _BUS_ARRIVAL_PHRASES):
            ask = "arrival"
        elif any(f" {phrase} " in padded for phrase in _BUS_ROUTE_PHRASES):
            ask = "route"
        else:
            ask = "info"
        return {"mode": "line", "ref": match.group(1).replace(" ", "").upper(), "ask": ask}
    query = " ".join(kept)
    if any(f" {phrase} " in padded for phrase in _BUS_STOP_PHRASES) or not query:
        return {"mode": "stops", "query": query}
    return {"mode": "lines", "query": query}


def bus_answer(
    params: dict[str, Any], latitude: float, longitude: float, now: datetime | None = None
) -> tuple[str, dict[str, Any] | None, list[str]]:
    """``(câu trả lời, lớp vẽ bản đồ, câu gợi ý)``. Lớp vẽ cùng dạng
    ``AssistantOverlay`` của giao diện: lộ trình tuyến, hoặc các trạm gần."""
    now = now or datetime.now(ZoneInfo(TIMEZONE))
    try:
        if params["mode"] == "line":
            return _bus_line_answer(params["ref"], params.get("ask") or "info", now)
        if params["mode"] == "lines":
            return _bus_lines_answer(params["query"], now)
        return _bus_stops_answer(params.get("query") or "", latitude, longitude)
    except Exception:  # noqa: BLE001 - công cụ hỏng không được làm hỏng cả khung chat
        logger.exception("Tra xe buýt lỗi trong lượt chat")
        return "Xin lỗi, mình chưa tra được xe buýt lúc này. Bạn thử lại sau ít phút nhé.", None, []


def _ref_key(ref: str) -> str:
    """"1" khớp "01" — cùng cách so của `bus._matches`."""
    return normalize_text(ref).replace(" ", "").lstrip("0")


def _bus_line_answer(ref: str, ask: str, now: datetime) -> tuple[str, dict[str, Any] | None, list[str]]:
    found = bus.search_lines(ref, limit=10)
    wanted = _ref_key(ref)
    line = next((line for line in found["lines"] if _ref_key(line["ref"]) == wanted), None)
    if line is None:
        # Chỉ gợi ý tuyến cùng đầu số ("60" → 60-1, 60-2); `search_lines` còn
        # trả tuyến có tên đường chứa con số đó — không liên quan.
        similar = [line["ref"] for line in found["lines"] if _ref_key(line["ref"]).startswith(wanted)][:3]
        reply = f"Mình không thấy tuyến xe buýt số {ref} trong dữ liệu."
        if similar:
            reply += f" Bạn muốn hỏi tuyến {_join_vi(similar)}?"
        return reply, None, [f"Xe buýt {other} chạy mấy giờ?" for other in similar[:2]]
    return _bus_detail_answer(line, ask, now)


def _sentence(text: str) -> str:
    return text[:1].upper() + text[1:] + "."


def _bus_detail_answer(line: dict[str, Any], ask: str, now: datetime) -> tuple[str, dict[str, Any] | None, list[str]]:
    detail = bus.route_detail(int(line["directions"][0]["id"]), now)
    if detail is None:
        return f"Mình không thấy tuyến xe buýt số {line['ref']} trong dữ liệu.", None, []
    ref = detail["ref"]
    directions = _bus_directions(detail)
    sentences = [_bus_head(detail, now)]
    service = _bus_service(detail)
    if ask == "route":
        sentences += [_bus_streets(direction, label) for direction, label in directions]
    else:
        if service:
            sentences.append(_sentence(service))
        if directions:
            sentences.append(_sentence("; ".join(_bus_trip(direction, label) for direction, label in directions)))
    if ask == "arrival":
        interval = _bus_interval(detail)
        sentences.append(
            "Mình không có vị trí xe theo thời gian thực nên không biết chính xác khi nào xe tới trạm"
            + (f" — chỉ biết {interval}." if interval else ".")
        )
    replies = [
        f"Xe buýt {ref} chạy mấy giờ?" if ask == "route" else f"Tuyến {ref} đi qua những đâu?",
        "Trạm xe buýt gần tôi",
    ]
    return " ".join(sentences), _bus_overlay(detail), replies


def _bus_head(detail: dict[str, Any], now: datetime) -> str:
    head = f"Tuyến {detail['ref']} ({detail['name']})"
    # Dữ liệu có cả tuyến Bình Dương, Đồng Nai… — "xe buýt số 2" không có ở
    # TP.HCM thì ra tuyến 02 Bình Dương, phải nói rõ.
    if detail.get("network") and detail["network"] != bus.HCMC_NETWORK:
        head = f"Tuyến {detail['ref']} của {detail['network']} ({detail['name']})"
    hours = detail.get("hours") or {}
    first, last = hours.get("firstTrip"), hours.get("lastTrip")
    if first and last:
        head += f" chạy từ {first} đến {last}"
        state = _bus_state(hours, now)
        return head + (f", {state}." if state else ".")
    if hours.get("raw"):
        return f"{head}: giờ chạy ghi trên bản đồ là {hours['raw']}."
    return f"{head}: dữ liệu chưa ghi giờ chạy."


def _bus_state(hours: dict[str, Any], now: datetime) -> str | None:
    if hours.get("runningNow") is True:
        ends = hours.get("endsInMinutes")
        if ends is not None and ends <= 60:
            return f"giờ này đang chạy, còn khoảng {_say_duration(ends)} nữa là hết chuyến"
        return "giờ này đang chạy"
    if hours.get("runningNow") is False:
        starts = hours.get("startsInMinutes")
        if starts is None:
            return "giờ này không có chuyến"
        start_at = now + timedelta(minutes=starts)
        if start_at.date() == now.date():
            return f"giờ này chưa chạy, chuyến đầu lúc {start_at:%H:%M}"
        day = "sáng mai" if start_at.date() == (now + timedelta(days=1)).date() else f"ngày {start_at:%d/%m}"
        return f"hôm nay đã hết chuyến, chuyến đầu {day} lúc {start_at:%H:%M}"
    return None


def _bus_interval(detail: dict[str, Any]) -> str | None:
    interval = detail.get("interval")
    if not interval:
        return None
    low, high = interval["minMinutes"], interval["maxMinutes"]
    return f"cứ {low}–{high} phút có một chuyến" if low != high else f"khoảng {low} phút có một chuyến"


def _bus_service(detail: dict[str, Any]) -> str:
    """"cứ 6–12 phút có một chuyến, vé 6.000đ" — chưa viết hoa, chưa chấm câu."""
    parts = [_bus_interval(detail)]
    if detail.get("charge"):
        parts.append(f"vé {_vnd(int(detail['charge']))}")
    return ", ".join(part for part in parts if part)


def _bus_directions(detail: dict[str, Any]) -> list[tuple[dict[str, Any], str]]:
    directions = detail.get("directions") or []
    if len(directions) == 2:
        return list(zip(directions, ("lượt đi", "lượt về")))
    return [(direction, "lộ trình" if len(directions) == 1 else "lượt") for direction in directions]


def _bus_endpoints(direction: dict[str, Any]) -> str:
    if direction.get("origin") and direction.get("destination"):
        return f"{direction['origin']} → {direction['destination']}"
    return direction.get("name") or ""


def _bus_length(direction: dict[str, Any], nested: bool = False) -> list[str]:
    """``nested``: đã nằm trong ngoặc — viết "ước tính 56 phút" thay vì lồng ngoặc."""
    bits = []
    length = format_distance(direction.get("lengthMeters"))
    if length:
        bits.append(length)
    minutes = direction.get("tripMinutes")
    if minutes:
        # Phần lớn tuyến không ghi `duration`: số phút chia từ quãng đường với
        # vận tốc trung bình (`bus.trip_minutes`) — phải nói rõ là ước tính.
        if direction.get("tripMinutesSource") != "estimate":
            bits.append(f"khoảng {_say_duration(minutes)}")
        elif nested:
            bits.append(f"ước tính {_say_duration(minutes)}")
        else:
            bits.append(f"khoảng {_say_duration(minutes)} (ước tính)")
    return bits


def _bus_trip(direction: dict[str, Any], label: str) -> str:
    """"lượt đi Bến xe Miền Đông → Bến xe Miền Tây: 16,7 km, khoảng 56 phút (ước tính)"."""
    bits = _bus_length(direction)
    text = f"{label} {_bus_endpoints(direction)}".strip()
    return f"{text}: {', '.join(bits)}" if bits else text


def _bus_streets(direction: dict[str, Any], label: str) -> str:
    # Lộ trình rẽ ra rồi quay lại cùng một đường thì kể tên đường một lần.
    streets = list(dict.fromkeys(direction.get("streets") or []))
    stops = direction.get("stops") or []
    bits = [*_bus_length(direction, nested=True), *([f"{len(stops)} trạm"] if stops else [])]
    text = f"{label} {_bus_endpoints(direction)}".strip()
    if bits:
        text += f" ({', '.join(bits)})"
    if not streets:
        return _sentence(text + ": dữ liệu chưa ghi tên đường đi qua")
    shown = streets[:12]
    rest = len(streets) - len(shown)
    names = ", ".join(shown) + f" và {rest} đường khác" if rest else _join_vi(shown)
    return _sentence(f"{text} đi qua {names}")


def _bus_overlay(detail: dict[str, Any]) -> dict[str, Any] | None:
    """Lộ trình lượt đang chọn + bến đầu (A), bến cuối (B)."""
    directions = detail.get("directions") or []
    if not directions:
        return None
    direction = next((item for item in directions if item["id"] == detail.get("selectedId")), directions[0])
    path = direction.get("path")
    stops = direction.get("stops") or []
    points = []
    if len(stops) >= 2:
        for label, role, stop in (("A", "Bến đầu", stops[0]), ("B", "Bến cuối", stops[-1])):
            points.append(
                {
                    "id": f"bus-{direction['id']}-{label}",
                    "latitude": stop["latitude"],
                    "longitude": stop["longitude"],
                    "label": label,
                    "tone": "stop",
                    "title": f"{role}: {stop['name']}",
                }
            )
    line = path if isinstance(path, dict) and path.get("coordinates") else None
    if line is None and not points:
        return None
    return {"line": line, "points": points}


def _bus_lines_answer(query: str, now: datetime) -> tuple[str, dict[str, Any] | None, list[str]]:
    found = bus.search_lines(query, limit=5)
    lines = found["lines"]
    if not lines:
        reply = (
            f"Mình chưa thấy tuyến xe buýt nào đi qua “{query}”. Bạn thử nói số tuyến, "
            "ví dụ “xe buýt 14 chạy mấy giờ?”, hoặc hỏi “trạm xe buýt gần tôi”."
        )
        return reply, None, ["Trạm xe buýt gần tôi"]
    if found["total"] == 1:
        return _bus_detail_answer(lines[0], "info", now)
    items = [f"{line['ref']} ({line['name']})" for line in lines]
    more = found["total"] - len(items)
    listed = ", ".join(items) + f" và {more} tuyến khác" if more else _join_vi(items)
    reply = (
        f"Có {found['total']} tuyến xe buýt đi qua “{query}”: {listed}. "
        f"Bạn hỏi “xe buýt {lines[0]['ref']} chạy mấy giờ?” để xem giờ chạy, giá vé và lộ trình."
    )
    return reply, None, [f"Xe buýt {line['ref']} chạy mấy giờ?" for line in lines[:3]]


def _bus_refs(stop: dict[str, Any]) -> list[str]:
    # Một tuyến có hai lượt cùng dừng ở trạm thì chỉ kể một lần.
    return list(dict.fromkeys(route["ref"] for route in stop.get("routes") or []))


def _bus_refs_text(refs: list[str]) -> str:
    if not refs:
        return "chưa rõ tuyến nào dừng"
    shown = refs[:_BUS_LISTED_REFS]
    rest = len(refs) - len(shown)
    return "tuyến " + (", ".join(shown) + f" và {rest} tuyến khác" if rest else _join_vi(shown))


def _bus_stops_answer(query: str, latitude: float, longitude: float) -> tuple[str, dict[str, Any] | None, list[str]]:
    found = bus.search_stops(latitude=latitude, longitude=longitude, query=query, limit=5)
    stops = found["results"]
    if not stops:
        if query:
            return f"Mình không thấy trạm xe buýt nào tên “{query}”.", None, ["Trạm xe buýt gần tôi"]
        radius = format_distance(found.get("radius"))
        where = f" trong bán kính {radius}" if radius else ""
        return f"Không thấy trạm xe buýt nào{where} quanh bạn.", None, []
    items = []
    for stop in stops[:3]:
        minutes = stop.get("driveMinutes")
        where = f"{minutes} phút đi bộ" if minutes else format_distance(stop.get("distanceMeters"))
        name = f"{stop['name']} ({where})" if where else stop["name"]
        items.append(f"{name}: {_bus_refs_text(_bus_refs(stop))}")
    lead = f"Trạm xe buýt khớp “{query}”:" if query else "Trạm xe buýt gần bạn nhất:"
    reply = f"{lead} {'; '.join(items)}."
    if found.get("approximate"):
        reply += " Thời gian đi bộ là ước tính."
    overlay = {
        "line": None,
        "points": [
            {
                "id": f"bus-stop-{stop['id']}",
                "latitude": stop["latitude"],
                "longitude": stop["longitude"],
                "label": str(index),
                "tone": "stop",
                "title": f"{stop['name']} · {_bus_refs_text(_bus_refs(stop))}",
            }
            for index, stop in enumerate(stops, start=1)
        ],
    }
    return reply, overlay, [f"Xe buýt {ref} chạy mấy giờ?" for ref in _bus_refs(stops[0])[:2]]


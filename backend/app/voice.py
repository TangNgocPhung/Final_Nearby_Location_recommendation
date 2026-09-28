"""Chế độ giọng nói cho người khiếm thị — bộ quản lý hội thoại.

Mục tiêu: tìm, chọn và đi tới một địa điểm HOÀN TOÀN bằng lời nói. Trình duyệt
lo phần nghe (Web Speech API) và phần đọc (giọng đọc); module này lo phần hiểu
câu nói và soạn câu trả lời — để cả luồng hội thoại kiểm được bằng unit test
thay vì nằm rải trong code giao diện.

Vì sao LUẬT thay vì LLM: mỗi lượt nói phải có phản hồi trong một hai giây. Chat
LLM trên CPU máy dev có lúc mất cả phút (đo thật, xem `app/chat.py`) — với người
không nhìn thấy màn hình, im lặng một phút nghĩa là "ứng dụng đã chết". Tập lệnh
cần hiểu nhỏ và cố định (chọn số mấy, dẫn đường, nhắc lại…); phần tự do duy
nhất là câu tìm kiếm, và phần đó đi thẳng vào pipeline xếp hạng thật (BM25 +
vector + geo-parser hiểu "gần Bến Thành").

Trạng thái hội thoại do CLIENT giữ và gửi lại mỗi lượt (``state``) — server
không lưu gì, mất kết nối giữa chừng cũng không để lại phiên mồ côi.

Nguyên tắc nói: không khẳng định điều không biết. POI không có giờ mở cửa thì
KHÔNG nói "đang mở cửa"; khoảng cách lúc chưa có tuyến đường là đường chim bay
và phải nói rõ như vậy.
"""

from __future__ import annotations

import math
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Callable

from .poi_features import normalize_text

MAX_RESULTS = 12
PAGE_SIZE = 3
SEARCH_RADIUS_METERS = 2_000
# Người đi bộ ~ 75 m/phút (cùng hằng số tour thuyết minh), đường thật dài hơn
# đường chim bay ~ 1,3 lần.
WALK_METERS_PER_MINUTE = 75.0
DETOUR_FACTOR = 1.3

STAGES = ("idle", "results", "selected", "navigating")

# --- Hiểu câu nói -------------------------------------------------------------

# Số thứ tự so khớp trên chữ CÓ DẤU: bỏ dấu thì "ba" (3) trùng "bà", "sau" (6)
# trùng "sau", "bay" (7) trùng "bay", "tam" (8) trùng "tắm", "nam" (5) trùng
# "nam" — và "chùa bà" sẽ thành "chọn số 3". Nhận dạng giọng nói luôn trả chữ
# có dấu nên đây không phải một giới hạn thực tế. "nhất" đứng một mình KHÔNG
# phải số thứ tự: "quán gần nhất" là một câu tìm kiếm.
_ORDINAL_WORDS = {
    "một": 1, "thứ nhất": 1, "đầu tiên": 1,
    "hai": 2, "thứ nhì": 2,
    "ba": 3,
    "bốn": 4, "tư": 4,
    "năm": 5, "lăm": 5,
    "sáu": 6,
    "bảy": 7,
    "tám": 8,
    "chín": 9,
    "mười": 10,
    "mười một": 11,
    "mười hai": 12,
}

# Lệnh dừng cũng so trên chữ có dấu: bỏ dấu thì "dừng" và "đúng" cùng thành
# "dung" — nói "đúng rồi" không được làm dừng dẫn đường.
_STOP_WORDS = ("dừng lại", "dừng", "hủy", "huỷ", "thôi", "ngừng")

# Cụm từ (đã bỏ dấu) cho từng ý định. So khớp theo RANH GIỚI TỪ — "tiep" không
# được khớp vào giữa "tiep tan".
_PHRASES: dict[str, tuple[str, ...]] = {
    "exit": ("thoat", "tat che do", "ket thuc", "tam biet", "tat giong noi"),
    "help": ("tro giup", "huong dan", "giup toi voi", "noi gi", "lam sao", "cach dung"),
    "repeat": ("nhac lai", "lap lai", "noi lai", "doc lai", "gi co"),
    "where": ("toi dang o dau", "dang o dau", "o dau day", "day la dau", "vi tri cua toi", "toi o dau"),
    # KHÔNG có "toi chua": "tôi chưa ăn" bỏ dấu cũng ra "toi chua".
    "howfar": ("con bao xa", "bao xa", "con bao lau", "bao lau nua", "den noi chua", "toi noi chua"),
    "navigate": (
        "dan duong", "chi duong", "di thoi", "bat dau di", "dua toi di", "dan toi di",
        "di den do", "di toi do", "di nao",
    ),
    "narrate": ("thuyet minh", "ke ve", "gioi thieu", "cau chuyen"),
    "details": ("chi tiet", "thong tin", "dia chi", "gio mo cua", "mo cua khong", "may gio"),
    "more": ("them", "tiep theo", "tiep", "nua", "xem them", "nghe tiep"),
    "back": ("quay lai", "tro lai", "danh sach"),
}

# Từ đệm bỏ khỏi câu tìm kiếm (so trên chữ bỏ dấu). KHÔNG bỏ "gần" đứng một
# mình: "gần Bến Thành" là thông tin vị trí mà geo-parser cần. Cũng không bỏ
# từ một âm tiết như "đi"/"một": bỏ dấu thì "đi" trùng "dì" ("quán dì Ba").
_FILLERS = (
    "tim kiem", "tim giup toi", "tim cho toi", "tim", "cho toi", "giup toi", "toi muon",
    "toi can", "o gan day", "gan day", "quanh day", "gan nhat", "o dau",
)


def fold(text: str | None) -> str:
    """Chữ thường, bỏ dấu, chỉ chữ-số — so khớp lệnh không phụ thuộc cách gõ dấu."""
    return normalize_text(text)


def _has_phrase(folded: str, phrases: tuple[str, ...]) -> bool:
    padded = f" {folded} "
    return any(f" {phrase} " in padded for phrase in phrases)


def _lower_words(text: str) -> str:
    """Chữ thường CÓ DẤU (chuẩn NFC), bỏ dấu câu — dùng cho so khớp cần dấu."""
    lowered = unicodedata.normalize("NFC", text.lower())
    return " ".join(re.findall(r"\w+", lowered))


def ordinal(text: str) -> int | None:
    """Số thứ tự trong câu: "số hai", "cái thứ ba", "2", "chọn số mười một"."""
    words = _lower_words(text)
    digits = re.search(r"\b(\d{1,2})\b", words)
    if digits:
        return int(digits.group(1))
    # Cụm dài trước ("mười một" trước "một").
    for phrase in sorted(_ORDINAL_WORDS, key=len, reverse=True):
        if f" {phrase} " in f" {words} ":
            return _ORDINAL_WORDS[phrase]
    return None


def _is_stop(text: str) -> bool:
    words = f" {_lower_words(text)} "
    return any(f" {word} " in words for word in _STOP_WORDS)


def _is_go(folded: str, has_index: bool) -> bool:
    """"Đi" đứng một mình (hoặc "số hai, đi") là lệnh đi; "tìm quán phở đi" thì không."""
    if _has_phrase(folded, _PHRASES["navigate"]):
        return True
    words = folded.split()
    return folded == "di" or (has_index and "di" in words and len(words) <= 4)


def clean_query(text: str) -> str:
    """Bỏ từ đệm khỏi câu tìm kiếm, GIỮ NGUYÊN dấu của phần còn lại."""
    words = text.strip().split()
    folded = [fold(word) for word in words]
    keep = [True] * len(words)
    for filler in sorted(_FILLERS, key=len, reverse=True):
        parts = filler.split()
        size = len(parts)
        for start in range(0, len(words) - size + 1):
            if all(keep[start + i] and folded[start + i] == parts[i] for i in range(size)):
                for i in range(size):
                    keep[start + i] = False
    cleaned = " ".join(word for word, flag in zip(words, keep) if flag).strip(" ,.?!")
    return cleaned or text.strip()


def parse(text: str, stage: str, result_names: list[str] | None = None) -> dict[str, Any]:
    """Câu nói → ý định. Trả ``{"intent": ..., "index"?: int, "query"?: str}``.

    Ý định phụ thuộc NGỮ CẢNH (``stage``): "hai" là "chọn số hai" khi đang nghe
    danh sách, nhưng là một phần câu tìm kiếm khi chưa có danh sách nào.
    """
    folded = fold(text)
    if not folded:
        return {"intent": "empty"}
    words = folded.split()
    short = len(words) <= 5

    for intent in ("exit", "help", "repeat", "where", "howfar"):
        if _has_phrase(folded, _PHRASES[intent]):
            return {"intent": intent}
    # "Dừng" chỉ là lệnh khi câu ngắn — "quán ăn trên đường dừng xe" là tìm kiếm.
    if short and _is_stop(text):
        return {"intent": "stop"}

    index = ordinal(text) if stage in ("results", "selected") else None
    if stage in ("results", "selected") and short and _is_go(folded, index is not None):
        return {"intent": "navigate", **({"index": index} if index else {})}
    if stage in ("selected", "navigating") and _has_phrase(folded, _PHRASES["narrate"]):
        return {"intent": "narrate"}
    if stage in ("results", "selected") and short and _has_phrase(folded, _PHRASES["details"]):
        return {"intent": "details", **({"index": index} if index else {})}
    if stage == "results" and short and _has_phrase(folded, _PHRASES["more"]):
        return {"intent": "more"}
    if stage in ("selected", "navigating") and short and _has_phrase(folded, _PHRASES["back"]):
        return {"intent": "back"}
    if stage in ("results", "selected") and index is not None and short:
        return {"intent": "select", "index": index}
    if stage in ("results", "selected") and result_names:
        best, best_index = 0.0, None
        for position, name in enumerate(result_names, start=1):
            score = SequenceMatcher(None, folded, fold(name)).ratio()
            if score > best:
                best, best_index = score, position
        if best >= 0.8 and best_index is not None:
            return {"intent": "select", "index": best_index}
    return {"intent": "search", "query": clean_query(text)}


# --- Soạn câu nói --------------------------------------------------------------


def say_number(value: float, decimals: int = 1) -> str:
    """Số thập phân kiểu Việt: 1.5 → "1,5"; số nguyên thì bỏ phần thập phân."""
    if abs(value - round(value)) < 10 ** -decimals / 2:
        return str(int(round(value)))
    return f"{value:.{decimals}f}".replace(".", ",")


def say_distance(meters: float | None) -> str:
    if meters is None:
        return "chưa rõ khoảng cách"
    if meters < 1_000:
        # Làm tròn 10 m: đọc "một trăm bốn mươi ba mét" vừa dài vừa giả chính xác
        # (GPS điện thoại sai vài chục mét).
        return f"{max(10, int(round(meters / 10.0)) * 10)} mét"
    return f"{say_number(meters / 1000)} ki lô mét"


def walk_minutes(meters: float) -> int:
    return max(1, round(meters * DETOUR_FACTOR / WALK_METERS_PER_MINUTE))


def say_open(poi: dict[str, Any]) -> str:
    open_now = poi.get("openNow")
    if open_now is True:
        closes = poi.get("closesInMinutes")
        if closes is not None and closes <= 60:
            return f"đang mở cửa, sắp đóng sau {closes} phút"
        return "đang mở cửa"
    if open_now is False:
        opens = poi.get("opensInMinutes")
        if opens is not None and opens <= 120:
            return f"đang đóng cửa, mở lại sau {opens} phút"
        return "đang đóng cửa"
    return ""


def say_result(position: int, poi: dict[str, Any]) -> str:
    parts = [f"Số {position}: {poi['name']}", f"cách {say_distance(poi.get('distanceMeters'))}"]
    status = say_open(poi)
    if status:
        parts.append(status)
    rating = poi.get("rating")
    if isinstance(rating, (int, float)):
        parts.append(f"{say_number(float(rating))} sao")
    return ", ".join(parts) + "."


def say_page(results: list[dict[str, Any]], start: int) -> str:
    page = results[start : start + PAGE_SIZE]
    lines = [say_result(start + offset + 1, poi) for offset, poi in enumerate(page)]
    remaining = len(results) - (start + len(page))
    tail = "Hãy nói số để chọn"
    tail += ", nói “thêm” để nghe tiếp" if remaining > 0 else ""
    tail += ", hoặc nói điều khác để tìm lại."
    return " ".join(lines) + " " + tail


def say_details(poi: dict[str, Any], has_story: bool) -> str:
    parts = [f"Bạn chọn {poi['name']}."]
    if poi.get("address"):
        parts.append(f"Địa chỉ: {poi['address']}.")
    distance = poi.get("distanceMeters")
    if distance is not None:
        parts.append(
            f"Cách {say_distance(distance)} đường chim bay, "
            f"khoảng {walk_minutes(distance)} phút đi bộ."
        )
    status = say_open(poi)
    if status:
        parts.append(status[0].upper() + status[1:] + ".")
    options = "Nói “dẫn đường” để bắt đầu đi"
    if has_story:
        options += ", “thuyết minh” để nghe giới thiệu"
    options += ", hoặc “quay lại” để về danh sách."
    parts.append(options)
    return " ".join(parts)


_COMPASS = ("bắc", "đông bắc", "đông", "đông nam", "nam", "tây nam", "tây", "tây bắc")


def bearing_degrees(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lng2 - lng1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def compass_word(degrees: float) -> str:
    return _COMPASS[int(((degrees % 360) + 22.5) // 45) % 8]


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


HELP_TEXT = (
    "Bạn có thể nói tên loại địa điểm cần tìm, ví dụ: “quán phở”, “nhà thuốc”, "
    "hay “cà phê gần Bến Thành”. Khi nghe danh sách, nói số để chọn, “thêm” để nghe tiếp. "
    "Sau khi chọn, nói “dẫn đường” để đi. Lúc nào cũng có thể nói “nhắc lại”, "
    "“tôi đang ở đâu”, “dừng”, hoặc “thoát” để tắt chế độ giọng nói."
)
GREETING = "Chế độ giọng nói đã bật. Bạn muốn tìm gì? " + (
    "Ví dụ: “quán phở gần đây”. Nói “trợ giúp” để nghe hướng dẫn."
)


# --- Một lượt hội thoại ----------------------------------------------------------

SearchFn = Callable[[str, float, float], list[dict[str, Any]]]
StoryFn = Callable[[str], bool]
WhereFn = Callable[[float, float], dict[str, Any] | None]


def _compact(poi: dict[str, Any], latitude: float, longitude: float) -> dict[str, Any]:
    """Giữ đúng các trường cần để nói và để dẫn đường — state gửi đi gửi lại
    mỗi lượt, không mang theo cả trăm trường của kết quả xếp hạng."""
    lat, lng = float(poi["latitude"]), float(poi["longitude"])
    return {
        "id": poi["id"],
        "name": poi["name"],
        "address": poi.get("address"),
        "latitude": lat,
        "longitude": lng,
        # Khoảng cách từ NGƯỜI DÙNG — câu "cà phê gần Bến Thành" xếp hạng quanh
        # Bến Thành, nhưng người nghe cần biết mình còn cách bao xa.
        "distanceMeters": round(haversine_m(latitude, longitude, lat, lng)),
        "openNow": poi.get("openNow"),
        "closesInMinutes": poi.get("closesInMinutes"),
        "opensInMinutes": poi.get("opensInMinutes"),
        "rating": poi.get("rating"),
        "categoryLabel": poi.get("categoryLabel"),
    }


def _state(**values: Any) -> dict[str, Any]:
    base = {"stage": "idle", "query": None, "results": [], "page": 0, "selected": None, "lastSpeech": ""}
    base.update(values)
    return base


def respond(
    text: str,
    latitude: float,
    longitude: float,
    state: dict[str, Any] | None,
    *,
    search: SearchFn,
    has_story: StoryFn,
    where: WhereFn,
) -> dict[str, Any]:
    """Một lượt: câu người dùng vừa nói → ``{speech, state, action}``.

    ``action`` (có thể None) là việc client phải làm ngoài việc đọc câu trả
    lời: ``navigate`` (bắt đầu dẫn đường), ``stop_navigation``, ``narrate``,
    ``exit``. Các hàm truy cập dữ liệu được TIÊM vào để test không cần database.
    """
    current = _state(**(state or {}))
    stage = current["stage"] if current["stage"] in STAGES else "idle"
    results: list[dict[str, Any]] = current["results"] or []
    selected: dict[str, Any] | None = current["selected"]
    parsed = parse(text, stage, [poi["name"] for poi in results])
    intent = parsed["intent"]

    def reply(speech: str, action: dict[str, Any] | None = None, **changes: Any) -> dict[str, Any]:
        new_state = {**current, **changes, "lastSpeech": speech}
        return {"speech": speech, "state": new_state, "action": action, "intent": intent}

    if intent == "empty":
        return reply("Tôi chưa nghe rõ. Bạn nói lại nhé.")
    if intent == "exit":
        return reply("Đã tắt chế độ giọng nói. Tạm biệt.", {"type": "exit"})
    if intent == "help":
        return reply(HELP_TEXT)
    if intent == "repeat":
        return reply(current["lastSpeech"] or GREETING)
    if intent == "where":
        place = where(latitude, longitude)
        match = (place or {}).get("match") if place else None
        if not match:
            return reply("Tôi chưa xác định được bạn đang ở gần đâu.")
        distance = float(match.get("distanceMeters") or 0)
        near = "ngay tại" if distance < 30 else f"cách khoảng {say_distance(distance)} từ"
        address = f", {match['address']}" if match.get("address") else ""
        return reply(f"Bạn đang {near} {match['name']}{address}.")
    if intent == "howfar":
        target = selected
        if not target:
            return reply("Bạn chưa chọn điểm đến nào.")
        distance = haversine_m(latitude, longitude, target["latitude"], target["longitude"])
        if distance < 25:
            return reply(f"Bạn đã tới {target['name']}.")
        direction = compass_word(bearing_degrees(latitude, longitude, target["latitude"], target["longitude"]))
        return reply(
            f"Còn khoảng {say_distance(distance)} đường chim bay tới {target['name']}, "
            f"về hướng {direction}, chừng {walk_minutes(distance)} phút đi bộ."
        )
    if intent == "stop":
        if stage == "navigating":
            return reply(
                "Đã dừng dẫn đường. Nói “dẫn đường” để đi tiếp, hoặc nói điều khác để tìm lại.",
                {"type": "stop_navigation"},
                stage="selected",
            )
        return reply("Đã dừng. Bạn muốn tìm gì?", {"type": "stop_navigation"}, stage="idle")
    if intent == "more":
        start = current["page"] + PAGE_SIZE
        if start >= len(results):
            return reply("Đã hết danh sách. Nói số để chọn, hoặc nói điều khác để tìm lại.")
        return reply(say_page(results, start), page=start)
    if intent == "back":
        if not results:
            return reply("Chưa có danh sách nào. Bạn muốn tìm gì?", stage="idle")
        return reply(
            say_page(results, current["page"]),
            {"type": "stop_navigation"} if stage == "navigating" else None,
            stage="results",
        )
    if intent in ("select", "details", "navigate"):
        index = parsed.get("index")
        if index is not None:
            if not 1 <= index <= len(results):
                return reply(f"Danh sách chỉ có {len(results)} địa điểm. Bạn chọn số từ 1 đến {len(results)} nhé.")
            selected = results[index - 1]
        if selected is None:
            return reply("Bạn hãy nói số của địa điểm muốn chọn trước, ví dụ “số một”.")
        if intent == "navigate":
            return reply(
                f"Bắt đầu dẫn đường tới {selected['name']}, cách {say_distance(selected.get('distanceMeters'))}. "
                "Tôi sẽ nhắc khi tới chỗ rẽ. Nói “còn bao xa” để hỏi, “dừng” để kết thúc.",
                {
                    "type": "navigate",
                    "poiId": selected["id"],
                    "name": selected["name"],
                    "latitude": selected["latitude"],
                    "longitude": selected["longitude"],
                },
                stage="navigating",
                selected=selected,
            )
        return reply(say_details(selected, has_story(selected["id"])), stage="selected", selected=selected)
    if intent == "narrate":
        if not selected:
            return reply("Bạn chưa chọn địa điểm nào.")
        if not has_story(selected["id"]):
            return reply(f"{selected['name']} chưa có bài thuyết minh.")
        return reply(
            f"Thuyết minh về {selected['name']}.",
            {"type": "narrate", "poiId": selected["id"], "name": selected["name"]},
        )

    # Còn lại: tìm kiếm mới.
    query = parsed.get("query") or text.strip()
    found = [_compact(poi, latitude, longitude) for poi in search(query, latitude, longitude)[:MAX_RESULTS]]
    if not found:
        return reply(
            f"Không tìm thấy địa điểm nào cho “{query}” trong khoảng {say_distance(SEARCH_RADIUS_METERS)}. "
            "Bạn thử nói cách khác nhé.",
            stage="idle",
            query=query,
            results=[],
            page=0,
            selected=None,
        )
    intro = f"Tìm thấy {len(found)} địa điểm cho “{query}”. "
    return reply(
        intro + say_page(found, 0),
        {"type": "stop_navigation"} if stage == "navigating" else None,
        stage="results",
        query=query,
        results=found,
        page=0,
        selected=None,
    )

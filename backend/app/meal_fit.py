"""Lọc/xếp lại kết quả "quán ăn" theo BỮA đang hỏi (sáng, trưa, tối, khuya).

Category ``restaurant`` gộp cả quán kem, chè, food court, quán nướng (xem
``poi_features.CATEGORY_MAP``), nên chip "Gợi ý cho bữa sáng" chỉ lọc theo
category từng trả về "Chè 259" và "Kem Vĩnh Sanh" đứng đầu — đúng loại, sai bữa.

Dữ liệu có hai nguồn tín hiệu, cả hai đều thưa:

- ``tags``: giá trị ``cuisine``/``amenity`` của OSM (``ice_cream``, ``noodle``,
  ``breakfast``…) — chỉ khoảng một nửa quán có thêm tag ngoài ``restaurant``.
- Tên quán: ở Việt Nam tên thường chính là món ("Phở …", "Xôi …", "Chè …").

Quy tắc: quán bị LOẠI khi tag hoặc tên chỉ ra món không hợp bữa; quán HỢP
bữa được đưa lên trước; phần còn lại (không rõ món) giữ nguyên thứ tự xếp
hạng ở phía sau. Không quán nào bị loại chỉ vì thiếu dữ liệu.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

MEALS = ("breakfast", "lunch", "dinner", "late_night")

# Món tráng miệng/đồ uống — không phải một bữa chính ở bất kỳ giờ nào trừ khuya.
_DESSERT_TAGS = frozenset({"ice_cream", "dessert", "bubble_tea", "juice", "trà_sữa", "hồng_trà", "tea"})
_DESSERT_WORDS = ("chè", "kem", "trà sữa", "sinh tố", "tàu hũ", "bingsu", "milk tea", "ice cream", "gelato")

# Món nhậu/nặng — hợp tối và khuya, không hợp buổi sáng.
_HEAVY_TAGS = frozenset({
    "beer", "hotpot", "lẩu", "barbecue", "grill", "nướng", "steak_house", "wings", "fine_dining",
})
_HEAVY_WORDS = ("lẩu", "nướng", "bbq", "bia", "beer", "nhậu", "ốc", "pub", "steak", "buffet")

_PROFILES: dict[str, dict[str, Any]] = {
    "breakfast": {
        "exclude_tags": _DESSERT_TAGS | _HEAVY_TAGS,
        "exclude_words": _DESSERT_WORDS + _HEAVY_WORDS,
        "prefer_tags": frozenset({
            "breakfast", "brunch", "noodle", "noodles", "pho", "phở", "sticky_rice", "sandwich",
            "bakery", "pancake", "coffee_shop", "deli", "rice",
        }),
        "prefer_words": (
            "phở", "bún", "hủ tiếu", "hủ tíu", "bánh mì", "xôi", "cháo", "bánh cuốn", "cơm tấm",
            "bò kho", "mì", "bánh canh", "bột chiên", "bánh bao", "súp cua", "điểm tâm",
            "dimsum", "dim sum", "ăn sáng", "breakfast",
        ),
    },
    "lunch": {
        "exclude_tags": _DESSERT_TAGS,
        "exclude_words": _DESSERT_WORDS,
        "prefer_tags": frozenset({"vietnamese", "rice", "noodle", "noodles", "pho", "phở", "regional"}),
        "prefer_words": ("cơm", "bún", "phở", "mì", "hủ tiếu", "hủ tíu", "bánh canh", "quán ăn"),
    },
    "dinner": {
        "exclude_tags": _DESSERT_TAGS,
        "exclude_words": _DESSERT_WORDS,
        "prefer_tags": frozenset(),
        "prefer_words": (),
    },
    # Ăn khuya: chè, ốc, lẩu đều hợp — không loại gì.
    "late_night": {
        "exclude_tags": frozenset(),
        "exclude_words": (),
        "prefer_tags": frozenset(),
        "prefer_words": (),
    },
}


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFC", text).lower()


def _has_word(name: str, words: tuple[str, ...]) -> bool:
    # So khớp nguyên từ: "kem" không được khớp "Kemmy", "mì" không khớp "mìn".
    return any(re.search(rf"(?<!\w){re.escape(word)}(?!\w)", name) for word in words)


def meal_fit(candidate: dict[str, Any], meal: str) -> int:
    """-1 = không hợp bữa (loại), 1 = hợp rõ ràng, 0 = không rõ."""
    profile = _PROFILES[meal]
    tags = {_normalize(str(tag)) for tag in candidate.get("tags") or ()}
    name = _normalize(candidate.get("name") or "")
    if tags & profile["exclude_tags"] or _has_word(name, profile["exclude_words"]):
        return -1
    if tags & profile["prefer_tags"] or _has_word(name, profile["prefer_words"]):
        return 1
    return 0


def filter_for_meal(candidates: list[dict[str, Any]], meal: str, limit: int) -> list[dict[str, Any]]:
    """Bỏ quán sai bữa, đưa quán hợp bữa lên trước; giữ thứ tự xếp hạng trong
    từng nhóm (sort ổn định)."""
    scored = [(meal_fit(candidate, meal), candidate) for candidate in candidates]
    kept = [pair for pair in scored if pair[0] >= 0]
    kept.sort(key=lambda pair: -pair[0])
    return [candidate for _fit, candidate in kept[:limit]]

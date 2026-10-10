"""Loại ứng viên chỉ khớp chữ nhờ BỎ DẤU, khi người dùng đã gõ có dấu.

Analyzer ``vi_folded`` gộp "chay" (ăn chay) với "cháy" (phòng cháy), "quán"
với "quận". Đo 2026-10-10: "Quán chay gần tôi" trả "Phòng Cảnh sát Phòng cháy
và Chữa cháy Công an Quận 6" — tên có HAI chữ "cháy" nên BM25 chấm cao hơn cả
quán chay thật. Field ``.strict`` chỉ CỘNG điểm khi khớp đúng dấu, không trừ
điểm khi lệch dấu, nên không cứu được.

Câu gõ có dấu thì dấu là thông tin thật (cùng giả định với
``poi_features.categories_for_query``): "chay" không dấu trong câu có dấu nghĩa
là đúng chữ "chay". Tên POI cũng phải có dấu mới phán được — "Quan Com Chay
Dieu Hue" gõ không dấu thì không biết "Chay" là chữ gì, giữ nguyên.

So theo chữ cái + dấu mũ/râu từng vị trí + LOẠI dấu thanh, không so chuỗi:
"Hoà" và "Hòa" (bỏ dấu kiểu cũ/mới) là một chữ, chỉ đặt dấu thanh khác chỗ.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from typing import Any

from ..poi_features import category_keywords

# Dấu mũ (â ê ô), trăng (ă), râu (ơ ư) gắn với chữ cái đứng trước nó.
_SHAPE_MARKS = frozenset({"̂", "̆", "̛"})
# Dấu thanh: huyền, sắc, hỏi, ngã, nặng — vị trí đặt tuỳ kiểu gõ.
_TONE_MARKS = frozenset({"̀", "́", "̉", "̃", "̣"})
_WORD_RE = re.compile(r"\w+")

Signature = tuple[str, str, str]  # (bỏ dấu, chữ cái + mũ/râu, dấu thanh)


def signature(word: str) -> Signature:
    letters: list[str] = []
    tone = ""
    for char in unicodedata.normalize("NFD", word.lower()):
        if char in _SHAPE_MARKS:
            letters.append(char)
        elif char in _TONE_MARKS:
            tone = char
        elif char == "đ":
            letters.append("d̵")
        elif not unicodedata.combining(char):
            letters.append(char)
    shaped = "".join(letters)
    folded = "".join(char for char in shaped if not unicodedata.combining(char))
    return folded, shaped, tone


def _signatures(text: str | None) -> list[Signature]:
    return [signature(word) for word in _WORD_RE.findall(text or "")]


def _is_marked(sig: Signature) -> bool:
    return sig[0] != sig[1] or bool(sig[2])


def has_marks(text: str | None) -> bool:
    return any(_is_marked(sig) for sig in _signatures(text))


def accent_mismatch(query: str, name: str | None, extra_texts: Iterable[str | None] = ()) -> bool:
    """True khi tên chỉ "khớp" truy vấn nhờ bỏ dấu.

    Nghĩa là: có chữ trong truy vấn trùng khi bỏ dấu với chữ trong tên nhưng
    KHÁC dấu, và không chữ nào của truy vấn khớp đúng dấu với tên hay với
    ``extra_texts`` (nhãn loại, từ khoá loại — POI vẫn đúng loại người dùng
    hỏi dù tên tình cờ có chữ lệch dấu). Bên gọi chỉ hỏi khi câu gốc có dấu.
    """
    names = _signatures(name)
    if not any(_is_marked(sig) for sig in names):
        return False
    extras = {sig for text in extra_texts for sig in _signatures(text)}
    conflict = False
    for word in _signatures(query):
        same_fold = [sig for sig in names if sig[0] == word[0]]
        if word in extras or word in same_fold:
            return False
        if same_fold:
            conflict = True
    return conflict


def drop_accent_mismatches(
    candidates: list[dict[str, Any]], query: str, original: str | None = None
) -> list[dict[str, Any]]:
    """Bỏ ứng viên ``accent_mismatch``. ``original``: câu người dùng gõ (chat
    đưa BM25 câu đã bỏ từ đệm — "chay" trơ trọi không còn dấu nào để biết
    người dùng gõ có dấu)."""
    if not query.strip() or not has_marks(original or query):
        return candidates
    return [
        candidate
        for candidate in candidates
        if not accent_mismatch(
            query,
            candidate.get("name"),
            (candidate.get("categoryLabel"), *category_keywords(candidate.get("category"))),
        )
    ]

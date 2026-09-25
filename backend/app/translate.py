"""Dịch giao diện sang 134 ngôn ngữ (xem `app/languages.py`) bằng Qwen chạy
local qua Ollama — không cần API key, không cần Internet lúc demo.

Frontend KHÔNG giữ file dịch cho từng ngôn ngữ: nó gom các chuỗi tiếng Việt
đang hiện trên trang, gửi lên đây, nhận bản dịch về rồi thay tại chỗ (xem
`frontend/hooks/use-auto-translate.ts`). Bản dịch cache theo từng ngôn ngữ
trên volume riêng (`nearby-i18n-cache`), nên mỗi chuỗi chỉ phải dịch MỘT lần
cho mỗi ngôn ngữ — lần đầu chọn một ngôn ngữ mất vài phút trên CPU (~2 giây
mỗi chuỗi, đo được thật 2026-09-25), từ lần thứ hai hiện ngay.

Bản dịch hỏng (model trả thiếu khoá, trả rỗng, dài bất thường) KHÔNG được
cache — chuỗi đó giữ nguyên tiếng Việt và được thử dịch lại ở lượt sau.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

from . import chat
from .config import settings
from .languages import ENGLISH_NAMES, SOURCE_LANGUAGE

logger = logging.getLogger("nearby-translate")

CACHE_DIR = Path(os.environ.get("I18N_CACHE_DIR", "/app/i18n_cache"))

MAX_TEXT_LENGTH = 2000
MAX_TEXTS_PER_REQUEST = 40
# Mỗi lượt gọi Ollama phải xong trong `ollama_narration_timeout_seconds`
# (140s) — đo thật: 7 nhãn ngắn sang tiếng Khmer mất 31s, nên giữ lô nhỏ.
_CHUNK_ITEMS = 12
_CHUNK_CHARS = 700

_SYSTEM_PROMPT = """You translate user-interface text of "Nearby", a Vietnamese app for finding places nearby on a map, from Vietnamese into {language}.
Input: a JSON object mapping ids to Vietnamese texts.
Output: ONLY a JSON object with exactly the same ids, each value being the {language} translation of that text.
Rules:
- Translate the meaning naturally, as a native {language} app would say it. Keep it about as short as the original.
- Keep numbers, units, emoji, symbols, URLs and punctuation as they are.
- Keep proper names (places, streets, brands) recognizable; transliterate them only if {language} does not use the Latin alphabet.
- If a text is not Vietnamese (a brand, a code, English), return it unchanged.
- Output nothing except the JSON object."""

_memory: dict[str, dict[str, str]] = {}
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def is_supported(language: str) -> bool:
    return language in ENGLISH_NAMES and language != SOURCE_LANGUAGE


def _lock_for(language: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(language, threading.Lock())


def _cache_path(language: str) -> Path:
    return CACHE_DIR / f"{language}.json"


def _load(language: str) -> dict[str, str]:
    if language in _memory:
        return _memory[language]
    mapping: dict[str, str] = {}
    path = _cache_path(language)
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                mapping = {k: v for k, v in loaded.items() if isinstance(k, str) and isinstance(v, str)}
        except (OSError, json.JSONDecodeError) as error:
            logger.warning("Đọc cache bản dịch hỏng (%s): %s", language, error)
    _memory[language] = mapping
    return mapping


def _save(language: str, mapping: dict[str, str]) -> None:
    path = _cache_path(language)
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as error:
        logger.warning("Ghi cache bản dịch thất bại (%s): %s", language, error)


def cached_translations(language: str) -> dict[str, str]:
    """Toàn bộ bản dịch đã có của một ngôn ngữ — frontend áp ngay lúc đổi
    ngôn ngữ, chỉ gửi lên dịch những chuỗi còn thiếu."""
    if not is_supported(language):
        return {}
    with _lock_for(language):
        return dict(_load(language))


def _chunks(texts: list[str]) -> list[list[str]]:
    chunks: list[list[str]] = []
    current: list[str] = []
    size = 0
    for text in texts:
        if current and (len(current) >= _CHUNK_ITEMS or size + len(text) > _CHUNK_CHARS):
            chunks.append(current)
            current, size = [], 0
        current.append(text)
        size += len(text)
    if current:
        chunks.append(current)
    return chunks


def _plausible(source: str, translated: str) -> bool:
    # Model nhỏ đôi khi "giải thích" thay vì dịch, hoặc lặp vô tận — bản dịch
    # dài gấp nhiều lần bản gốc gần như chắc chắn là rác.
    return bool(translated.strip()) and len(translated) <= len(source) * 6 + 40


def _translate_chunk(texts: list[str], language: str) -> dict[str, str]:
    payload = {str(index): text for index, text in enumerate(texts, start=1)}
    content = chat._ollama_chat(
        [
            {"role": "system", "content": _SYSTEM_PROMPT.replace("{language}", ENGLISH_NAMES[language])},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        deterministic=True,
        model=settings.ollama_narration_model or None,
        think=False,
        num_ctx=settings.ollama_narration_num_ctx,
        timeout=settings.ollama_narration_timeout_seconds,
    )
    if content is None:
        return {}
    parsed = chat._extract_json_object(content)
    if parsed is None:
        logger.warning("Bản dịch %s không phải JSON: %.200s", language, content)
        return {}
    result: dict[str, str] = {}
    for key, source in payload.items():
        translated = parsed.get(key)
        if isinstance(translated, str) and _plausible(source, translated):
            result[source] = translated.strip()
    return result


def translate_texts(texts: list[str], language: str) -> dict[str, str]:
    """Dịch ``texts`` (tiếng Việt) sang ``language``; trả về chỉ những chuỗi
    dịch được. Chuỗi đã có trong cache không gọi LLM lại."""
    if not is_supported(language):
        return {}
    wanted = [
        text for text in dict.fromkeys(texts) if text.strip() and len(text) <= MAX_TEXT_LENGTH
    ]
    # Khoá chỉ bao quanh việc đọc/ghi cache, KHÔNG bao lượt gọi LLM (tới cả
    # phút) — không thì `cached_translations` của người dùng khác phải chờ.
    lock = _lock_for(language)
    with lock:
        cache = _load(language)
        missing = [text for text in wanted if text not in cache]
    for chunk in _chunks(missing):
        translated = _translate_chunk(chunk, language)
        if translated:
            with lock:
                cache.update(translated)
                _save(language, cache)
    with lock:
        return {text: cache[text] for text in wanted if text in cache}

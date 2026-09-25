"""Thuyết minh POI có CACHE và TẠO SẴN — lớp nằm giữa API và `chat`/`tts`.

Vấn đề cũ: chữ thuyết minh chỉ sinh khi người dùng bấm nút, và endpoint audio
lại gọi LLM thêm một lần nữa — mỗi lần nghe một POI mới phải chờ LLM + TTS
(~2 phút trên CPU, đo được thật 2026-09-20), và chữ hiển thị có thể lệch với
câu đang đọc.

Giờ:
- Chữ và audio cùng cache theo (poi_id, language) trên volume `tts_cache`
  (xem `app/tts.py`). Audio LUÔN đọc đúng chữ đã cache, không sinh lại chữ.
- `start_prewarm()` chạy một thread nền lúc khởi động, sinh sẵn chữ cho mọi
  ngôn ngữ rồi audio cho ngôn ngữ có giọng đọc, với mọi POI có
  `poi_knowledge` — chỉ những mục CHƯA có trong cache.
- Bản chữ ghép thô khi Ollama chết (`fallback`) KHÔNG được cache, để lần sau
  còn thử lại LLM thay vì giữ vĩnh viễn một bản kém mượt.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

import psycopg

from . import chat, tts
from .config import settings

logger = logging.getLogger("nearby-narration")

# Khoá theo từng (poi_id, language, loại): người dùng mở đúng POI mà thread
# prewarm đang sinh thì request chờ rồi đọc cache, không gọi LLM/TTS lần hai.
_locks: dict[tuple[str, str, str], threading.Lock] = {}
_locks_guard = threading.Lock()
# Engine TTS dùng chung một instance và chạy CPU thuần — chạy song song hai
# lượt chỉ làm cả hai chậm đi, nên tổng hợp giọng nói tuần tự.
_synth_lock = threading.Lock()


def _lock_for(poi_id: str, language: str, kind: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault((poi_id, language, kind), threading.Lock())


def _normalize_language(language: str) -> str:
    return language if language in chat.NARRATION_LANGUAGES else chat.DEFAULT_NARRATION_LANGUAGE


def get_text(poi_id: str, language: str) -> dict[str, Any]:
    """Chữ thuyết minh — từ cache nếu có, không thì sinh bằng LLM rồi cache.
    Cùng dạng kết quả với `chat.generate_poi_narration`."""
    language = _normalize_language(language)
    cached = tts.get_cached_text(poi_id, language)
    if cached is not None:
        return {"available": True, **cached, "language": language, "cached": True}

    with _lock_for(poi_id, language, "text"):
        cached = tts.get_cached_text(poi_id, language)
        if cached is not None:
            return {"available": True, **cached, "language": language, "cached": True}
        result = chat.generate_poi_narration(poi_id, language=language)
        if result["available"] and result["narration"] and not result.get("fallback"):
            tts.store_text(poi_id, language, result["narration"], result["verified"])
        return {**result, "cached": False}


def has_cached_audio(poi_id: str, language: str) -> bool:
    return tts.has_audio(poi_id, _normalize_language(language))


def get_audio(poi_id: str, language: str) -> tuple[str, dict[str, Any] | None]:
    """Audio đọc đúng chữ trong `get_text`.

    Trả ``("ok", {...})``, ``("unavailable", None)`` khi POI không có
    thuyết minh, hoặc ``("no_voice", None)`` khi ngôn ngữ chưa có giọng / TTS
    lỗi — frontend tự rơi về speechSynthesis trong trường hợp này.
    """
    language = _normalize_language(language)
    cached = tts.get_cached(poi_id, language)
    if cached is not None:
        return "ok", {**cached, "cache": "hit"}

    text = get_text(poi_id, language)
    if not text["available"] or not text["narration"]:
        return "unavailable", None
    if language not in tts.VOICE_BY_LANGUAGE:
        return "no_voice", None

    with _lock_for(poi_id, language, "audio"):
        cached = tts.get_cached(poi_id, language)
        if cached is not None:
            return "ok", {**cached, "cache": "hit"}
        with _synth_lock:
            audio = tts.synthesize(text["narration"], language)
        if audio is None:
            return "no_voice", None
        if not text.get("fallback"):
            tts.store(poi_id, language, text["narration"], text["verified"], audio)
        return "ok", {
            "narration": text["narration"],
            "verified": text["verified"],
            "audio": audio,
            "cache": "miss",
        }


def _poi_ids_with_knowledge() -> list[str]:
    with psycopg.connect(settings.database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT poi_id::text FROM poi_knowledge ORDER BY poi_id")
            return [row[0] for row in cursor.fetchall()]


def prewarm() -> None:
    """Sinh sẵn chữ (các ngôn ngữ trong `PREWARM_NARRATION_LANGUAGES`) trước,
    rồi mới tới audio — chữ nhanh hơn nhiều, nên người dùng có chữ cho mọi POI
    sớm nhất có thể. Các ngôn ngữ khác sinh ở lần chọn đầu tiên."""
    try:
        poi_ids = _poi_ids_with_knowledge()
    except psycopg.Error as error:
        logger.warning("Prewarm thuyết minh: không đọc được poi_knowledge: %s", error)
        return

    logger.info("Prewarm thuyết minh cho %d POI", len(poi_ids))
    for language in chat.PREWARM_NARRATION_LANGUAGES:
        for poi_id in poi_ids:
            try:
                get_text(poi_id, language)
            except Exception as error:  # noqa: BLE001 - một POI lỗi không được dừng cả lượt
                logger.warning("Prewarm chữ lỗi (%s/%s): %s", poi_id, language, error)

    if not settings.tts_enabled:
        return
    for language in tts.VOICE_BY_LANGUAGE:
        for poi_id in poi_ids:
            if tts.has_audio(poi_id, language):
                continue
            try:
                status, _ = get_audio(poi_id, language)
                logger.info("Prewarm audio %s/%s: %s", poi_id, language, status)
            except Exception as error:  # noqa: BLE001
                logger.warning("Prewarm audio lỗi (%s/%s): %s", poi_id, language, error)
    logger.info("Prewarm thuyết minh xong")


def start_prewarm() -> None:
    if not settings.narration_prewarm:
        return
    threading.Thread(target=prewarm, name="narration-prewarm", daemon=True).start()

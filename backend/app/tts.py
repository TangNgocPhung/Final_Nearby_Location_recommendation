"""Text-to-Speech (Phase 16.2) — sinh audio THẬT từ narration text, thay
``speechSynthesis`` của trình duyệt.

Lý do đổi: ``speechSynthesis`` phụ thuộc HOÀN TOÀN vào giọng đã cài sẵn trên
máy người xem — đo được thật (2026-09-20) một máy Windows không có giọng
tiếng Việt, phải đọc tiếng Việt bằng giọng mặc định (thường là tiếng Anh),
nghe không tự nhiên. Rủi ro này không chấp nhận được cho ngày bảo vệ luận
văn, nơi máy trình chiếu là một biến số không kiểm soát được.

Đã cân nhắc Edge TTS (dịch vụ "Đọc to" của Microsoft Edge, không chính thức,
miễn phí) nhưng loại vì nó đổi một phụ thuộc-máy-người-xem thành một phụ
thuộc-mạng-và-dịch-vụ-không-SLA — không tốt hơn cho ngày demo. Chọn
VieNeu-TTS: chạy CPU thuần (không cần GPU), có giọng tiếng Việt dựng sẵn,
không cần API key, không cần Internet SAU lần tải model đầu tiên.

Model KHÔNG đóng gói sẵn vào Docker image (image sẽ phình thêm hàng trăm MB
cho một tính năng không phải lúc nào cũng bật) — tự tải từ Hugging Face ở
LẦN GỌI ĐẦU TIÊN, cache tại ``~/.cache/huggingface`` bên trong container.
Thư mục này PHẢI có volume riêng trong docker-compose.yml, nếu không mỗi lần
`docker compose build backend` (rất thường xuyên trong lúc phát triển) sẽ
tải lại toàn bộ model.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from .config import settings

logger = logging.getLogger("nearby-tts")

# Cache audio ĐÃ SINH theo (poi_id, language) — Phase 16.3.
#
# Vì sao cache ở đây thay vì chỉ dựa vào việc người dùng bấm nhanh hơn: một
# lượt thuyết minh cộng dồn LLM (~20-90s) + TTS (~30-60s, RTF≈1) có thể mất
# tới hơn 2 phút — đo được thật (2026-09-20). Với đúng 14 POI có
# `poi_knowledge`, nội dung KHÔNG đổi giữa các lần hỏi (grounded vào cùng một
# nguồn tĩnh), nên không có lý do gì để sinh lại từ đầu mỗi lần người dùng
# bấm "Nghe thuyết minh" cho cùng một POI — lần đầu vẫn chậm (chưa có gì để
# cache), những lần sau gần như tức thì.
#
# Thư mục PHẢI có volume riêng trong docker-compose.yml (giống HF cache),
# nếu không cache mất trắng mỗi lần `docker compose build backend`.
CACHE_DIR = Path(os.environ.get("TTS_CACHE_DIR", "/app/tts_cache"))


def _cache_paths(poi_id: str, language: str) -> tuple[Path, Path]:
    base = CACHE_DIR / f"{poi_id}_{language}"
    return base.with_suffix(".wav"), base.with_suffix(".json")


def get_cached(poi_id: str, language: str) -> dict[str, Any] | None:
    """Đọc audio + metadata đã cache, hoặc ``None`` nếu chưa có (cache miss —
    hoàn toàn bình thường, KHÔNG phải lỗi)."""
    audio_path, meta_path = _cache_paths(poi_id, language)
    if not audio_path.exists() or not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        audio_bytes = audio_path.read_bytes()
    except (OSError, json.JSONDecodeError) as error:
        # Cache hỏng (ghi dở dang, đĩa lỗi, ...) — coi như cache miss, để sinh
        # lại từ đầu, KHÔNG để lỗi đọc cache làm hỏng cả tính năng thuyết minh.
        logger.warning("Đọc cache thuyết minh hỏng (%s/%s): %s", poi_id, language, error)
        return None
    return {"narration": meta.get("narration"), "verified": meta.get("verified"), "audio": audio_bytes}


def get_cached_text(poi_id: str, language: str) -> dict[str, Any] | None:
    """Chỉ đọc PHẦN CHỮ đã cache (file .json), không cần có audio — dùng cho
    endpoint `/narration` (hiện chữ ngay khi mở panel) và cho ngôn ngữ chưa
    có giọng đọc (vd "en"), nơi chỉ có chữ chứ không bao giờ có file .wav."""
    _, meta_path = _cache_paths(poi_id, language)
    if not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        logger.warning("Đọc cache chữ thuyết minh hỏng (%s/%s): %s", poi_id, language, error)
        return None
    if not meta.get("narration"):
        return None
    return {"narration": meta["narration"], "verified": meta.get("verified")}


def has_audio(poi_id: str, language: str) -> bool:
    audio_path, _ = _cache_paths(poi_id, language)
    return audio_path.exists()


def store_text(poi_id: str, language: str, narration: str, verified: bool | None) -> None:
    """Ghi riêng phần chữ — audio (nếu có) ghi sau bằng `store`. Cùng nguyên
    tắc với `store`: lỗi ghi chỉ log, không raise."""
    _, meta_path = _cache_paths(poi_id, language)
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(
            json.dumps({"narration": narration, "verified": verified}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as error:
        logger.warning("Ghi cache chữ thuyết minh thất bại (%s/%s): %s", poi_id, language, error)


def store(poi_id: str, language: str, narration: str, verified: bool | None, audio: bytes) -> None:
    """Ghi cache. Lỗi ghi (đĩa đầy, không có quyền, ...) chỉ log — KHÔNG raise,
    vì response cho lượt NÀY đã có đủ dữ liệu để trả về rồi, ghi cache thất
    bại chỉ có nghĩa là lượt SAU sẽ phải sinh lại, không phải sự cố người
    dùng cần thấy."""
    audio_path, meta_path = _cache_paths(poi_id, language)
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        # Ghi ra file tạm rồi đổi tên: phần chữ (.json) có thể đã nằm sẵn từ
        # trước (`store_text`), nên `get_cached` không được thấy một file .wav
        # mới ghi dở.
        tmp_audio = audio_path.with_suffix(".wav.tmp")
        tmp_audio.write_bytes(audio)
        os.replace(tmp_audio, audio_path)
        meta_path.write_text(
            json.dumps({"narration": narration, "verified": verified}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as error:
        logger.warning("Ghi cache thuyết minh thất bại (%s/%s): %s", poi_id, language, error)

_engine = None
_engine_lock = threading.Lock()

# VieNeu-TTS hiện CHỈ có giọng tiếng Việt dựng sẵn (25 giọng, 3 miền) — không
# có giọng tiếng Anh tương đương. Ngôn ngữ không có trong bảng này thì
# `synthesize` trả None, bên gọi (frontend) tự rơi về `speechSynthesis` của
# trình duyệt cho đúng ngôn ngữ đó — browser thường có sẵn giọng en-US, nên
# rủi ro "thiếu giọng" chủ yếu chỉ xảy ra với tiếng Việt, đúng vấn đề module
# này giải quyết.
VOICE_BY_LANGUAGE: dict[str, str] = {"vi": "Minh Quân Pro"}


def _get_engine():
    """Nạp model MỘT LẦN, dùng lại cho mọi request — nạp lại mỗi lần tốn
    thêm khoảng chục giây không cần thiết (đo được thật lúc thử nghiệm)."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                from vieneu import Vieneu  # import trễ: gói nặng, chỉ tải khi thật sự cần

                _engine = Vieneu()
    return _engine


def synthesize(text: str, language: str) -> bytes | None:
    """Tổng hợp ``text`` thành audio WAV (bytes).

    Trả ``None`` khi: TTS bị tắt (``settings.tts_enabled``), ngôn ngữ chưa có
    giọng, văn bản rỗng, hoặc engine lỗi (model chưa tải xong, hết bộ nhớ,
    v.v.). Bên gọi coi đó là "audio tạm không dùng được" — cùng triết lý
    graceful-degradation đã dùng cho Ollama/thời tiết/ảnh trong project này,
    KHÔNG được làm hỏng cả tính năng thuyết minh chỉ vì lớp giọng đọc lỗi.
    """
    if not settings.tts_enabled:
        return None
    voice = VOICE_BY_LANGUAGE.get(language)
    if voice is None or not text.strip():
        return None

    tmp_path: str | None = None
    try:
        engine = _get_engine()
        audio = engine.infer(text, voice=voice)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
        engine.save(audio, tmp_path)
        with open(tmp_path, "rb") as handle:
            return handle.read()
    except Exception as error:  # noqa: BLE001 - engine bên thứ ba, không rõ hết các kiểu lỗi
        logger.warning("Tổng hợp giọng nói thất bại (%s): %s", language, error)
        return None
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

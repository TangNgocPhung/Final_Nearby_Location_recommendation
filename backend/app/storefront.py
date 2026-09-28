"""Xác minh địa điểm bằng biển hiệu trong ảnh đường phố.

Dữ liệu OSM ở TP.HCM thường cũ: quán đổi chủ, đổi tên, đóng cửa mà bản đồ vẫn
giữ. Module này tự kiểm chứng, không cần người đi khảo sát:

1. Lấy ảnh Mapillary NHÌN VỀ PHÍA địa điểm (`streetview.ranked_views`): ảnh
   thường chụp thẳng mặt tiền + ảnh 360° đã CẮT đúng hướng tới quán.
2. Model thị giác chạy cục bộ (Ollama, qwen3.5) đọc chữ trên biển hiệu.
3. So khớp GẦN ĐÚNG với tên POI (bỏ dấu, bỏ từ chỉ loại như "hotel", "cà phê").

Vì sao gần đúng và vì sao cần NHIỀU ảnh — đo thật ở khách sạn Trung Mai
(2026-09-25): ảnh ban ngày đọc thành "TRUNG NAM HOTEL" (sai MAI→NAM), ảnh 360°
đọc đúng "TRUNG MAI", ảnh đêm nhoè đọc thành "TOMAS". Một ảnh đơn lẻ không đủ
tin; kết luận dựa trên phiếu của nhiều ảnh.

Kết luận (xem migration 0026):
- ``verified``: một ảnh khớp mạnh, hoặc hai ảnh khớp vừa.
- ``mismatch``: ảnh CŨ khớp tên nhưng ảnh MỚI HƠN ít nhất một năm, rõ nét, gần
  mặt tiền lại đọc được một biển hiệu KHÁC và không ảnh mới nào khớp. Đây là
  bằng chứng "đổi chủ/đóng cửa" duy nhất được chấp nhận — không đọc được biển
  (xe che, tối) KHÔNG phải bằng chứng quán đã đóng.
- ``unreadable`` / ``no_imagery``: không kết luận gì, giao diện không hiện.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import math
import re
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

import psycopg
from psycopg.rows import dict_row

from . import streetview
from .config import settings

logger = logging.getLogger("nearby-storefront")

MAX_FACING_IMAGES = 3
MAX_PANO_IMAGES = 2
# Ngưỡng điểm khớp (0..1). Đo trên Trung Mai: đọc đúng → 1,0; đọc sai một chữ
# ("TRUNG NAM" so với "trung mai") → 0,78. Một ảnh ≥ STRONG là đủ; ở mức
# WEAK phải có hai ảnh cùng khớp.
STRONG_MATCH = 0.85
WEAK_MATCH = 0.7
# Ảnh "mới" chỉ được dùng làm bằng chứng đổi biển khi đủ tiêu chuẩn này.
MISMATCH_MIN_YEARS_NEWER = 1.0
MISMATCH_MAX_DISTANCE_METERS = 25.0
MISMATCH_MIN_QUALITY = 0.5
NO_MATCH = 0.5

# Cắt ảnh 360° (equirectangular): 90° quanh hướng tới quán, dải quanh đường
# chân trời — nơi có biển hiệu. Ảnh nhỏ hơn thì model đọc nhanh hơn và nét hơn
# so với đưa cả ảnh toàn cảnh.
PANO_CROP_DEGREES = 90
PANO_CROP_TOP = 0.22
PANO_CROP_BOTTOM = 0.68
# Model thị giác tính token theo số điểm ảnh: đo thật trên CPU máy dev, ảnh
# 1280 px mất ~95 giây. Cắt đúng vùng mặt tiền rồi thu về 768 px giữ được chữ
# biển hiệu mà nhanh hơn nhiều.
MAX_IMAGE_WIDTH = 768
# Ảnh thường: giả định góc nhìn ngang ~90° (camera hành trình/camera hông xe).
PERSPECTIVE_FOV_DEGREES = 90
PERSPECTIVE_CROP_WIDTH = 0.6
PERSPECTIVE_CROP_TOP = 0.08
PERSPECTIVE_CROP_BOTTOM = 0.72
# Giới hạn độ dài câu trả lời: chỉ cần danh sách chữ, không để model viết dài.
OCR_MAX_TOKENS = 160
DOWNLOAD_TIMEOUT_SECONDS = 20

OCR_PROMPT = (
    "Read the text on every shop sign / business signboard in this street photo. "
    "Output one sign per line, exactly as written (keep Vietnamese diacritics). "
    "Only the text, no commentary. If no sign is readable, output NONE."
)

# Từ chỉ LOẠI địa điểm — bỏ đi để còn phần tên riêng. "Khách sạn Trung Mai" và
# biển "TRUNG MAI HOTEL" chung nhau đúng phần "trung mai".
_GENERIC_PHRASES = (
    "khach san", "nha nghi", "nha hang", "ca phe", "cua hang", "tiem", "quan an", "quan",
    "hotel", "hostel", "motel", "homestay", "apartment", "residence", "inn",
    "cafe", "coffee", "tea", "restaurant", "bistro", "bar", "pub", "shop", "store",
    "spa", "salon", "the", "and",
)


def normalize(text: str) -> str:
    """Chữ thường, bỏ dấu (đ → d), chỉ giữ chữ-số, các từ cách nhau một dấu cách."""
    text = unicodedata.normalize("NFD", text.lower().replace("đ", "d").replace("Đ", "d"))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _strip_generic(text: str) -> str:
    core = f" {normalize(text)} "
    for phrase in _GENERIC_PHRASES:
        core = core.replace(f" {phrase} ", " ")
    return re.sub(r"\s+", " ", core).strip()


def core_name(name: str) -> str:
    """Phần tên riêng của POI (bỏ từ chỉ loại). Quá ngắn thì giữ tên đầy đủ."""
    core = _strip_generic(name)
    return core if len(core.replace(" ", "")) >= 3 else normalize(name)


def match_score(name: str, text: str) -> float:
    """Độ giống (0..1) giữa tên POI và MỘT dòng chữ đọc được.

    Chứa trọn phần tên riêng → 1,0. Không thì trượt cửa sổ cùng số từ (±1) trên
    dòng chữ, lấy tỉ lệ giống cao nhất — chịu được lỗi đọc sai một vài ký tự.
    """
    core = core_name(name)
    line = normalize(text)
    if not core or not line:
        return 0.0
    if f" {core} " in f" {line} ":
        return 1.0
    words = line.split()
    size = len(core.split())
    best = SequenceMatcher(None, core, line).ratio()
    for width in {max(1, size - 1), size, size + 1}:
        for start in range(0, max(1, len(words) - width + 1)):
            window = " ".join(words[start : start + width])
            best = max(best, SequenceMatcher(None, core, window).ratio())
    return round(best, 3)


def best_match(name: str, texts: list[str]) -> tuple[float, str | None]:
    best, best_text = 0.0, None
    for text in texts:
        score = match_score(name, text)
        if score > best:
            best, best_text = score, text
    return best, best_text


def _is_name_like(text: str) -> bool:
    """Dòng chữ có vẻ là TÊN một cơ sở (không chỉ là "HOTEL", "30m", biển giao thông).

    KHÔNG dùng ``core_name`` ở đây: nó lùi về tên đầy đủ khi phần còn lại quá
    ngắn, nên "HOTEL" đứng một mình sẽ bị tính là một cái tên — và một ảnh mới
    chỉ đọc được "HOTEL" thành bằng chứng giả rằng quán đã đổi chủ.
    """
    letters = re.sub(r"[^a-z]", "", _strip_generic(text))
    return len(letters) >= 4


# --- Ảnh ------------------------------------------------------------------------


def pano_center_x(view: dict[str, Any]) -> float:
    """Toạ độ x (0..1) của hướng tới địa điểm trên ảnh 360° — cùng công thức với
    khung xem 360° ở frontend (components/street-view.tsx)."""
    compass = view.get("compassAngle")
    if compass is None:
        return 0.5
    return ((view["bearingToPoi"] - compass) / 360 + 0.5) % 1


def perspective_center_x(view: dict[str, Any]) -> float:
    """Toạ độ x (0..1) của hướng tới địa điểm trên ảnh thường, theo góc lệch giữa
    hướng máy quay và hướng tới quán (phép chiếu phối cảnh, FOV giả định)."""
    compass = view.get("compassAngle")
    if compass is None:
        return 0.5
    offset = (view["bearingToPoi"] - compass + 180) % 360 - 180
    half = math.radians(PERSPECTIVE_FOV_DEGREES / 2)
    x = 0.5 + math.tan(math.radians(max(-44.0, min(44.0, offset)))) / (2 * math.tan(half))
    return min(1.0, max(0.0, x))


def prepare_image(data: bytes, view: dict[str, Any]) -> bytes:
    """Cắt vùng quanh hướng tới quán rồi thu nhỏ về ≤ MAX_IMAGE_WIDTH.

    Ảnh 360°: cắt 90° quanh hướng tới quán (nối vòng qua mép ảnh nếu cần).
    Ảnh thường: cắt 60% bề ngang quanh vị trí mặt tiền, bỏ mặt đường/nắp capo
    phía dưới — nơi không bao giờ có biển hiệu.
    """
    from PIL import Image

    image = Image.open(io.BytesIO(data)).convert("RGB")
    if view.get("isPano"):
        width, height = image.size
        crop_w = int(width * PANO_CROP_DEGREES / 360)
        center = int(pano_center_x(view) * width)
        left = center - crop_w // 2
        top, bottom = int(height * PANO_CROP_TOP), int(height * PANO_CROP_BOTTOM)
        # Nối hai bản ảnh cạnh nhau để cắt qua mép 0°/360° không bị hụt.
        doubled = Image.new("RGB", (width * 2, height))
        doubled.paste(image, (0, 0))
        doubled.paste(image, (width, 0))
        left %= width
        image = doubled.crop((left, top, left + crop_w, bottom))
    else:
        width, height = image.size
        crop_w = int(width * PERSPECTIVE_CROP_WIDTH)
        center = int(perspective_center_x(view) * width)
        left = min(max(0, center - crop_w // 2), width - crop_w)
        image = image.crop(
            (left, int(height * PERSPECTIVE_CROP_TOP), left + crop_w, int(height * PERSPECTIVE_CROP_BOTTOM))
        )
    if image.width > MAX_IMAGE_WIDTH:
        ratio = MAX_IMAGE_WIDTH / image.width
        image = image.resize((MAX_IMAGE_WIDTH, int(image.height * ratio)))
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=88)
    return out.getvalue()


def _download(url: str) -> bytes | None:
    try:
        with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
            return response.read()
    except (urllib.error.URLError, OSError) as error:
        logger.debug("Không tải được ảnh: %s", error)
        return None


def read_signs(image_bytes: bytes) -> list[str] | None:
    """Chữ trên biển hiệu, mỗi biển một dòng. ``None`` = không gọi được model."""
    if not settings.ollama_url:
        return None
    body = {
        "model": settings.ollama_vision_model,
        "stream": False,
        # Qwen3.5 có chế độ "thinking" — tắt để chỉ nhận danh sách chữ.
        "think": False,
        # Giữ model trong RAM giữa các POI: mặc định Ollama gỡ sau 5 phút, và
        # nạp lại khi máy dev đang thiếu RAM hay hỏng (`std::bad_alloc` → 500).
        "keep_alive": "30m",
        "options": {"temperature": 0, "num_ctx": 4096, "num_predict": OCR_MAX_TOKENS},
        "messages": [
            {
                "role": "user",
                "content": OCR_PROMPT,
                "images": [base64.b64encode(image_bytes).decode()],
            }
        ],
    }
    request = urllib.request.Request(
        f"{settings.ollama_url.rstrip('/')}/api/chat",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    payload = None
    # Thử lại: Ollama trả lỗi thoáng qua khi đang nạp/đổi model (vd. backend
    # vừa khởi động và gọi cùng model với num_ctx khác, hoặc nạp hụt RAM). Nạp
    # model mất ~20 giây nên chờ tăng dần. Hết thời gian chờ thì KHÔNG thử lại
    # — ảnh đó quá nặng, thử lại chỉ tốn thêm vài phút.
    attempts = 3
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(
                request, timeout=settings.ollama_vision_timeout_seconds
            ) as response:
                payload = json.load(response)
            break
        except TimeoutError as error:
            logger.warning("Model thị giác quá thời gian chờ: %s", error)
            return None
        except (urllib.error.URLError, OSError, ValueError) as error:
            logger.warning("Model thị giác không trả lời (lần %d): %s", attempt + 1, error)
            if attempt < attempts - 1:
                time.sleep(15 * (attempt + 1))
    if payload is None:
        return None
    content = ((payload.get("message") or {}).get("content") or "").strip()
    lines = []
    for raw in content.splitlines():
        line = re.sub(r"^[\s\-\*•\d\.\)]+", "", raw).strip().strip('"')
        if line and line.upper() != "NONE" and len(line) <= 80:
            lines.append(line)
    return lines[:30]


# --- Kết luận -----------------------------------------------------------------------


def _captured(view: dict[str, Any]) -> datetime | None:
    text = view.get("capturedAt")
    try:
        return datetime.fromisoformat(text) if text else None
    except ValueError:
        return None


def decide(name: str, readings: list[dict[str, Any]]) -> dict[str, Any]:
    """Gộp kết quả đọc của nhiều ảnh thành một kết luận. ``readings`` xếp MỚI → CŨ.

    Mỗi phần tử: ``{imageId, capturedAt, distanceMeters, quality, texts, score,
    matchedText, ...}``. Hàm thuần — kiểm thử được mà không cần ảnh hay model.
    """
    if not readings:
        return {"status": "no_imagery", "score": None, "matchedText": None, "evidence": None}

    strong = [r for r in readings if r["score"] >= STRONG_MATCH]
    weak = [r for r in readings if r["score"] >= WEAK_MATCH]
    matched = strong[0] if strong else (weak[0] if len(weak) >= 2 else None)

    if matched is not None:
        matched_at = _captured(matched)
        newer_contradicting = []
        for reading in readings:
            captured = _captured(reading)
            if captured is None or matched_at is None:
                continue
            years_newer = (captured - matched_at).days / 365.25
            if (
                years_newer >= MISMATCH_MIN_YEARS_NEWER
                and reading["score"] < NO_MATCH
                and reading["distanceMeters"] <= MISMATCH_MAX_DISTANCE_METERS
                and (reading.get("quality") is None or reading["quality"] >= MISMATCH_MIN_QUALITY)
                and any(_is_name_like(text) for text in reading["texts"])
            ):
                newer_contradicting.append(reading)
        # Ảnh mới hơn cả ảnh phản bác mà vẫn khớp tên thì không tính là đổi biển.
        latest_contra = max((_captured(r) for r in newer_contradicting), default=None)
        still_matches_later = latest_contra is not None and any(
            (_captured(r) or matched_at) >= latest_contra and r["score"] >= WEAK_MATCH
            for r in readings
        )
        if newer_contradicting and not still_matches_later:
            evidence = newer_contradicting[0]
            return {
                "status": "mismatch",
                "score": matched["score"],
                "matchedText": ", ".join(t for t in evidence["texts"] if _is_name_like(t))[:200],
                "evidence": evidence,
            }
        score = matched["score"] if strong else round(sum(r["score"] for r in weak[:2]) / 2, 3)
        return {
            "status": "verified",
            "score": score,
            "matchedText": matched["matchedText"],
            "evidence": matched,
        }

    readable = [r for r in readings if r["texts"]]
    return {
        "status": "unreadable",
        "score": max((r["score"] for r in readings), default=None),
        "matchedText": None,
        "evidence": readable[0] if readable else None,
    }


def select_views(lat: float, lng: float) -> list[dict[str, Any]] | None:
    """Ảnh sẽ đọc cho một POI, xếp MỚI → CŨ. ``None`` = không hỏi được Mapillary."""
    ranked = streetview.ranked_views(lat, lng)
    if ranked is None:
        return None
    panos, facing = ranked
    chosen = facing[:MAX_FACING_IMAGES] + panos[:MAX_PANO_IMAGES]
    chosen.sort(key=lambda view: view.get("capturedAt") or "", reverse=True)
    return chosen


def verify(poi: dict[str, Any]) -> dict[str, Any] | None:
    """Xác minh MỘT POI (``{poiId, name, latitude, longitude}``).

    Đọc ảnh từ mới tới cũ và dừng sớm khi đã khớp mạnh — mỗi ảnh tốn 3-50 giây
    trên CPU. ``None`` = không chạy được (Mapillary/model không trả lời), khi đó
    KHÔNG ghi gì vào DB để lần sau chạy lại.
    """
    views = select_views(poi["latitude"], poi["longitude"])
    if views is None:
        return None
    readings: list[dict[str, Any]] = []
    for view in views:
        data = _download(view.get("thumbLargeUrl") or view.get("thumbUrl") or "")
        if data is None:
            continue
        texts = read_signs(prepare_image(data, view))
        if texts is None:
            return None
        score, matched_text = best_match(poi["name"], texts)
        readings.append(
            {
                "imageId": view["imageId"],
                "capturedAt": view.get("capturedAt"),
                "isPano": view.get("isPano", False),
                "centerX": round(pano_center_x(view), 4) if view.get("isPano") else None,
                "distanceMeters": view["distanceMeters"],
                "quality": view.get("_quality"),
                "texts": texts,
                "score": score,
                "matchedText": matched_text,
            }
        )
        if score >= STRONG_MATCH:
            break
    result = decide(poi["name"], readings)
    result["readings"] = readings
    return result


def store(poi_id: str, result: dict[str, Any], database_url: str | None = None) -> None:
    evidence = result.get("evidence") or {}
    with psycopg.connect(database_url or settings.database_url) as connection:
        connection.execute(
            """
            INSERT INTO poi_verifications (
                poi_id, status, score, matched_text, evidence_image_id,
                evidence_captured_at, evidence, model, checked_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, NOW())
            ON CONFLICT (poi_id) DO UPDATE SET
                status = EXCLUDED.status, score = EXCLUDED.score,
                matched_text = EXCLUDED.matched_text,
                evidence_image_id = EXCLUDED.evidence_image_id,
                evidence_captured_at = EXCLUDED.evidence_captured_at,
                evidence = EXCLUDED.evidence, model = EXCLUDED.model,
                checked_at = NOW()
            """,
            (
                poi_id,
                result["status"],
                result.get("score"),
                result.get("matchedText"),
                evidence.get("imageId"),
                evidence.get("capturedAt"),
                json.dumps(result.get("readings") or [], ensure_ascii=False),
                settings.ollama_vision_model,
            ),
        )


def get_verification(poi_id: str) -> dict[str, Any]:
    """Kết quả xác minh cho panel chi tiết, kèm URL ảnh bằng chứng MỚI.

    Chỉ ``verified``/``mismatch`` mang ý nghĩa cho người dùng; các trạng thái
    còn lại trả nguyên để giao diện tự ẩn.
    """
    with psycopg.connect(settings.database_url, row_factory=dict_row) as connection:
        row = connection.execute(
            """
            SELECT status, score, matched_text AS "matchedText",
                   evidence_image_id AS "imageId", evidence_captured_at AS "capturedAt",
                   evidence, model, checked_at AS "checkedAt"
            FROM poi_verifications WHERE poi_id = %s
            """,
            (poi_id,),
        ).fetchone()
    if row is None:
        return {"poiId": poi_id, "status": "unchecked"}

    evidence = None
    if row["imageId"] and row["status"] in ("verified", "mismatch"):
        reading = next(
            (item for item in row["evidence"] or [] if item.get("imageId") == row["imageId"]),
            {},
        )
        thumb = None
        if settings.mapillary_client_token:
            details = streetview._image_details([row["imageId"]]) or []
            thumb = (details[0].get("thumb_1024_url") if details else None)
        evidence = {
            "imageId": row["imageId"],
            "capturedAt": row["capturedAt"].isoformat() if row["capturedAt"] else None,
            "isPano": bool(reading.get("isPano")),
            "centerX": reading.get("centerX"),
            "distanceMeters": reading.get("distanceMeters"),
            "texts": reading.get("texts") or [],
            "thumbUrl": thumb,
            "sourceUrl": f"https://www.mapillary.com/app/?pKey={row['imageId']}",
        }
    return {
        "poiId": poi_id,
        "status": row["status"],
        "score": row["score"],
        "matchedText": row["matchedText"],
        "checkedAt": row["checkedAt"].astimezone(timezone.utc).isoformat(),
        "model": row["model"],
        "imagesRead": len(row["evidence"] or []),
        "evidence": evidence,
    }

"""Săn địa danh Sài Gòn — khám phá POI kiểu Pokémon GO, nhưng "bắt" câu chuyện.

Luồng: tìm POI → đi tới → chụp ảnh → xác nhận → lưu ảnh → mở khoá câu chuyện →
AI thuyết minh → bộ sưu tập. Hai mục tiêu cùng lúc:

1. Người chơi có lý do đi khám phá thành phố, mỗi nơi mở ra một câu chuyện.
2. Kho ảnh THẬT của Nearby dày lên: OSM/Wikimedia chỉ có ảnh của chính địa
   điểm cho khoảng 0,8% POI (xem `app/photos.py`); mỗi lượt khám phá là một tấm
   ảnh đã được kiểm tra cả vị trí lẫn nội dung.

Chỉ POI có ``poi_knowledge`` ĐÃ KIỂM CHỨNG mới là địa danh săn được — mở khoá
xong phải có câu chuyện thật để kể, không để LLM tự bịa về một nơi không có dữ
liệu (cùng nguyên tắc với tour thuyết minh trong `app/assistant.py`). Bệnh viện
có bài giới thiệu nhưng bị loại: biến việc tới bệnh viện thành trò chơi sưu tập
là sai ngữ cảnh.

Xác nhận "đã tới" gồm hai lớp độc lập:

- **Vị trí** — khoảng cách từ toạ độ người chơi tới POI tính bằng PostGIS, so
  với bán kính theo loại địa điểm (công viên rộng hơn một toà nhà) cộng một
  phần sai số GPS. Toạ độ do trình duyệt báo lên nên KHÔNG chống được giả lập
  vị trí — giới hạn này phải ghi rõ trong báo cáo, không giấu.
- **Ảnh** — model thị giác chạy cục bộ (Ollama, cùng model đọc biển hiệu ở
  `app/storefront.py`) xem ảnh có phải địa điểm đó không. Kết luận ba mức, và
  "không chắc" KHÔNG bị coi là "sai": vị trí đã đúng thì vẫn mở khoá, ảnh chỉ
  chưa được công khai (``pending``).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import logging
import re
import threading
import urllib.error
import urllib.request
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .config import settings
from .poi_features import CATEGORY_MAP

logger = logging.getLogger("nearby-explore")

# Loại nội dung của `poi_knowledge` được đưa vào trò chơi. "medical" bị loại có
# chủ đích — xem docstring module.
HUNTABLE_CONTENT_TYPES = ("historical", "cultural", "architectural", "nature")

CONTENT_TYPE_LABELS = {
    "historical": "lịch sử",
    "cultural": "văn hoá",
    "architectural": "kiến trúc",
    "nature": "thiên nhiên",
}

# Bán kính "đã tới nơi". Toạ độ của một công viên/vườn thú là MỘT điểm giữa khu
# đất rộng hàng chục hecta — đứng ở cổng đã cách tâm vài trăm mét.
DEFAULT_RADIUS_METERS = 150
WIDE_CATEGORIES = {"park": 350, "theme_park": 350}
# Cộng thêm sai số GPS trình duyệt báo, nhưng có trần: một thiết bị báo sai số
# 2 km không được vì thế mà "khám phá" từ nhà.
MAX_ACCURACY_ALLOWANCE_METERS = 60

# Ảnh: trình duyệt đã thu nhỏ trước khi gửi; đây là trần phòng thủ phía server.
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_IMAGE_SIDE = 1280
THUMB_SIDE = 360
MIN_IMAGE_SIDE = 200

# Ngưỡng kết luận từ câu trả lời của model thị giác.
VERIFY_MIN_CONFIDENCE = 0.5
REJECT_MIN_CONFIDENCE = 0.6
VISION_MAX_TOKENS = 200

# Một lượt xem ảnh tốn 3-50 giây CPU (đo trên máy dev, xem config). Cho chạy
# song song thì hai người chơi cùng gửi là cả hai cùng chậm gấp đôi, và Ollama
# dễ hụt RAM — xếp hàng từng ảnh một.
_vision_lock = threading.Semaphore(1)

# Bộ sưu tập — một địa danh có thể nằm trong nhiều bộ (như Pokémon có nhiều hệ).
# Quy tắc theo category + content_type thay vì liệt kê tay từng POI: thêm một
# bài `poi_knowledge` mới là địa danh tự vào đúng bộ, không phải sửa code.
COLLECTIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "di-san-sai-gon",
        "title": "Di sản Sài Gòn",
        "icon": "🏛️",
        "description": "Mọi địa danh có câu chuyện đã kiểm chứng nguồn.",
    },
    {
        "id": "cong-trinh-lich-su",
        "title": "Công trình lịch sử",
        "icon": "🏰",
        "description": "Dinh thự, nhà thờ, bưu điện, địa đạo — nơi lịch sử còn đứng đó.",
    },
    {
        "id": "bao-tang",
        "title": "Bảo tàng",
        "icon": "🖼️",
        "description": "Những nơi lưu giữ ký ức thành phố.",
    },
    {
        "id": "cong-vien-xanh",
        "title": "Công viên & thiên nhiên",
        "icon": "🌳",
        "description": "Lá phổi xanh giữa lòng thành phố.",
    },
    {
        "id": "nhip-song-sai-gon",
        "title": "Nhịp sống Sài Gòn",
        "icon": "🛍️",
        "description": "Chợ, quảng trường — nơi văn hoá đời thường diễn ra.",
    },
)
COLLECTION_IDS = tuple(item["id"] for item in COLLECTIONS)

_CATEGORY_LABELS = {category: label for category, label in CATEGORY_MAP.values()}
_CATEGORY_LABELS.update({"museum": "Bảo tàng", "landmark": "Địa danh", "park": "Công viên"})


def category_label(category: str | None) -> str:
    return _CATEGORY_LABELS.get(category or "", "Địa điểm")


def collections_for(category: str | None, content_type: str | None) -> list[str]:
    """Các bộ sưu tập chứa một địa danh. Luôn có "Di sản Sài Gòn"."""
    result = ["di-san-sai-gon"]
    if category == "museum":
        result.append("bao-tang")
    if category in ("park", "theme_park") or content_type == "nature":
        result.append("cong-vien-xanh")
    elif content_type in ("historical", "architectural"):
        result.append("cong-trinh-lich-su")
    if content_type == "cultural":
        result.append("nhip-song-sai-gon")
    return result


def discover_radius(category: str | None) -> int:
    return WIDE_CATEGORIES.get(category or "", DEFAULT_RADIUS_METERS)


def allowed_distance(category: str | None, accuracy_meters: float | None) -> float:
    allowance = min(max(accuracy_meters or 0.0, 0.0), MAX_ACCURACY_ALLOWANCE_METERS)
    return discover_radius(category) + allowance


def teaser(content_type: str | None, events: list[Any] | None, facts: list[Any] | None) -> str:
    """Gợi tò mò cho địa danh CHƯA mở khoá — nói có gì để mở, không lộ nội dung."""
    parts = [f"Câu chuyện {CONTENT_TYPE_LABELS.get(content_type or '', 'về địa điểm')}"]
    if events:
        parts.append(f"{len(events)} sự kiện")
    if facts:
        parts.append(f"{len(facts)} điều thú vị")
    return " · ".join(parts)


# --- Ảnh --------------------------------------------------------------------------


def decode_upload(image_base64: str) -> bytes:
    """Base64 (có hoặc không có tiền tố data URL) → bytes. Sai định dạng → ValueError."""
    payload = image_base64.strip()
    if payload.startswith("data:"):
        payload = payload.split(",", 1)[-1]
    # Ước lượng trước khi giải mã: không cấp phát 100 MB chỉ để rồi từ chối.
    if len(payload) * 3 // 4 > MAX_UPLOAD_BYTES:
        raise ValueError("Ảnh quá lớn")
    try:
        data = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("Ảnh không đúng định dạng base64") from error
    if not data:
        raise ValueError("Ảnh rỗng")
    return data


def prepare_photo(data: bytes) -> dict[str, Any]:
    """Mã hoá lại ảnh thành JPEG ≤ MAX_IMAGE_SIDE + thumbnail.

    Mã hoá lại chứ không lưu nguyên bytes: (1) loại bỏ EXIF — ảnh chọn từ thư
    viện có thể mang toạ độ GPS nhà riêng; (2) chặn file không phải ảnh giả
    đuôi .jpg; (3) xoay ảnh theo thẻ Orientation một lần cho xong, để mọi nơi
    hiển thị đều đúng chiều.
    """
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        image = Image.open(io.BytesIO(data))
        image = ImageOps.exif_transpose(image).convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise ValueError("Tệp không phải ảnh hợp lệ") from error
    if min(image.size) < MIN_IMAGE_SIDE:
        raise ValueError("Ảnh quá nhỏ để nhận ra địa điểm")

    image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    full = io.BytesIO()
    image.save(full, format="JPEG", quality=85, optimize=True)
    thumb_image = image.copy()
    thumb_image.thumbnail((THUMB_SIDE, THUMB_SIDE))
    thumb = io.BytesIO()
    thumb_image.save(thumb, format="JPEG", quality=80, optimize=True)
    return {
        "image": full.getvalue(),
        "thumbnail": thumb.getvalue(),
        "width": image.width,
        "height": image.height,
        # Băm bytes GỐC người dùng gửi: gửi lại đúng tấm đó thì nhận ra ngay.
        "sha256": hashlib.sha256(data).hexdigest(),
    }


VISION_PROMPT = """You check photos for a sightseeing game in Ho Chi Minh City, Vietnam.
The player says this photo was taken at the landmark "{name}" ({category}).
About the place: {intro}

Reply with JSON only, no other text:
{{"match": "yes" | "no" | "unsure", "confidence": <number 0 to 1>, "seen": "<one short Vietnamese sentence describing what the photo shows>"}}

- "yes": the photo plausibly shows this place: its building, facade, gate, interior, grounds, exhibits, signage, or a distinctive part of it.
- "no": the photo clearly cannot be this place, e.g. a phone or computer screen, a screenshot, a document, only a face, food on a table, a room at home, the inside of a vehicle, or a clearly different kind of place.
- "unsure": anything else."""


def parse_verdict(content: str | None) -> dict[str, Any] | None:
    """Câu trả lời của model → {match, confidence, seen}. Không đọc được → None.

    Model nhỏ đôi khi bọc JSON trong ```json … ``` hoặc thêm câu dẫn, nên tìm
    khối {...} đầu tiên thay vì json.loads cả chuỗi.
    """
    if not content:
        return None
    found = re.search(r"\{.*\}", content, flags=re.DOTALL)
    if not found:
        return None
    try:
        raw = json.loads(found.group(0))
    except ValueError:
        return None
    if not isinstance(raw, dict):
        return None
    match = str(raw.get("match", "")).strip().lower()
    if match not in ("yes", "no", "unsure"):
        return None
    try:
        confidence = float(raw.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0.0
    seen = str(raw.get("seen") or "").strip()[:240]
    return {"match": match, "confidence": max(0.0, min(1.0, confidence)), "seen": seen}


def decide_photo(verdict: dict[str, Any] | None) -> str:
    """``verified`` | ``pending`` | ``rejected``.

    Bất đối xứng có chủ đích: công khai một ảnh cần model khá chắc là ĐÚNG, còn
    bác một lượt khám phá cần model khá chắc là SAI. Mọi trường hợp lưng chừng
    (kể cả model không chạy) đều là ``pending`` — vị trí đã được xác nhận riêng,
    không để một model 4B trên CPU tự quyết người chơi có "tới" hay không.
    """
    if not verdict:
        return "pending"
    if verdict["match"] == "yes" and verdict["confidence"] >= VERIFY_MIN_CONFIDENCE:
        return "verified"
    if verdict["match"] == "no" and verdict["confidence"] >= REJECT_MIN_CONFIDENCE:
        return "rejected"
    return "pending"


def check_photo(image_bytes: bytes, name: str, intro: str | None, category: str | None) -> dict[str, Any] | None:
    """Hỏi model thị giác cục bộ. ``None`` = không hỏi được (không phải "sai")."""
    if not settings.ollama_url:
        return None
    prompt = VISION_PROMPT.format(
        name=name,
        category=category_label(category),
        intro=(intro or "(no description)").strip()[:400],
    )
    body = {
        "model": settings.ollama_vision_model,
        "stream": False,
        "think": False,
        "format": "json",
        "keep_alive": "30m",
        "options": {"temperature": 0, "num_ctx": 4096, "num_predict": VISION_MAX_TOKENS},
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [base64.b64encode(image_bytes).decode()],
            }
        ],
    }
    request = urllib.request.Request(
        f"{settings.ollama_url.rstrip('/')}/api/chat",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    acquired = _vision_lock.acquire(timeout=settings.explore_vision_timeout_seconds)
    if not acquired:
        logger.warning("Hàng chờ xem ảnh quá lâu — bỏ qua bước AI cho ảnh này")
        return None
    try:
        with urllib.request.urlopen(request, timeout=settings.explore_vision_timeout_seconds) as response:
            payload = json.load(response)
    except (TimeoutError, urllib.error.URLError, OSError, ValueError) as error:
        logger.warning("Model thị giác không trả lời: %s", error)
        return None
    finally:
        _vision_lock.release()
    verdict = parse_verdict((payload.get("message") or {}).get("content"))
    if verdict is not None:
        verdict["model"] = settings.ollama_vision_model
    return verdict


# --- Dữ liệu ----------------------------------------------------------------------

_HUNTABLE_COLUMNS = """
    p.id::text AS "poiId", p.name, p.category, p.address,
    ST_Y(p.location::geometry) AS latitude,
    ST_X(p.location::geometry) AS longitude,
    ST_Distance(p.location, ST_SetSRID(ST_MakePoint(%(lng)s, %(lat)s), 4326)::geography)
        AS "distanceMeters",
    k.content_type AS "contentType", k.intro, k.specialty,
    k.historical_context AS "historicalContext",
    k.historical_events AS "historicalEvents",
    k.interesting_facts AS "interestingFacts",
    k.source
"""
_HUNTABLE_FILTER = "k.verified AND k.content_type = ANY(%(types)s)"

_ONE_HUNTABLE_SQL = f"""
    SELECT {_HUNTABLE_COLUMNS}
    FROM poi_knowledge k
    JOIN pois p ON p.id = k.poi_id
    WHERE {_HUNTABLE_FILTER} AND p.id = %(poi)s
"""

_OVERVIEW_SQL = f"""
    SELECT {_HUNTABLE_COLUMNS},
           d.discovered_at AS "discoveredAt",
           ph.thumbnail,
           ph.status AS "photoStatus"
    FROM poi_knowledge k
    JOIN pois p ON p.id = k.poi_id
    LEFT JOIN poi_discoveries d ON d.poi_id = k.poi_id AND d.owner_id = %(owner)s
    LEFT JOIN poi_visitor_photos ph ON ph.id = d.photo_id
    WHERE {_HUNTABLE_FILTER}
    ORDER BY "distanceMeters"
"""


def _story(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "contentType": row["contentType"],
        "contentTypeLabel": CONTENT_TYPE_LABELS.get(row["contentType"], ""),
        "intro": row["intro"],
        "specialty": row["specialty"],
        "historicalContext": row["historicalContext"],
        "historicalEvents": list(row["historicalEvents"] or []),
        "interestingFacts": list(row["interestingFacts"] or []),
        "source": row["source"],
    }


def _thumb_data_url(thumbnail: bytes | memoryview | None) -> str | None:
    if not thumbnail:
        return None
    return "data:image/jpeg;base64," + base64.b64encode(bytes(thumbnail)).decode()


def collection_progress(places: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Tiến độ từng bộ sưu tập từ danh sách địa danh (đã gắn ``collections``)."""
    result = []
    for collection in COLLECTIONS:
        members = [place for place in places if collection["id"] in place["collections"]]
        if not members:
            continue
        found = sum(1 for place in members if place["discovered"])
        result.append(
            {
                **collection,
                "total": len(members),
                "discovered": found,
                "completed": found == len(members),
            }
        )
    return result


def overview(owner_id: str | None, latitude: float, longitude: float) -> dict[str, Any]:
    """Toàn bộ địa danh săn được, gần trước xa sau, kèm trạng thái của người chơi.

    Người chơi chưa có phiên thì mọi địa danh đều "chưa khám phá" — vẫn trả đủ
    danh sách để giao diện hiện bản đồ săn.
    """
    with psycopg.connect(settings.database_url, row_factory=dict_row) as connection:
        rows = connection.execute(
            _OVERVIEW_SQL,
            {"lat": latitude, "lng": longitude, "types": list(HUNTABLE_CONTENT_TYPES), "owner": owner_id},
        ).fetchall()

    places = []
    for row in rows:
        discovered = row["discoveredAt"] is not None
        places.append(
            {
                "poiId": row["poiId"],
                "name": row["name"],
                "category": row["category"],
                "categoryLabel": category_label(row["category"]),
                "address": row["address"],
                "latitude": float(row["latitude"]),
                "longitude": float(row["longitude"]),
                "distanceMeters": round(float(row["distanceMeters"]), 1),
                "radiusMeters": discover_radius(row["category"]),
                "contentType": row["contentType"],
                "collections": collections_for(row["category"], row["contentType"]),
                "teaser": teaser(row["contentType"], row["historicalEvents"], row["interestingFacts"]),
                "discovered": discovered,
                "discoveredAt": row["discoveredAt"].isoformat() if discovered else None,
                "photoThumb": _thumb_data_url(row["thumbnail"]) if discovered else None,
                "photoStatus": row["photoStatus"] if discovered else None,
            }
        )
    found = sum(1 for place in places if place["discovered"])
    return {
        "total": len(places),
        "discovered": found,
        "collections": collection_progress(places),
        "places": places,
    }


def nearby_summary(owner_id: str | None, latitude: float, longitude: float, radius_meters: float) -> dict[str, Any]:
    """Tóm tắt cho chip gợi ý: bao nhiêu địa danh quanh đây, đã khám phá mấy.

    Một câu SQL đếm, không kéo ảnh thumbnail như ``overview`` — chip gợi ý được
    tải mỗi lần mở khung chat.
    """
    with psycopg.connect(settings.database_url, row_factory=dict_row) as connection:
        row = connection.execute(
            f"""
            WITH h AS (
                SELECT {_HUNTABLE_COLUMNS},
                       EXISTS (
                           SELECT 1 FROM poi_discoveries d
                           WHERE d.poi_id = k.poi_id AND d.owner_id = %(owner)s
                       ) AS found
                FROM poi_knowledge k
                JOIN pois p ON p.id = k.poi_id
                WHERE {_HUNTABLE_FILTER}
            )
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE found) AS discovered,
                   COUNT(*) FILTER (WHERE "distanceMeters" <= %(radius)s) AS nearby,
                   COUNT(*) FILTER (WHERE found AND "distanceMeters" <= %(radius)s) AS "discoveredNearby",
                   MIN("distanceMeters") FILTER (WHERE NOT found) AS "nearestMeters"
            FROM h
            """,
            {
                "lat": latitude,
                "lng": longitude,
                "types": list(HUNTABLE_CONTENT_TYPES),
                "owner": owner_id,
                "radius": radius_meters,
            },
        ).fetchone()
    return {
        "total": int(row["total"]),
        "discovered": int(row["discovered"]),
        "nearby": int(row["nearby"]),
        "discoveredNearby": int(row["discoveredNearby"]),
        "nearestMeters": float(row["nearestMeters"]) if row["nearestMeters"] is not None else None,
    }


def story(owner_id: str | None, poi_id: str) -> dict[str, Any] | None:
    """Câu chuyện của một địa danh — chỉ mở khi người chơi đã khám phá.

    ``None`` = không phải địa danh săn được. ``{"locked": True}`` = có câu
    chuyện nhưng chưa tới nơi.
    """
    with psycopg.connect(settings.database_url, row_factory=dict_row) as connection:
        row = connection.execute(
            _ONE_HUNTABLE_SQL,
            {"lat": 0.0, "lng": 0.0, "types": list(HUNTABLE_CONTENT_TYPES), "poi": poi_id},
        ).fetchone()
        if row is None:
            return None
        discovered = (
            owner_id is not None
            and connection.execute(
                "SELECT 1 FROM poi_discoveries WHERE owner_id = %s AND poi_id = %s",
                (owner_id, poi_id),
            ).fetchone()
            is not None
        )
    if not discovered:
        return {
            "poiId": poi_id,
            "name": row["name"],
            "locked": True,
            "teaser": teaser(row["contentType"], row["historicalEvents"], row["interestingFacts"]),
        }
    return {"poiId": poi_id, "name": row["name"], "locked": False, "story": _story(row)}


def discover(
    owner_id: str,
    poi_id: str,
    latitude: float,
    longitude: float,
    accuracy_meters: float | None,
    image_base64: str,
    share_publicly: bool = True,
) -> dict[str, Any]:
    """Một lượt "khám phá". Luôn trả dict có ``status``:

    ``not_found`` · ``too_far`` · ``bad_image`` · ``photo_rejected`` ·
    ``discovered`` (lần đầu) · ``rediscovered`` (đã khám phá, góp thêm ảnh).

    Thứ tự kiểm tra từ rẻ tới đắt: vị trí (một câu SQL) trước, giải mã ảnh sau,
    model thị giác (hàng chục giây) sau cùng — đứng sai chỗ thì không tốn một
    giây CPU nào cho ảnh.
    """
    with psycopg.connect(settings.database_url, row_factory=dict_row) as connection:
        row = connection.execute(
            _ONE_HUNTABLE_SQL,
            {"lat": latitude, "lng": longitude, "types": list(HUNTABLE_CONTENT_TYPES), "poi": poi_id},
        ).fetchone()
    if row is None:
        return {"status": "not_found"}

    distance = float(row["distanceMeters"])
    allowed = allowed_distance(row["category"], accuracy_meters)
    base = {
        "poiId": poi_id,
        "name": row["name"],
        "distanceMeters": round(distance, 1),
        "allowedMeters": round(allowed, 1),
    }
    if distance > allowed:
        return {**base, "status": "too_far"}

    try:
        photo = prepare_photo(decode_upload(image_base64))
    except ValueError as error:
        return {**base, "status": "bad_image", "detail": str(error)}

    verdict = check_photo(photo["image"], row["name"], row["intro"], row["category"])
    photo_status = decide_photo(verdict)
    public_verdict = (
        {"match": verdict["match"], "confidence": verdict["confidence"], "seen": verdict["seen"]}
        if verdict
        else None
    )
    if photo_status == "rejected":
        return {**base, "status": "photo_rejected", "verification": public_verdict}

    with psycopg.connect(settings.database_url, row_factory=dict_row) as connection:
        with connection.transaction():
            photo_row = connection.execute(
                """
                INSERT INTO poi_visitor_photos (
                    poi_id, owner_id, status, is_public, verdict, distance_meters,
                    accuracy_meters, image, thumbnail, width, height, sha256
                )
                VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (poi_id, sha256) DO NOTHING
                RETURNING id::text AS id
                """,
                (
                    poi_id,
                    owner_id,
                    photo_status,
                    share_publicly,
                    json.dumps(verdict or {}, ensure_ascii=False),
                    distance,
                    accuracy_meters,
                    photo["image"],
                    photo["thumbnail"],
                    photo["width"],
                    photo["height"],
                    photo["sha256"],
                ),
            ).fetchone()
            if photo_row is None:
                photo_row = connection.execute(
                    "SELECT id::text AS id, status FROM poi_visitor_photos WHERE poi_id = %s AND sha256 = %s",
                    (poi_id, photo["sha256"]),
                ).fetchone()
                photo_status = photo_row["status"]
            discovery = connection.execute(
                """
                INSERT INTO poi_discoveries (owner_id, poi_id, photo_id, distance_meters)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (owner_id, poi_id)
                DO UPDATE SET photo_id = EXCLUDED.photo_id
                RETURNING (xmax = 0) AS inserted
                """,
                (owner_id, poi_id, photo_row["id"], distance),
            ).fetchone()

    first_time = bool(discovery["inserted"])
    progress = overview(owner_id, latitude, longitude)
    mine = set(collections_for(row["category"], row["contentType"]))
    completed = [
        item for item in progress["collections"] if item["id"] in mine and item["completed"]
    ] if first_time else []
    return {
        **base,
        "status": "discovered" if first_time else "rediscovered",
        "photo": {
            "id": photo_row["id"],
            "status": photo_status,
            "isPublic": share_publicly,
            "url": f"/api/v1/visitor-photos/{photo_row['id']}" if photo_status == "verified" and share_publicly else None,
        },
        "verification": public_verdict,
        "story": _story(row),
        "progress": {"total": progress["total"], "discovered": progress["discovered"]},
        "collections": [item for item in progress["collections"] if item["id"] in mine],
        "completedCollections": completed,
    }


def visitor_photos(poi_id: str, limit: int = 12) -> list[dict[str, Any]]:
    """Ảnh người chơi đã xác minh VÀ đồng ý công khai — cho trang chi tiết POI."""
    with psycopg.connect(settings.database_url, row_factory=dict_row) as connection:
        rows = connection.execute(
            """
            SELECT id::text AS id, width, height, created_at AS "createdAt"
            FROM poi_visitor_photos
            WHERE poi_id = %s AND status = 'verified' AND is_public
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (poi_id, limit),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "url": f"/api/v1/visitor-photos/{row['id']}",
            "thumbUrl": f"/api/v1/visitor-photos/{row['id']}?size=thumb",
            "width": row["width"],
            "height": row["height"],
            "createdAt": row["createdAt"].isoformat(),
            "source": "Người chơi Nearby · Săn địa danh",
        }
        for row in rows
    ]


def photo_bytes(photo_id: str, thumb: bool = False) -> bytes | None:
    """Bytes JPEG của một ảnh CÔNG KHAI. Ảnh ``pending``/riêng tư → None (404)."""
    column = "thumbnail" if thumb else "image"
    with psycopg.connect(settings.database_url) as connection:
        row = connection.execute(
            f"SELECT {column} FROM poi_visitor_photos "  # noqa: S608 — column là hằng số ở trên
            "WHERE id = %s AND status = 'verified' AND is_public",
            (photo_id,),
        ).fetchone()
    return bytes(row[0]) if row else None

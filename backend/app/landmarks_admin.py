"""Admin thêm/sửa/gỡ địa danh cho Săn địa danh Sài Gòn (và tour thuyết minh).

Một "địa danh săn được" = một POI có ``poi_knowledge`` ĐÃ KIỂM CHỨNG với
``content_type`` thuộc `explore.HUNTABLE_CONTENT_TYPES` (xem `app/explore.py`).
Trước đây chỉ thêm được bằng migration; file này cho admin làm trên giao diện:

- **Gắn bài giới thiệu vào POI có sẵn** (``upsert_story``) — dùng cho 24.900 POI
  nhập từ OSM.
- **Tạo địa danh mới chưa có trong dữ liệu** (``create_landmark``) — POI mới
  (``source = 'admin'``) cùng bài giới thiệu trong một transaction. Chặn trùng:
  cùng tên (gần đúng) trong bán kính ``DUPLICATE_RADIUS_METERS`` thì từ chối và
  trả POI đang có, vì dữ liệu từng có hai bản ghi cho cùng một địa đạo
  (migration 0023) và hai bản ghi là hai "địa danh" trong bộ sưu tập.
- **Gỡ** (``delete_story``) — chỉ xoá bài giới thiệu, giữ POI.

Nguyên tắc "không bịa" của module `explore` được giữ: MỌI claim (sự kiện, điều
thú vị) và bản ghi đều phải kèm URL nguồn http(s) — thiếu thì bị từ chối chứ
không lưu với ``verified = false`` rồi lặng lẽ không hiện ở đâu cả. Admin là
người đối chiếu nguồn, nên bản ghi lưu xong là ``verified = true``.

POI tạo mới chưa có embedding và chưa nằm trong chỉ mục OpenSearch: Săn địa danh
và trang chi tiết đọc thẳng Postgres nên dùng được ngay, còn tìm kiếm văn bản
chỉ thấy nó sau lần dựng lại chỉ mục (`python -m app.search.reindex`).
"""

from __future__ import annotations

import json
import logging
from typing import Any

import psycopg

from . import auth, explore, tts
from .auth import AuthUser
from .poi_features import normalize_text

logger = logging.getLogger("nearby-landmarks-admin")

DUPLICATE_RADIUS_METERS = 150
DUPLICATE_MIN_SIMILARITY = 0.5
# Hộp bao Việt Nam: chặn toạ độ gõ nhầm (đảo vĩ độ/kinh độ) rơi ra giữa biển/nước khác.
VIETNAM_LAT = (8.0, 24.0)
VIETNAM_LNG = (102.0, 110.0)


class LandmarkError(ValueError):
    """Lỗi nghiệp vụ có thông báo hiển thị được cho admin."""


class DuplicateLandmarkError(LandmarkError):
    def __init__(self, message: str, existing: dict[str, Any]) -> None:
        super().__init__(message)
        self.existing = existing


def _claims_json(items: list[dict[str, Any]]) -> str:
    return json.dumps(
        [
            {
                "title": item.get("title") or None,
                "description": item["description"].strip(),
                "source": item["source"].strip(),
                "verified": True,
            }
            for item in items
        ],
        ensure_ascii=False,
    )


def _upsert_story(connection: psycopg.Connection, poi_id: str, story: dict[str, Any]) -> None:
    existing = connection.execute(
        "SELECT content_type FROM poi_knowledge WHERE poi_id = %s", (poi_id,)
    ).fetchone()
    if existing and existing["content_type"] not in explore.HUNTABLE_CONTENT_TYPES:
        raise LandmarkError(
            f"Địa điểm này đã có bài giới thiệu loại “{existing['content_type']}” — "
            "không phải loại địa danh săn được nên không ghi đè."
        )
    connection.execute(
        """
        INSERT INTO poi_knowledge (
            poi_id, content_type, intro, specialty, historical_context,
            historical_events, interesting_facts, source, verified
        )
        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, TRUE)
        ON CONFLICT (poi_id) DO UPDATE SET
            content_type = EXCLUDED.content_type,
            intro = EXCLUDED.intro,
            specialty = EXCLUDED.specialty,
            historical_context = EXCLUDED.historical_context,
            historical_events = EXCLUDED.historical_events,
            interesting_facts = EXCLUDED.interesting_facts,
            source = EXCLUDED.source,
            verified = TRUE
        """,
        (
            poi_id,
            story["content_type"],
            story["intro"].strip(),
            (story.get("specialty") or "").strip() or None,
            (story.get("historical_context") or "").strip() or None,
            _claims_json(story.get("historical_events") or []),
            _claims_json(story.get("interesting_facts") or []),
            story["source"].strip(),
        ),
    )


def _landmark_json(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "poiId": row["poi_id"],
        "name": row["name"],
        "category": row["category"],
        "categoryLabel": explore.category_label(row["category"]),
        "address": row["address"],
        "latitude": float(row["latitude"]),
        "longitude": float(row["longitude"]),
        "contentType": row["content_type"],
        "contentTypeLabel": explore.CONTENT_TYPE_LABELS.get(row["content_type"], ""),
        "verified": row["verified"],
        "discoveries": row["discoveries"],
        "updatedAt": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


_LANDMARK_COLUMNS = """
    p.id::text AS poi_id, p.name, p.category, p.address,
    ST_Y(p.location::geometry) AS latitude, ST_X(p.location::geometry) AS longitude,
    k.content_type, k.verified, k.updated_at,
    (SELECT COUNT(*) FROM poi_discoveries d WHERE d.poi_id = p.id)::int AS discoveries
"""


def list_landmarks(
    q: str = "", limit: int = 50, offset: int = 0, database_url: str | None = None
) -> dict[str, Any]:
    """Mọi địa danh săn được, mới sửa trước — kèm số người đã khám phá."""
    needle = normalize_text(q)
    with auth._connect(database_url) as connection:
        rows = connection.execute(
            f"""
            SELECT {_LANDMARK_COLUMNS}, COUNT(*) OVER ()::int AS total
            FROM poi_knowledge k JOIN pois p ON p.id = k.poi_id
            WHERE k.content_type = ANY(%(types)s)
              AND (%(q)s = '' OR position(%(q)s in p.normalized_name) > 0)
            ORDER BY k.updated_at DESC, p.name
            LIMIT %(limit)s OFFSET %(offset)s
            """,
            {"types": list(explore.HUNTABLE_CONTENT_TYPES), "q": needle, "limit": limit, "offset": offset},
        ).fetchall()
    return {
        "landmarks": [_landmark_json(row) for row in rows],
        "total": rows[0]["total"] if rows else 0,
    }


def search_pois(q: str, limit: int = 10, database_url: str | None = None) -> list[dict[str, Any]]:
    """POI theo tên để chọn gắn bài giới thiệu. Gần đúng nhất trước."""
    needle = normalize_text(q)
    if len(needle) < 2:
        return []
    with auth._connect(database_url) as connection:
        rows = connection.execute(
            """
            SELECT p.id::text AS poi_id, p.name, p.category, p.address,
                   ST_Y(p.location::geometry) AS latitude, ST_X(p.location::geometry) AS longitude,
                   k.content_type
            FROM pois p LEFT JOIN poi_knowledge k ON k.poi_id = p.id
            WHERE position(%(q)s in p.normalized_name) > 0
            ORDER BY similarity(p.normalized_name, %(q)s) DESC, p.popularity_score DESC
            LIMIT %(limit)s
            """,
            {"q": needle, "limit": limit},
        ).fetchall()
    return [
        {
            "poiId": row["poi_id"],
            "name": row["name"],
            "category": row["category"],
            "categoryLabel": explore.category_label(row["category"]),
            "address": row["address"],
            "latitude": float(row["latitude"]),
            "longitude": float(row["longitude"]),
            "contentType": row["content_type"],
            "hasStory": row["content_type"] is not None,
            "huntable": row["content_type"] in explore.HUNTABLE_CONTENT_TYPES,
        }
        for row in rows
    ]


def get_landmark(poi_id: str, database_url: str | None = None) -> dict[str, Any] | None:
    """Toàn bộ bài giới thiệu (điền sẵn form sửa). ``None`` nếu không phải địa danh săn được."""
    with auth._connect(database_url) as connection:
        row = connection.execute(
            f"""
            SELECT {_LANDMARK_COLUMNS}, k.intro, k.specialty, k.historical_context,
                   k.historical_events, k.interesting_facts, k.source
            FROM poi_knowledge k JOIN pois p ON p.id = k.poi_id
            WHERE p.id = %s AND k.content_type = ANY(%s)
            """,
            (poi_id, list(explore.HUNTABLE_CONTENT_TYPES)),
        ).fetchone()
    if row is None:
        return None
    return {
        **_landmark_json(row),
        "intro": row["intro"],
        "specialty": row["specialty"],
        "historicalContext": row["historical_context"],
        "historicalEvents": explore.claims(row["historical_events"]),
        "interestingFacts": explore.claims(row["interesting_facts"]),
        "source": row["source"],
    }


def upsert_story(
    actor: AuthUser, poi_id: str, story: dict[str, Any], database_url: str | None = None
) -> dict[str, Any] | None:
    """Gắn/sửa bài giới thiệu của một POI có sẵn. ``None`` khi không có POI đó."""
    with auth._connect(database_url) as connection:
        if connection.execute("SELECT 1 FROM pois WHERE id = %s", (poi_id,)).fetchone() is None:
            return None
        _upsert_story(connection, poi_id, story)
    tts.invalidate(poi_id)  # thuyết minh đã cache là của bài cũ
    logger.info("admin %s lưu địa danh %s", actor.owner_id, poi_id)
    return get_landmark(poi_id, database_url)


def create_landmark(
    actor: AuthUser, request: dict[str, Any], database_url: str | None = None
) -> dict[str, Any]:
    """Tạo POI mới + bài giới thiệu trong một transaction."""
    latitude, longitude = request["latitude"], request["longitude"]
    if not (
        VIETNAM_LAT[0] <= latitude <= VIETNAM_LAT[1] and VIETNAM_LNG[0] <= longitude <= VIETNAM_LNG[1]
    ):
        raise LandmarkError("Toạ độ nằm ngoài Việt Nam — kiểm tra lại vĩ độ/kinh độ có bị đảo không")
    name = request["name"].strip()
    normalized = normalize_text(name)
    if not normalized:
        raise LandmarkError("Tên địa danh không hợp lệ")
    category = request["category"]

    with auth._connect(database_url) as connection:
        with connection.transaction():
            twin = connection.execute(
                """
                SELECT p.id::text AS poi_id, p.name, k.content_type
                FROM pois p LEFT JOIN poi_knowledge k ON k.poi_id = p.id
                WHERE ST_DWithin(p.location, ST_SetSRID(ST_MakePoint(%(lng)s, %(lat)s), 4326)::geography, %(radius)s)
                  AND similarity(p.normalized_name, %(name)s) >= %(min_sim)s
                ORDER BY similarity(p.normalized_name, %(name)s) DESC
                LIMIT 1
                """,
                {
                    "lat": latitude,
                    "lng": longitude,
                    "radius": DUPLICATE_RADIUS_METERS,
                    "name": normalized,
                    "min_sim": DUPLICATE_MIN_SIMILARITY,
                },
            ).fetchone()
            if twin:
                raise DuplicateLandmarkError(
                    f"Đã có “{twin['name']}” ngay tại đó — hãy gắn bài giới thiệu vào địa điểm này thay vì tạo mới.",
                    {"poiId": twin["poi_id"], "name": twin["name"], "hasStory": twin["content_type"] is not None},
                )
            row = connection.execute(
                """
                INSERT INTO pois (
                    id, name, description, category, category_label, address, location,
                    normalized_name, normalized_address, source, source_id
                )
                VALUES (
                    gen_random_uuid(), %(name)s, '', %(category)s, %(label)s, %(address)s,
                    ST_SetSRID(ST_MakePoint(%(lng)s, %(lat)s), 4326)::geography,
                    %(normalized)s, %(normalized_address)s, 'admin', gen_random_uuid()::text
                )
                RETURNING id::text AS id
                """,
                {
                    "name": name,
                    "category": category,
                    "label": explore.category_label(category),
                    "address": (request.get("address") or "").strip(),
                    "lat": latitude,
                    "lng": longitude,
                    "normalized": normalized,
                    "normalized_address": normalize_text(request.get("address")) or None,
                },
            ).fetchone()
            _upsert_story(connection, row["id"], request)
    logger.info("admin %s tạo địa danh mới %s (%s)", actor.owner_id, row["id"], name)
    landmark = get_landmark(row["id"], database_url)
    if landmark is None:  # không thể xảy ra: vừa ghi trong cùng transaction
        raise LandmarkError("Không đọc lại được địa danh vừa tạo")
    return landmark


def delete_story(actor: AuthUser, poi_id: str, database_url: str | None = None) -> bool:
    """Gỡ khỏi Săn địa danh (xoá bài giới thiệu). POI và lượt khám phá cũ được giữ."""
    with auth._connect(database_url) as connection:
        row = connection.execute(
            "DELETE FROM poi_knowledge WHERE poi_id = %s AND content_type = ANY(%s) RETURNING poi_id",
            (poi_id, list(explore.HUNTABLE_CONTENT_TYPES)),
        ).fetchone()
    if row is None:
        return False
    tts.invalidate(poi_id)
    logger.info("admin %s gỡ địa danh %s", actor.owner_id, poi_id)
    return True

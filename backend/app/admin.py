"""Chức năng chỉ dành cho vai trò ``admin``: thống kê, quản lý tài khoản,
kiểm duyệt đánh giá. Mọi route gọi tới đây đều đã qua ``auth.require_admin``.

Hai chốt chặn để admin không tự khoá mình ra ngoài hệ thống:

- Không tự hạ quyền hay tự khoá tài khoản của chính mình.
- Không hạ quyền/khoá admin đang hoạt động CUỐI CÙNG — kiểm trong cùng
  transaction với lệnh UPDATE (``FOR UPDATE``) để hai admin thao tác cùng lúc
  không cùng lọt qua.
"""

from __future__ import annotations

from typing import Any

from . import auth
from .auth import AuthError, AuthUser

_USER_ROW = """
    id::text AS id, username, display_name, role, is_active,
    created_at, updated_at, last_login_at
"""


def _user_json(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "displayName": row["display_name"],
        "role": row["role"],
        "isActive": row["is_active"],
        "createdAt": row["created_at"].isoformat(),
        "lastLoginAt": row["last_login_at"].isoformat() if row["last_login_at"] else None,
        "savedCount": row.get("saved_count", 0),
        "reviewCount": row.get("review_count", 0),
    }


def overview(database_url: str | None = None) -> dict[str, Any]:
    with auth._connect(database_url) as connection:
        row = connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM app_users)::int AS users,
                (SELECT COUNT(*) FROM app_users WHERE role = 'admin')::int AS admins,
                (SELECT COUNT(*) FROM app_users WHERE NOT is_active)::int AS locked,
                (SELECT COUNT(*) FROM app_users
                    WHERE created_at > NOW() - INTERVAL '7 days')::int AS new_users_7d,
                (SELECT COUNT(*) FROM pois)::int AS pois,
                (SELECT COUNT(*) FROM poi_reviews WHERE source = 'user')::int AS reviews,
                (SELECT COUNT(*) FROM poi_reviews WHERE source = 'user'
                    AND created_at > NOW() - INTERVAL '7 days')::int AS reviews_7d,
                (SELECT COUNT(*) FROM saved_places)::int AS saved_places,
                (SELECT COUNT(*) FROM ingestion_events
                    WHERE received_at > NOW() - INTERVAL '24 hours')::int AS events_24h
            """
        ).fetchone()
        details = _overview_details(connection)
    return {
        "users": row["users"],
        "admins": row["admins"],
        "lockedUsers": row["locked"],
        "newUsers7d": row["new_users_7d"],
        "pois": row["pois"],
        "reviews": row["reviews"],
        "reviews7d": row["reviews_7d"],
        "savedPlaces": row["saved_places"],
        "events24h": row["events_24h"],
        **details,
    }


# Số ngày của biểu đồ hoạt động. Ngày tính theo giờ Việt Nam để cột "hôm nay"
# khớp với lịch của người xem, không lệch 7 tiếng theo UTC.
_ACTIVITY_DAYS = 14
_LOCAL_TZ = "Asia/Ho_Chi_Minh"


def _overview_details(connection: Any) -> dict[str, Any]:
    """Phần chi tiết của trang Tổng quan: hoạt động theo ngày, phân loại sự
    kiện, địa điểm được quan tâm, độ phủ dữ liệu POI, phân bố điểm đánh giá.

    Các câu SQL ở đây cố ý không có ký tự phần trăm: psycopg dùng paramstyle
    pyformat nên ký tự đó dễ bị hiểu nhầm là placeholder."""
    people = connection.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM app_users
                WHERE last_login_at > NOW() - INTERVAL '7 days')::int AS active_users_7d,
            (SELECT COUNT(DISTINCT session_id) FROM ingestion_events
                WHERE received_at > NOW() - INTERVAL '24 hours')::int AS sessions_24h,
            (SELECT COUNT(DISTINCT session_id) FROM ingestion_events
                WHERE received_at > NOW() - INTERVAL '7 days')::int AS sessions_7d,
            (SELECT COUNT(*) FROM ingestion_events
                WHERE processing_status IN ('pending', 'queued'))::int AS events_pending,
            (SELECT COUNT(*) FROM ingestion_events
                WHERE processing_status = 'failed')::int AS events_failed,
            (SELECT MAX(received_at) FROM ingestion_events) AS last_event_at
        """
    ).fetchone()

    daily = connection.execute(
        """
        WITH days AS (
            SELECT generate_series(
                (NOW() AT TIME ZONE %(tz)s)::date - (%(days)s - 1),
                (NOW() AT TIME ZONE %(tz)s)::date,
                INTERVAL '1 day'
            )::date AS day
        ),
        counted AS (
            SELECT (received_at AT TIME ZONE %(tz)s)::date AS day,
                   COUNT(*)::int AS events,
                   COUNT(DISTINCT session_id)::int AS sessions,
                   COUNT(*) FILTER (WHERE event_type = 'search')::int AS searches,
                   COUNT(*) FILTER (WHERE event_type = 'navigation_start')::int AS navigations
            FROM ingestion_events
            WHERE received_at >= ((NOW() AT TIME ZONE %(tz)s)::date - (%(days)s - 1))
                                 AT TIME ZONE %(tz)s
            GROUP BY 1
        )
        SELECT days.day, COALESCE(c.events, 0) AS events, COALESCE(c.sessions, 0) AS sessions,
               COALESCE(c.searches, 0) AS searches, COALESCE(c.navigations, 0) AS navigations
        FROM days LEFT JOIN counted c USING (day)
        ORDER BY days.day
        """,
        {"tz": _LOCAL_TZ, "days": _ACTIVITY_DAYS},
    ).fetchall()

    event_types = connection.execute(
        """
        SELECT event_type, COUNT(*)::int AS count
        FROM ingestion_events
        WHERE received_at > NOW() - INTERVAL '7 days'
        GROUP BY 1 ORDER BY 2 DESC
        """
    ).fetchall()

    top_pois = connection.execute(
        """
        SELECT p.id::text AS id, p.name, p.category_label,
               COUNT(*) FILTER (WHERE e.event_type = 'poi_click')::int AS clicks,
               COUNT(*) FILTER (WHERE e.event_type = 'navigation_start')::int AS navigations,
               COUNT(*) FILTER (WHERE e.event_type = 'poi_dwell')::int AS dwells
        FROM ingestion_events e
        JOIN pois p ON p.id::text = e.poi_id
        WHERE e.event_type IN ('poi_click', 'navigation_start', 'poi_dwell')
          AND e.received_at > NOW() - INTERVAL '30 days'
        GROUP BY p.id, p.name, p.category_label
        ORDER BY COUNT(*) DESC, p.name
        LIMIT 8
        """
    ).fetchall()

    categories = connection.execute(
        """
        SELECT category_label AS label, COUNT(*)::int AS count
        FROM pois GROUP BY 1 ORDER BY 2 DESC
        """
    ).fetchall()

    coverage = connection.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM pois WHERE rating IS NOT NULL)::int AS with_rating,
            (SELECT COUNT(*) FROM pois
                WHERE COALESCE(phone, '') <> '' OR COALESCE(website, '') <> '')::int AS with_contact,
            (SELECT COUNT(*) FROM pois WHERE opening_hours <> '{}'::jsonb)::int AS with_hours,
            (SELECT COUNT(DISTINCT poi_id) FROM poi_photos)::int AS with_photos,
            (SELECT COUNT(DISTINCT poi_id) FROM poi_knowledge)::int AS with_knowledge,
            (SELECT COUNT(DISTINCT poi_id) FROM poi_videos)::int AS with_videos,
            (SELECT COUNT(*) FROM pois WHERE sponsored_until > NOW())::int AS sponsored
        """
    ).fetchone()

    ratings = connection.execute(
        """
        SELECT rating, COUNT(*)::int AS count
        FROM poi_reviews WHERE source = 'user'
        GROUP BY 1
        """
    ).fetchall()

    saved_kinds = connection.execute(
        "SELECT kind, COUNT(*)::int AS count FROM saved_places GROUP BY 1"
    ).fetchall()

    recent_users = connection.execute(
        f"""
        SELECT {_USER_ROW} FROM app_users
        ORDER BY created_at DESC
        LIMIT 5
        """
    ).fetchall()

    # Gom các nhóm nhỏ thành "Khác" để biểu đồ không dài vô tận.
    top_categories = [{"label": r["label"], "count": r["count"]} for r in categories[:8]]
    other = sum(r["count"] for r in categories[8:])
    if other:
        top_categories.append({"label": "Khác", "count": other})

    rating_counts = {r["rating"]: r["count"] for r in ratings}
    rating_total = sum(rating_counts.values())
    kind_counts = {r["kind"]: r["count"] for r in saved_kinds}

    return {
        "activeUsers7d": people["active_users_7d"],
        "sessions24h": people["sessions_24h"],
        "sessions7d": people["sessions_7d"],
        "eventsPending": people["events_pending"],
        "eventsFailed": people["events_failed"],
        "lastEventAt": people["last_event_at"].isoformat() if people["last_event_at"] else None,
        "dailyActivity": [
            {
                "date": r["day"].isoformat(),
                "events": r["events"],
                "sessions": r["sessions"],
                "searches": r["searches"],
                "navigations": r["navigations"],
            }
            for r in daily
        ],
        "eventTypes7d": [{"type": r["event_type"], "count": r["count"]} for r in event_types],
        "topPois30d": [
            {
                "id": r["id"],
                "name": r["name"],
                "category": r["category_label"],
                "clicks": r["clicks"],
                "navigations": r["navigations"],
                "dwells": r["dwells"],
            }
            for r in top_pois
        ],
        "poiCategories": top_categories,
        "poiCoverage": {
            "withRating": coverage["with_rating"],
            "withContact": coverage["with_contact"],
            "withHours": coverage["with_hours"],
            "withPhotos": coverage["with_photos"],
            "withKnowledge": coverage["with_knowledge"],
            "withVideos": coverage["with_videos"],
            "sponsored": coverage["sponsored"],
        },
        "ratingDistribution": [
            {"rating": star, "count": rating_counts.get(star, 0)} for star in range(5, 0, -1)
        ],
        "averageRating": (
            round(sum(star * n for star, n in rating_counts.items()) / rating_total, 2)
            if rating_total
            else None
        ),
        "savedByKind": {kind: kind_counts.get(kind, 0) for kind in ("home", "work", "saved")},
        "recentUsers": [_user_json(r) for r in recent_users],
    }


def list_users(
    query: str | None = None, limit: int = 50, offset: int = 0, database_url: str | None = None
) -> dict[str, Any]:
    pattern = f"%{(query or '').strip()}%"
    with auth._connect(database_url) as connection:
        rows = connection.execute(
            f"""
            SELECT {_USER_ROW},
                (SELECT COUNT(*) FROM saved_places s
                    WHERE s.owner_id = 'user:' || u.id::text)::int AS saved_count,
                (SELECT COUNT(*) FROM poi_reviews r
                    WHERE r.user_id = 'user:' || u.id::text AND r.source = 'user')::int AS review_count,
                COUNT(*) OVER ()::int AS total
            FROM app_users u
            WHERE username ILIKE %(p)s OR COALESCE(display_name, '') ILIKE %(p)s
            ORDER BY (role = 'admin') DESC, created_at DESC
            LIMIT %(limit)s OFFSET %(offset)s
            """,
            {"p": pattern, "limit": limit, "offset": offset},
        ).fetchall()
    return {"users": [_user_json(row) for row in rows], "total": rows[0]["total"] if rows else 0}


def update_user(
    actor: AuthUser,
    user_id: str,
    *,
    role: str | None = None,
    is_active: bool | None = None,
    display_name: str | None = None,
    password: str | None = None,
    database_url: str | None = None,
) -> dict[str, Any] | None:
    """Đổi vai trò / khoá-mở khoá / đổi tên hiển thị / đặt lại mật khẩu.
    Trả None nếu không có tài khoản này."""
    if not auth.is_uuid(user_id):
        return None
    if role is not None and role not in auth.ROLES:
        raise AuthError("Vai trò không hợp lệ")
    if password is not None:
        auth.validate_password(password)
    is_self = user_id.lower() == actor.id.lower()
    if is_self and (role == "user" or is_active is False):
        raise AuthError("Không thể tự hạ quyền hoặc tự khoá tài khoản của chính mình")

    with auth._connect(database_url) as connection:
        current = connection.execute(
            "SELECT role, is_active FROM app_users WHERE id = %(id)s::uuid FOR UPDATE",
            {"id": user_id},
        ).fetchone()
        if current is None:
            return None
        loses_admin = current["role"] == "admin" and current["is_active"] and (
            role == "user" or is_active is False
        )
        if loses_admin:
            # Khoá mọi dòng admin đang hoạt động để hai admin không cùng lúc
            # hạ quyền lẫn nhau rồi để hệ thống không còn ai quản trị.
            others = connection.execute(
                """
                SELECT id FROM app_users
                WHERE role = 'admin' AND is_active AND id <> %(id)s::uuid
                FOR UPDATE
                """,
                {"id": user_id},
            ).fetchall()
            if not others:
                raise AuthError("Phải còn ít nhất một quản trị viên đang hoạt động")
        row = connection.execute(
            f"""
            UPDATE app_users SET
                role = COALESCE(%(role)s, role),
                is_active = COALESCE(%(is_active)s, is_active),
                display_name = CASE WHEN %(set_name)s THEN %(display_name)s ELSE display_name END,
                password_hash = COALESCE(%(password_hash)s, password_hash),
                updated_at = NOW()
            WHERE id = %(id)s::uuid
            RETURNING {_USER_ROW}
            """,
            {
                "id": user_id,
                "role": role,
                "is_active": is_active,
                "set_name": display_name is not None,
                "display_name": (display_name or "").strip()[:80] or None,
                "password_hash": auth.hash_password(password) if password is not None else None,
            },
        ).fetchone()
    return _user_json(row)


def list_reviews(limit: int = 50, offset: int = 0, database_url: str | None = None) -> dict[str, Any]:
    with auth._connect(database_url) as connection:
        rows = connection.execute(
            """
            SELECT r.id::text AS id, r.poi_id::text AS poi_id, p.name AS poi_name,
                   r.user_id, r.author_name, r.rating, r.title, r.body,
                   r.created_at, r.updated_at, u.username,
                   COUNT(*) OVER ()::int AS total
            FROM poi_reviews r
            JOIN pois p ON p.id = r.poi_id
            LEFT JOIN app_users u ON r.user_id = 'user:' || u.id::text
            WHERE r.source = 'user'
            ORDER BY r.updated_at DESC
            LIMIT %(limit)s OFFSET %(offset)s
            """,
            {"limit": limit, "offset": offset},
        ).fetchall()
    return {
        "reviews": [
            {
                "id": row["id"],
                "poiId": row["poi_id"],
                "poiName": row["poi_name"],
                "authorName": row["author_name"],
                "username": row["username"],
                "anonymous": row["username"] is None,
                "rating": row["rating"],
                "title": row["title"],
                "body": row["body"],
                "createdAt": row["created_at"].isoformat(),
                "updatedAt": row["updated_at"].isoformat(),
            }
            for row in rows
        ],
        "total": rows[0]["total"] if rows else 0,
    }

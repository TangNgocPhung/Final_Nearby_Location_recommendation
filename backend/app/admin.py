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

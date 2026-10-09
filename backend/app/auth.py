"""Đăng nhập và phân quyền hai vai trò: ``admin`` và ``user``.

Chỉ dùng thư viện chuẩn — không thêm PyJWT/bcrypt vào image:

- Mật khẩu băm bằng PBKDF2-HMAC-SHA256 (``hashlib.pbkdf2_hmac``, chạy trong C),
  muối ngẫu nhiên 16 byte cho mỗi tài khoản. Chuỗi lưu tự mô tả thuật toán và
  số vòng lặp, nên tăng ``PBKDF2_ITERATIONS`` sau này không làm hỏng mật khẩu cũ.
- Token là ``<payload base64url>.<chữ ký HMAC-SHA256 base64url>``, payload chứa
  ``sub`` (id tài khoản) và ``exp``. KHÔNG nhét vai trò vào token rồi tin nó:
  mỗi request cần đăng nhập đọc lại tài khoản từ database, nên hạ quyền hay khoá
  tài khoản có hiệu lực ngay, không phải chờ token hết hạn.

Token gửi qua header ``Authorization: Bearer <token>``, cùng kiểu với
``X-Session-ID`` sẵn có — không dùng cookie nên không phải lo CSRF.

Tạo admin đầu tiên: đặt ``ADMIN_USERNAME``/``ADMIN_PASSWORD`` (API tự tạo lúc
khởi động), hoặc chạy ``python -m app.auth create-admin <tên>``.
"""

from __future__ import annotations

import base64
import getpass
import hashlib
import hmac
import json
import logging
import re
import secrets
import sys
import time
from dataclasses import dataclass
from typing import Any, Literal

import psycopg
from fastapi import Depends, HTTPException, Request
from psycopg.rows import dict_row

from .config import settings

logger = logging.getLogger("nearby-auth")

Role = Literal["admin", "user"]
ROLES: tuple[str, ...] = ("admin", "user")
PBKDF2_ITERATIONS = 260_000
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
MIN_PASSWORD_LENGTH = 8
OWNER_PREFIX = "user:"


class AuthError(ValueError):
    """Lỗi nghiệp vụ có thông báo hiển thị được cho người dùng."""


@dataclass(frozen=True)
class AuthUser:
    id: str
    username: str
    display_name: str | None
    role: Role
    is_active: bool

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def owner_id(self) -> str:
        """Chuỗi chủ sở hữu ghi vào các cột ``owner_id``/``user_id`` kiểu TEXT."""
        return f"{OWNER_PREFIX}{self.id}"

    @property
    def label(self) -> str:
        return self.display_name or self.username

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "displayName": self.display_name,
            "role": self.role,
            "isActive": self.is_active,
        }


# --- Mật khẩu -----------------------------------------------------------------


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str, *, iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt, digest = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), _b64decode(salt), int(iterations)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, _b64decode(digest))


# Băm sẵn một lần để đăng nhập sai TÊN cũng tốn đúng bằng sai MẬT KHẨU — không
# thì đo thời gian phản hồi là dò ra được tên tài khoản nào tồn tại.
_DUMMY_HASH = hash_password(secrets.token_hex(8))


def validate_username(username: str) -> str:
    username = (username or "").strip()
    if not USERNAME_PATTERN.fullmatch(username):
        raise AuthError("Tên đăng nhập 3-32 ký tự, chỉ gồm chữ không dấu, số, '.', '_', '-'")
    return username


def validate_password(password: str) -> str:
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise AuthError(f"Mật khẩu cần ít nhất {MIN_PASSWORD_LENGTH} ký tự")
    if len(password) > 128:
        raise AuthError("Mật khẩu tối đa 128 ký tự")
    return password


def _clean_display_name(display_name: str | None) -> str | None:
    return (display_name or "").strip()[:80] or None


# --- Token --------------------------------------------------------------------


def _sign(payload: bytes, key: bytes) -> str:
    return _b64encode(hmac.new(key, payload, hashlib.sha256).digest())


def issue_token(
    user_id: str, *, now: float | None = None, ttl_hours: int | None = None, key: bytes | None = None
) -> str:
    issued = int(now if now is not None else time.time())
    ttl = (ttl_hours if ttl_hours is not None else settings.auth_token_ttl_hours) * 3600
    payload = json.dumps({"sub": user_id, "iat": issued, "exp": issued + ttl}, separators=(",", ":"))
    body = _b64encode(payload.encode("utf-8"))
    return f"{body}.{_sign(body.encode('ascii'), key or settings.auth_signing_key)}"


def read_token(token: str, *, now: float | None = None, key: bytes | None = None) -> str | None:
    """Trả id tài khoản nếu token đúng chữ ký và còn hạn, ngược lại None."""
    try:
        body, signature = token.split(".")
    except ValueError:
        return None
    expected = _sign(body.encode("ascii", "ignore"), key or settings.auth_signing_key)
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        payload = json.loads(_b64decode(body))
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("sub"), str):
        return None
    if int(payload.get("exp", 0)) < int(now if now is not None else time.time()):
        return None
    return payload["sub"]


def bearer_token(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


# --- Database -----------------------------------------------------------------

_USER_COLUMNS = "id::text AS id, username, display_name, role, is_active"
_UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def is_uuid(value: str | None) -> bool:
    return bool(value and _UUID_PATTERN.fullmatch(value))


def _connect(database_url: str | None = None) -> psycopg.Connection:
    return psycopg.connect(database_url or settings.database_url, row_factory=dict_row)


def _to_user(row: dict[str, Any] | None) -> AuthUser | None:
    if row is None:
        return None
    return AuthUser(
        id=row["id"],
        username=row["username"],
        display_name=row["display_name"],
        role=row["role"],
        is_active=row["is_active"],
    )


def get_user(user_id: str, database_url: str | None = None) -> AuthUser | None:
    if not is_uuid(user_id):
        return None
    with _connect(database_url) as connection:
        row = connection.execute(
            f"SELECT {_USER_COLUMNS} FROM app_users WHERE id = %(id)s::uuid", {"id": user_id}
        ).fetchone()
    return _to_user(row)


def create_user(
    username: str,
    password: str,
    *,
    display_name: str | None = None,
    role: Role = "user",
    database_url: str | None = None,
) -> AuthUser:
    username = validate_username(username)
    validate_password(password)
    if role not in ROLES:
        raise AuthError("Vai trò không hợp lệ")
    with _connect(database_url) as connection:
        try:
            row = connection.execute(
                f"""
                INSERT INTO app_users (username, display_name, password_hash, role)
                VALUES (%(username)s, %(display_name)s, %(password_hash)s, %(role)s)
                RETURNING {_USER_COLUMNS}
                """,
                {
                    "username": username,
                    "display_name": _clean_display_name(display_name),
                    "password_hash": hash_password(password),
                    "role": role,
                },
            ).fetchone()
        except psycopg.errors.UniqueViolation as error:
            raise AuthError("Tên đăng nhập đã có người dùng") from error
    user = _to_user(row)
    assert user is not None
    return user


def authenticate(username: str, password: str, database_url: str | None = None) -> AuthUser:
    """Kiểm tra mật khẩu. Sai tên hay sai mật khẩu đều báo CÙNG một thông báo."""
    with _connect(database_url) as connection:
        row = connection.execute(
            f"SELECT {_USER_COLUMNS}, password_hash FROM app_users WHERE lower(username) = lower(%(u)s)",
            {"u": (username or "").strip()},
        ).fetchone()
        if row is None:
            verify_password(password or "", _DUMMY_HASH)
            raise AuthError("Sai tên đăng nhập hoặc mật khẩu")
        if not verify_password(password or "", row["password_hash"]):
            raise AuthError("Sai tên đăng nhập hoặc mật khẩu")
        if not row["is_active"]:
            raise AuthError("Tài khoản đã bị khoá. Liên hệ quản trị viên.")
        connection.execute(
            "UPDATE app_users SET last_login_at = NOW() WHERE id = %(id)s::uuid", {"id": row["id"]}
        )
    user = _to_user(row)
    assert user is not None
    return user


def change_password(
    user: AuthUser, current_password: str, new_password: str, database_url: str | None = None
) -> None:
    validate_password(new_password)
    with _connect(database_url) as connection:
        row = connection.execute(
            "SELECT password_hash FROM app_users WHERE id = %(id)s::uuid", {"id": user.id}
        ).fetchone()
        if row is None or not verify_password(current_password or "", row["password_hash"]):
            raise AuthError("Mật khẩu hiện tại không đúng")
        connection.execute(
            "UPDATE app_users SET password_hash = %(h)s, updated_at = NOW() WHERE id = %(id)s::uuid",
            {"h": hash_password(new_password), "id": user.id},
        )


def ensure_bootstrap_admin(database_url: str | None = None) -> None:
    """Tạo admin từ ADMIN_USERNAME/ADMIN_PASSWORD nếu tên đó CHƯA tồn tại.

    Gọi lúc API khởi động. Lỗi ở đây (database chưa migrate, chưa sẵn sàng)
    chỉ ghi log — không được làm API không khởi động nổi.
    """
    username, password = settings.admin_username.strip(), settings.admin_password
    if not username or not password:
        return
    try:
        with _connect(database_url) as connection:
            exists = connection.execute(
                "SELECT 1 FROM app_users WHERE lower(username) = lower(%(u)s)", {"u": username}
            ).fetchone()
        if exists:
            return
        create_user(username, password, display_name="Quản trị viên", role="admin", database_url=database_url)
        logger.info("Đã tạo tài khoản admin khởi tạo '%s'", username)
    except Exception as error:  # noqa: BLE001 — khởi động API quan trọng hơn
        logger.warning("Không tạo được admin khởi tạo: %s", error)


# --- FastAPI dependencies -----------------------------------------------------


def optional_user(request: Request) -> AuthUser | None:
    """Tài khoản đang đăng nhập, hoặc None. Token sai/hết hạn coi như chưa đăng
    nhập — endpoint công khai không được hỏng chỉ vì client giữ token cũ."""
    cached = getattr(request.state, "auth_user", False)
    if cached is not False:
        return cached
    token = bearer_token(request)
    user_id = read_token(token) if token else None
    user = get_user(user_id) if user_id else None
    if user is not None and not user.is_active:
        user = None
    request.state.auth_user = user
    return user


def require_user(request: Request) -> AuthUser:
    token = bearer_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Cần đăng nhập")
    user_id = read_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Phiên đăng nhập đã hết hạn, hãy đăng nhập lại")
    user = get_user(user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Tài khoản không còn tồn tại")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Tài khoản đã bị khoá")
    request.state.auth_user = user
    return user


def require_admin(user: AuthUser = Depends(require_user)) -> AuthUser:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Chỉ quản trị viên mới được dùng chức năng này")
    return user


# --- CLI ----------------------------------------------------------------------


def _cli(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] != "create-admin":
        print("Cách dùng: python -m app.auth create-admin <tên đăng nhập>", file=sys.stderr)
        return 2
    password = getpass.getpass("Mật khẩu admin: ")
    if password != getpass.getpass("Nhập lại: "):
        print("Hai lần nhập không khớp", file=sys.stderr)
        return 1
    try:
        user = create_user(argv[1], password, display_name="Quản trị viên", role="admin")
    except AuthError as error:
        print(error, file=sys.stderr)
        return 1
    print(f"Đã tạo admin {user.username} ({user.id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))

"""Địa điểm đã lưu: "Đã lưu", "Nhà", "Chỗ làm".

Chủ sở hữu được định danh bằng ``owner_id`` — hôm nay là ``session_id`` ẩn danh
của trình duyệt, mai là user id thật khi có đăng nhập. Xem docstring migration
``0016_saved_places`` để biết vì sao cột mang tên đó.

Toạ độ KHÔNG nhận từ client khi lưu theo POI: lấy thẳng từ ``pois.location``
trong chính câu lệnh chèn, giống ``geofence.subscribe``. Nhận toạ độ từ giao
diện thì một lỗi phía client sẽ ghim "nhà" của người dùng ở sai chỗ mà không
có gì phát hiện được. Chỉ khi lưu một điểm TỰ DO (thả ghim, không có POI) thì
toạ độ mới đến từ client — lúc đó nó là thứ duy nhất tồn tại.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from .config import settings

logger = logging.getLogger("nearby-saved-places")

DATABASE_URL = settings.database_url

KINDS = ("saved", "home", "work")

# Nhãn mặc định khi người dùng không tự đặt tên. Dùng cho điểm tự do; lưu theo
# POI thì lấy chính tên POI.
DEFAULT_LABELS = {"home": "Nhà", "work": "Chỗ làm", "saved": "Địa điểm đã lưu"}


def is_uuid(value: str | None) -> bool:
    if not value:
        return False
    try:
        UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return True


_SELECT_COLUMNS = """
    id::text AS id,
    poi_id::text AS "poiId",
    kind,
    label,
    address,
    note,
    ST_Y(location::geometry) AS latitude,
    ST_X(location::geometry) AS longitude,
    created_at AS "createdAt",
    updated_at AS "updatedAt"
"""

# Lưu theo POI. Toạ độ/tên/địa chỉ chép từ `pois` NGAY LÚC LƯU, không join lúc
# đọc: POI có thể bị lần nhập OSM sau xoá đi, mà địa điểm người dùng tự tay lưu
# thì không được biến mất theo (migration 0016 dùng ON DELETE SET NULL).
_INSERT_FROM_POI = f"""
    INSERT INTO saved_places (owner_id, poi_id, kind, label, address, location, note)
    SELECT
        %(owner_id)s, p.id, %(kind)s, COALESCE(NULLIF(%(label)s, ''), p.name),
        p.address, p.location, %(note)s
    FROM pois p
    WHERE p.id = %(poi_id)s
    ON CONFLICT (owner_id, poi_id) WHERE poi_id IS NOT NULL
    DO UPDATE SET
        kind = EXCLUDED.kind,
        label = EXCLUDED.label,
        address = EXCLUDED.address,
        location = EXCLUDED.location,
        note = EXCLUDED.note
    RETURNING {_SELECT_COLUMNS}
"""

_INSERT_FREE_POINT = f"""
    INSERT INTO saved_places (owner_id, poi_id, kind, label, address, location, note)
    VALUES (
        %(owner_id)s, NULL, %(kind)s,
        COALESCE(NULLIF(%(label)s, ''), %(default_label)s),
        COALESCE(%(address)s, ''),
        ST_SetSRID(ST_Point(%(longitude)s, %(latitude)s), 4326)::geography,
        %(note)s
    )
    RETURNING {_SELECT_COLUMNS}
"""

# "Đặt làm nhà" lần thứ hai phải THAY chỗ cũ, không tạo thêm. Partial unique
# index `saved_places_owner_kind_idx` là thứ bắt được xung đột này; xoá trước
# rồi chèn thì hai request gửi gần nhau vẫn lọt cả hai.
_REPLACE_KIND = """
    DELETE FROM saved_places
    WHERE owner_id = %(owner_id)s AND kind = %(kind)s AND kind <> 'saved'
"""


def _connect(database_url: str | None = None):
    return psycopg.connect(database_url or DATABASE_URL, row_factory=dict_row)


def save_place(
    owner_id: str,
    *,
    poi_id: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    label: str | None = None,
    address: str | None = None,
    note: str | None = None,
    kind: str = "saved",
    database_url: str | None = None,
) -> dict[str, Any] | None:
    """Lưu một địa điểm. Trả ``None`` khi ``poi_id`` không tồn tại.

    Hai chế độ:

    - Có ``poi_id``: mọi thứ lấy từ bảng ``pois``; lưu lại cùng POI là cập nhật.
    - Không có: phải có ``latitude``/``longitude`` — đây là điểm tự do (thả
      ghim), dùng cho địa chỉ nhà không nằm trong dữ liệu POI.
    """
    if kind not in KINDS:
        raise ValueError(f"kind phải thuộc {KINDS}")
    if not poi_id and (latitude is None or longitude is None):
        raise ValueError("điểm tự do phải có latitude và longitude")

    params: dict[str, Any] = {
        "owner_id": owner_id,
        "kind": kind,
        "label": label,
        "note": note,
    }
    with _connect(database_url) as connection:
        with connection.cursor() as cursor:
            if kind != "saved":
                cursor.execute(_REPLACE_KIND, {"owner_id": owner_id, "kind": kind})
            if poi_id:
                if not is_uuid(poi_id):
                    return None
                cursor.execute(_INSERT_FROM_POI, params | {"poi_id": poi_id})
            else:
                cursor.execute(
                    _INSERT_FREE_POINT,
                    params
                    | {
                        "latitude": latitude,
                        "longitude": longitude,
                        "address": address,
                        "default_label": DEFAULT_LABELS[kind],
                    },
                )
            row = cursor.fetchone()
    return dict(row) if row else None


def list_places(owner_id: str, database_url: str | None = None) -> list[dict[str, Any]]:
    """Địa điểm đã lưu của một chủ sở hữu: Nhà và Chỗ làm luôn đứng đầu."""
    with _connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {_SELECT_COLUMNS}
                FROM saved_places
                WHERE owner_id = %(owner_id)s
                ORDER BY
                    CASE kind WHEN 'home' THEN 0 WHEN 'work' THEN 1 ELSE 2 END,
                    created_at DESC
                """,
                {"owner_id": owner_id},
            )
            return [dict(row) for row in cursor.fetchall()]


def delete_place(owner_id: str, place_id: str, database_url: str | None = None) -> bool:
    """Xoá theo id, LUÔN kèm điều kiện ``owner_id``.

    Thiếu điều kiện đó thì bất kỳ ai đoán được một UUID sẽ xoá được địa điểm
    của người khác — id không phải là bí mật, nó nằm trong response JSON.
    """
    if not is_uuid(place_id):
        return False
    with _connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM saved_places WHERE id = %(id)s AND owner_id = %(owner_id)s",
                {"id": place_id, "owner_id": owner_id},
            )
            return cursor.rowcount > 0


def transfer_owner(
    from_owner: str, to_owner: str, database_url: str | None = None
) -> int:
    """Chuyển địa điểm đã lưu từ phiên ẩn danh sang tài khoản vừa đăng nhập.

    Chưa có đường đăng nhập nào gọi hàm này — nó tồn tại để ghi rõ đường di cư
    đã được tính trước, và để lúc dựng đăng nhập không ai phải nghĩ lại từ đầu.
    Bỏ qua dòng gây trùng (đã lưu cùng POI ở cả hai bên) thay vì đổ lỗi.
    """
    with _connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE saved_places AS s
                SET owner_id = %(to_owner)s
                WHERE s.owner_id = %(from_owner)s
                  AND NOT EXISTS (
                      SELECT 1 FROM saved_places AS t
                      WHERE t.owner_id = %(to_owner)s
                        AND (
                            (t.poi_id IS NOT NULL AND t.poi_id = s.poi_id)
                            OR (s.kind <> 'saved' AND t.kind = s.kind)
                        )
                  )
                """,
                {"from_owner": from_owner, "to_owner": to_owner},
            )
            return cursor.rowcount

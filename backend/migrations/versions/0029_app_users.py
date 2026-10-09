"""Tài khoản đăng nhập và phân quyền admin/user.

Revision ID: 0029_app_users
Revises: 0028_poi_knowledge_landmarks

Trước migration này mọi dữ liệu cá nhân (địa điểm đã lưu, đánh giá) gắn với
`session_id` ẩn danh của trình duyệt. Bảng `app_users` thêm danh tính bền vững:

- `role`: `admin` quản trị người dùng và kiểm duyệt đánh giá; `user` là người
  dùng thường. Đăng ký công khai LUÔN ra `user` — chỉ admin nâng quyền được.
- `is_active = FALSE` là khoá tài khoản: token cũ vẫn đúng chữ ký nhưng bị từ
  chối vì `app/auth.py` đọc lại dòng này ở MỖI request cần đăng nhập.
- `username` duy nhất KHÔNG phân biệt hoa thường (index trên `lower()`), để
  "Admin" và "admin" không thành hai tài khoản trông giống hệt nhau.

Dữ liệu cá nhân trỏ về tài khoản bằng chuỗi `user:<uuid>` trong các cột
`owner_id`/`user_id` kiểu TEXT sẵn có (xem chú thích migration 0016), nên không
phải đổi schema của `saved_places` hay `poi_reviews`.
"""

from alembic import op

revision = "0029_app_users"
down_revision = "0028_poi_knowledge_landmarks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app_users (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            username TEXT NOT NULL CHECK (username ~ '^[A-Za-z0-9_.-]{3,32}$'),
            display_name TEXT,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_login_at TIMESTAMPTZ
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX app_users_username_idx ON app_users (lower(username))")
    op.execute("CREATE INDEX app_users_role_idx ON app_users (role)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app_users")

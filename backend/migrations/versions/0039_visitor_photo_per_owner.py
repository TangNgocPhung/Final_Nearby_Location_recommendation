"""Săn địa danh: chống ảnh trùng THEO TỪNG NGƯỜI CHƠI thay vì toàn cục.

Revision ID: 0039_visitor_photo_per_owner
Revises: 0038_quan_pho_32_seed

Chỉ mục ở 0027 là ``UNIQUE (poi_id, sha256)``: hai người chơi gửi đúng cùng byte
ảnh cho một POI thì người sau bị gắn vào dòng ảnh của người trước — kể cả khi
người trước chọn KHÔNG công khai (người sau thấy thumbnail ảnh riêng đó trong
bộ sưu tập của mình, và được báo ``isPublic`` sai). Mỗi người một dòng ảnh:
chỉ mục mới thêm ``owner_id``. Gửi lại cùng tấm ảnh của CHÍNH MÌNH vẫn là một ảnh.
"""

from alembic import op

revision = "0039_visitor_photo_per_owner"
down_revision = "0038_quan_pho_32_seed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS poi_visitor_photos_dedup_idx")
    op.execute(
        "CREATE UNIQUE INDEX poi_visitor_photos_dedup_idx ON poi_visitor_photos (poi_id, owner_id, sha256)"
    )


def downgrade() -> None:
    # Có thể thất bại nếu đã có hai người cùng gửi một ảnh — khi đó phải gộp tay trước.
    op.execute("DROP INDEX IF EXISTS poi_visitor_photos_dedup_idx")
    op.execute("CREATE UNIQUE INDEX poi_visitor_photos_dedup_idx ON poi_visitor_photos (poi_id, sha256)")

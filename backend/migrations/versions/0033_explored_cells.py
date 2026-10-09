"""Bản đồ sương mù: các ô H3 người dùng đã đi qua.

Revision ID: 0033_explored_cells
Revises: 0032_poi_checkins

Chỉ lưu Ô (H3 r9, cạnh ~170 m) và NGÀY lần đầu tới — không lưu toạ độ, không
lưu giờ, không lưu thứ tự. Đó là chủ ý về riêng tư: lịch sử vị trí thô cho biết
nhà ở đâu, đi làm lúc mấy giờ, đi đường nào; tập ô không thứ tự chỉ cho biết
"đã từng ở khu này". Đủ để vẽ sương mù, không đủ để dựng lại hành trình.

``first_seen_on`` là DATE chứ không phải TIMESTAMPTZ vì cùng lý do — "hôm nay
mở thêm 5 ô" cần ngày, không cần giờ.
"""

from alembic import op

revision = "0033_explored_cells"
down_revision = "0032_poi_checkins"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE explored_cells (
            owner_id TEXT NOT NULL,
            cell TEXT NOT NULL,
            first_seen_on DATE NOT NULL DEFAULT CURRENT_DATE,
            PRIMARY KEY (owner_id, cell)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS explored_cells")

"""Video YouTube gắn vào từng địa điểm — admin dán link, không gọi YouTube API.

Revision ID: 0030_poi_videos
Revises: 0029_app_users

Chỉ lưu ``youtube_id`` (11 ký tự), KHÔNG lưu nguyên URL người dán: cùng một
video có cả chục dạng link (watch?v=, youtu.be/, shorts/, có/không tham số
theo dõi ``si=``...). Chuẩn hoá về id thì ràng buộc ``UNIQUE (poi_id,
youtube_id)`` mới chặn được việc dán trùng một video hai lần dưới hai dạng link.

``start_seconds`` giữ mốc ``t=`` trong link — video dài 20 phút về cả khu phố
mà đoạn nói về địa điểm này nằm ở phút 12 thì mốc đó là toàn bộ giá trị của link.
"""

from alembic import op

revision = "0030_poi_videos"
down_revision = "0029_app_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE poi_videos (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            poi_id UUID NOT NULL REFERENCES pois(id) ON DELETE CASCADE,
            youtube_id TEXT NOT NULL CHECK (youtube_id ~ '^[A-Za-z0-9_-]{11}$'),
            title TEXT,
            start_seconds INT NOT NULL DEFAULT 0 CHECK (start_seconds >= 0),
            sort_order INT NOT NULL DEFAULT 0,
            created_by TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (poi_id, youtube_id)
        )
        """
    )
    op.execute("CREATE INDEX poi_videos_poi_idx ON poi_videos (poi_id, sort_order, created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS poi_videos")

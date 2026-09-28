"""Săn địa danh Sài Gòn: lượt khám phá + ảnh người chơi chụp tại chỗ.

Revision ID: 0027_explore_discoveries
Revises: 0026_poi_verifications

Luồng: tìm POI → đi tới → chụp ảnh → xác nhận → lưu ảnh → mở khoá câu chuyện →
thuyết minh → bộ sưu tập. Xem `app/explore.py`.

Hai bảng tách riêng vì hai thứ có vòng đời khác nhau:

- ``poi_discoveries`` — "người này đã tới địa điểm này", mỗi (chủ sở hữu, POI)
  một dòng. Đây là thứ mở khoá câu chuyện và tính tiến độ bộ sưu tập.
- ``poi_visitor_photos`` — ảnh người chơi chụp. Một người có thể quay lại chụp
  thêm; ảnh là DỮ LIỆU của POI (làm giàu kho ảnh thật), còn lượt khám phá là
  dữ liệu của NGƯỜI CHƠI.

``status`` của ảnh:
- ``verified`` — AI xem ảnh và xác nhận đúng là địa điểm đó. CHỈ ảnh này được
  hiện công khai trong trang chi tiết POI.
- ``pending``  — vị trí đã đúng nhưng AI chưa kết luận được (model không chạy,
  hết thời gian, trả lời "không chắc"). Người chụp vẫn thấy ảnh của mình; người
  khác thì không, cho tới khi được xác minh lại.
Ảnh bị AI bác (rõ ràng không phải địa điểm đó) KHÔNG được lưu: đó là ảnh riêng
của người dùng chụp nhầm/chụp bừa, giữ lại chẳng làm giàu gì cho POI mà thêm
rủi ro riêng tư.

``is_public``: người chơi tự chọn có góp ảnh vào kho ảnh công khai hay không
(ảnh chụp ở địa danh hay có mặt người). Không góp thì ảnh vẫn nằm trong bộ sưu
tập của chính họ, nhưng không bao giờ hiện cho người khác dù đã xác minh.

Ảnh lưu thẳng trong Postgres (BYTEA) thay vì một volume ảnh riêng: ảnh đã được
thu về ≤ 1280 px (vài trăm KB), số lượng nhỏ, và nằm chung database thì backup,
xoá POI (ON DELETE CASCADE) và dựng lại container đều không làm ảnh "mồ côi".
Ảnh được mã hoá lại ở backend nên metadata EXIF (có cả toạ độ GPS nhà riêng nếu
người dùng chọn ảnh cũ) bị loại bỏ trước khi lưu.
"""

from alembic import op

revision = "0027_explore_discoveries"
down_revision = "0026_poi_verifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE poi_visitor_photos (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            poi_id UUID NOT NULL REFERENCES pois(id) ON DELETE CASCADE,
            owner_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('verified', 'pending')),
            is_public BOOLEAN NOT NULL DEFAULT TRUE,
            verdict JSONB NOT NULL DEFAULT '{}'::jsonb,
            distance_meters REAL NOT NULL,
            accuracy_meters REAL,
            image BYTEA NOT NULL,
            thumbnail BYTEA NOT NULL,
            width INTEGER NOT NULL,
            height INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    # Cùng một tấm ảnh gửi lại cho cùng POI (bấm hai lần, gửi lại sau lỗi mạng)
    # là một ảnh, không phải hai.
    op.execute("CREATE UNIQUE INDEX poi_visitor_photos_dedup_idx ON poi_visitor_photos (poi_id, sha256)")
    op.execute(
        "CREATE INDEX poi_visitor_photos_public_idx ON poi_visitor_photos (poi_id, created_at DESC) "
        "WHERE status = 'verified' AND is_public"
    )
    op.execute(
        """
        CREATE TABLE poi_discoveries (
            owner_id TEXT NOT NULL,
            poi_id UUID NOT NULL REFERENCES pois(id) ON DELETE CASCADE,
            photo_id UUID REFERENCES poi_visitor_photos(id) ON DELETE SET NULL,
            distance_meters REAL NOT NULL,
            discovered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (owner_id, poi_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS poi_discoveries")
    op.execute("DROP TABLE IF EXISTS poi_visitor_photos")

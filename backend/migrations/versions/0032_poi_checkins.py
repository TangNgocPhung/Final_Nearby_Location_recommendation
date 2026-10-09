"""Check-in khi khám phá bằng camera (AR): "người này đã đứng tại địa điểm này".

Revision ID: 0032_poi_checkins
Revises: 0031_poi_category_overrides

Khác ``poi_discoveries`` (migration 0027, Săn địa danh): bên đó chỉ nhận địa
danh có câu chuyện đã kiểm chứng và bắt buộc chụp ảnh; check-in AR nhận MỌI POI
và chỉ cần vị trí — đó là thứ đếm huy hiệu ("3 quán cà phê", "10 nơi"). Gộp vào
một bảng thì hoặc Săn địa danh mất điều kiện ảnh, hoặc check-in phải mang theo
cột ảnh luôn rỗng.

Tên/loại/toạ độ CHÉP từ ``pois`` lúc check-in và ``poi_id`` là ON DELETE SET
NULL — cùng lý do với ``saved_places`` (0016): lần nhập OSM sau có thể xoá POI,
mà huy hiệu người dùng đã đi bộ để có thì không được biến mất theo. Vì
``poi_id`` có thể NULL nên khoá chính là ``id`` riêng, còn "mỗi người một lần
mỗi POI" do partial unique index giữ.
"""

from alembic import op

revision = "0032_poi_checkins"
down_revision = "0031_poi_category_overrides"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE poi_checkins (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            owner_id TEXT NOT NULL,
            poi_id UUID REFERENCES pois(id) ON DELETE SET NULL,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            location GEOGRAPHY(Point, 4326) NOT NULL,
            distance_meters REAL NOT NULL,
            accuracy_meters REAL,
            checked_in_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX poi_checkins_owner_poi_idx ON poi_checkins (owner_id, poi_id) "
        "WHERE poi_id IS NOT NULL"
    )
    op.execute("CREATE INDEX poi_checkins_owner_time_idx ON poi_checkins (owner_id, checked_in_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS poi_checkins")

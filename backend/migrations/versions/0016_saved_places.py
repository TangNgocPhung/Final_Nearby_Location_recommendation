"""Địa điểm đã lưu ("Đã lưu" / "Đặt làm nhà").

Revision ID: 0016_saved_places
Revises: 0015_cinema_pois

Ba quyết định thiết kế đáng giải thích, vì cả ba đều là chỗ dễ làm sai theo
cách chỉ lộ ra sau nhiều tháng.

**1. `owner_id TEXT`, không phải `user_id UUID`.** Hệ thống hiện CHƯA có đăng
nhập: thứ duy nhất định danh được người dùng là `session_id` ẩn danh sinh ở
trình duyệt. Nếu đặt tên cột là `user_id` và ràng buộc khoá ngoại tới một bảng
tài khoản chưa tồn tại thì không chèn nổi dòng nào hôm nay; còn nếu đặt
`session_id` thì mai có tài khoản thật lại phải đổi tên cột, sửa mọi câu lệnh
và migrate dữ liệu cũ.

`owner_id` là một chuỗi định danh "chủ sở hữu" — hôm nay chứa session id, mai
chứa user id. Khi dựng xong đăng nhập, việc duy nhất phải làm là UPDATE các
dòng cũ từ session id sang user id của người vừa đăng nhập, không đụng schema.

**2. `poi_id` cho phép NULL và `ON DELETE SET NULL`.** Người dùng phải lưu
được một địa chỉ BẤT KỲ (thả ghim giữa đường, nhà riêng không có trong OSM),
không chỉ POI có sẵn — đó chính là tình huống "lưu địa chỉ nhà".

Quan trọng hơn: `ON DELETE CASCADE` sẽ XOÁ MẤT địa điểm người dùng đã lưu chỉ
vì lần nhập OSM sau đó bỏ POI đó đi (đổi thẻ, gộp trùng, người map xoá nhầm).
Dữ liệu người dùng tự tay lưu không được phép biến mất vì một job nền. Với
`SET NULL`, liên kết tới POI mất nhưng toạ độ, tên và địa chỉ vẫn còn — người
dùng vẫn tìm lại được nhà mình.

Hệ quả: `location`, `label`, `address` được CHÉP vào bảng này lúc lưu chứ
không join sang `pois` mỗi lần đọc. Đây là phi chuẩn hoá có chủ đích, đúng
theo lý do trên.

**3. Một `home` (và một `work`) cho mỗi chủ sở hữu.** Ràng buộc bằng partial
unique index chứ không kiểm ở tầng ứng dụng: hai request "đặt làm nhà" gửi gần
nhau sẽ cùng đọc thấy "chưa có nhà" rồi cùng chèn. Database là chỗ duy nhất
chặn được đua như vậy.
"""

from __future__ import annotations

from alembic import op


revision = "0016_saved_places"
down_revision = "0015_cinema_pois"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE saved_places (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            owner_id TEXT NOT NULL,
            poi_id UUID REFERENCES pois(id) ON DELETE SET NULL,
            kind TEXT NOT NULL DEFAULT 'saved'
                CHECK (kind IN ('saved', 'home', 'work')),
            label TEXT NOT NULL CHECK (length(label) BETWEEN 1 AND 160),
            address TEXT NOT NULL DEFAULT '',
            location GEOGRAPHY(POINT, 4326) NOT NULL,
            note TEXT CHECK (note IS NULL OR length(note) <= 500),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    # Câu đọc chính: "mọi địa điểm của tôi, mới nhất trước".
    op.execute(
        "CREATE INDEX saved_places_owner_idx ON saved_places (owner_id, created_at DESC)"
    )

    # Lưu cùng một POI hai lần phải là CẬP NHẬT, không phải hai dòng. Index này
    # là thứ cho phép `ON CONFLICT` làm việc đó.
    op.execute(
        "CREATE UNIQUE INDEX saved_places_owner_poi_idx ON saved_places (owner_id, poi_id) "
        "WHERE poi_id IS NOT NULL"
    )

    # Mỗi người một nhà, một chỗ làm. `kind = 'saved'` thì không giới hạn.
    op.execute(
        "CREATE UNIQUE INDEX saved_places_owner_kind_idx ON saved_places (owner_id, kind) "
        "WHERE kind <> 'saved'"
    )

    # Để sau này trả lời được "địa điểm đã lưu nào gần tôi nhất".
    op.execute(
        "CREATE INDEX saved_places_location_gist_idx ON saved_places USING GIST (location)"
    )

    # Dùng lại trigger đã có từ migration 0003 thay vì viết hàm thứ hai làm
    # đúng một việc giống hệt.
    op.execute(
        "CREATE TRIGGER saved_places_set_updated_at BEFORE UPDATE ON saved_places "
        "FOR EACH ROW EXECUTE FUNCTION set_pois_updated_at()"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS saved_places")

"""Xác minh địa điểm bằng biển hiệu trong ảnh đường phố (AI đọc chữ).

Revision ID: 0026_poi_verifications
Revises: 0025_poi_knowledge_rematch

Một dòng cho mỗi POI đã được `scripts/verify_storefronts.py` kiểm tra: lấy ảnh
Mapillary nhìn về phía địa điểm, cho model thị giác đọc chữ trên biển hiệu, so
khớp gần đúng với tên POI. Xem `app/storefront.py`.

`status`:
- `verified`   — biển hiệu khớp tên. Giao diện hiện "Đã xác minh bằng ảnh".
- `mismatch`   — ảnh CŨ thấy đúng tên, ảnh MỚI rõ nét ở đúng chỗ lại thấy
                 biển khác. Giao diện cảnh báo "có thể đã đổi chủ/đóng cửa".
- `unreadable` — có ảnh nhưng không đọc được tên (xe che, tối, chữ nhỏ). KHÔNG
                 phải bằng chứng quán đã đóng — giao diện không hiện gì.
- `no_imagery` — quanh đó không có ảnh nhìn về phía quán.

`evidence` giữ MỌI ảnh đã đọc (id ảnh Mapillary, ngày chụp, chữ đọc được, điểm
khớp) để kiểm tra lại và đo độ chính xác cho luận văn. Chỉ lưu id ảnh, không lưu
URL: URL thumbnail của Mapillary có hạn dùng, endpoint lấy URL mới khi cần.
"""

from alembic import op

revision = "0026_poi_verifications"
down_revision = "0025_poi_knowledge_rematch"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE poi_verifications (
            poi_id UUID PRIMARY KEY REFERENCES pois(id) ON DELETE CASCADE,
            status TEXT NOT NULL
                CHECK (status IN ('verified', 'mismatch', 'unreadable', 'no_imagery')),
            score REAL,
            matched_text TEXT,
            evidence_image_id TEXT,
            evidence_captured_at TIMESTAMPTZ,
            evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
            model TEXT,
            checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX poi_verifications_status_idx ON poi_verifications (status)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS poi_verifications")

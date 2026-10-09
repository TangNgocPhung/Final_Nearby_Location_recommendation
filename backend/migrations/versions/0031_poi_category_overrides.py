"""Ghi đè danh mục cho POI mà nguồn (OSM) gắn sai loại.

Revision ID: 0031_poi_category_overrides
Revises: 0030_poi_videos

Đo được thật (2026-10-09): truy vấn "Siêu thị gần nhà" trả "116 Culture
Luxury" đứng đầu — node OSM ``node/11124634717`` gắn ``shop=supermarket``,
và bộ lọc danh mục đọc đúng theo dữ liệu đó. Sửa thẳng trong ``pois`` thì
mất khi dựng DB mới (import OSM chèn lại đúng nhãn sai), nên lưu bản ghi đè
theo ``(source, source_id)`` và để ``poi_import.import_osm_elements`` áp lại
sau mỗi lượt import.

``drop_tags``: giá trị thẻ OSM đã sinh ra danh mục sai. Cột ``pois.tags`` đi
vào trường ``tags`` của OpenSearch (BM25), giữ lại "supermarket" thì kênh
đó vẫn khớp POI với truy vấn siêu thị dù ``category`` đã đổi.

Danh mục ``shop`` ("Cửa hàng" chung, nhãn nhóm "Mua sắm"): không xác minh
được cửa hàng thật bán gì nên không đoán một loại cụ thể — chỉ đưa nó ra khỏi
nhóm siêu thị.

SQL áp ghi đè được chép vào đây thay vì import từ ``app.poi_import`` — cùng
lý do ở 0005: migration phải đứng yên khi code app đổi.
"""

from alembic import op

revision = "0031_poi_category_overrides"
down_revision = "0030_poi_videos"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE poi_category_overrides (
            source TEXT NOT NULL,
            source_id TEXT NOT NULL,
            category TEXT NOT NULL,
            category_label TEXT NOT NULL,
            drop_tags TEXT[] NOT NULL DEFAULT '{}',
            reason TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (source, source_id)
        )
        """
    )
    op.execute(
        """
        INSERT INTO poi_category_overrides (source, source_id, category, category_label, drop_tags, reason)
        VALUES (
            'openstreetmap', 'node/11124634717', 'shop', 'Mua sắm', ARRAY['supermarket'],
            '116 Culture Luxury (116 Nguyễn Thái Bình, Q1): OSM gắn shop=supermarket, lọt vào kết quả "siêu thị".'
        )
        """
    )
    op.execute(
        """
        UPDATE pois AS p SET
            category = o.category,
            category_label = o.category_label,
            tags = ARRAY(SELECT t FROM unnest(p.tags) AS t WHERE t <> ALL(o.drop_tags) ORDER BY t),
            updated_at = NOW()
        FROM poi_source_records AS r
        JOIN poi_category_overrides AS o ON o.source = r.source AND o.source_id = r.source_id
        WHERE r.source_type = 'poi' AND r.canonical_poi_id = p.id
        """
    )


def downgrade() -> None:
    # Không khôi phục nhãn cũ: lượt import OSM kế tiếp cũng không ghi lại
    # category cho POI đã có (xem `poi_import._merge_poi`), nên bỏ bảng là đủ.
    op.execute("DROP TABLE IF EXISTS poi_category_overrides")

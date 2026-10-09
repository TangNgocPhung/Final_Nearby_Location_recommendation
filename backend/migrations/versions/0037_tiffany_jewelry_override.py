"""Tiffany & Co. là tiệm trang sức, không phải tạp hoá.

Revision ID: 0037_tiffany_jewelry_override
Revises: 0036_bus_transit

Node OSM ``node/10904687087`` ("Tiffany & Co. Vietnam", 171 Đồng Khởi, Q1)
gắn ``shop=department_store``. Trước 0035 nó là ``shopping_mall``; sau 0035
(tạp hoá gắn ``department_store`` thành ``convenience``) nó lọt vào kết quả
tìm cửa hàng tiện lợi. Đưa về ``jewelry`` ("Tiệm vàng") — danh mục có sẵn
của ``shop=jewelry`` — qua ``poi_category_overrides`` (0031) để lượt import
OSM sau vẫn giữ. ``drop_tags`` bỏ "department_store" khỏi ``pois.tags`` như
lý do ở 0031.

INSERT ``ON CONFLICT DO NOTHING``: bản ghi này đã được áp tay lên DB dev
trước khi 0036 (của phiên khác) được áp, nên migration phải chạy lại được.

SQL áp ghi đè được chép vào đây thay vì import từ ``app.poi_import`` — cùng
lý do ở 0005: migration phải đứng yên khi code app đổi.
"""

from alembic import op

revision = "0037_tiffany_jewelry_override"
down_revision = "0036_bus_transit"
branch_labels = None
depends_on = None

SOURCE_ID = "node/10904687087"
# Phải là một cặp có trong `poi_features.CATEGORY_MAP` — test kiểm.
CATEGORY = ("jewelry", "Tiệm vàng")


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO poi_category_overrides (source, source_id, category, category_label, drop_tags, reason)
        VALUES (
            'openstreetmap', '{SOURCE_ID}', '{CATEGORY[0]}', '{CATEGORY[1]}', ARRAY['department_store'],
            'Tiffany & Co. Vietnam (171 Đồng Khởi, Q1): OSM gắn shop=department_store, lọt vào kết quả "cửa hàng tiện lợi".'
        )
        ON CONFLICT (source, source_id) DO NOTHING
        """
    )
    op.execute(
        f"""
        UPDATE pois AS p SET
            category = o.category,
            category_label = o.category_label,
            tags = ARRAY(SELECT t FROM unnest(p.tags) AS t WHERE t <> ALL(o.drop_tags) ORDER BY t),
            updated_at = NOW()
        FROM poi_source_records AS r
        JOIN poi_category_overrides AS o ON o.source = r.source AND o.source_id = r.source_id
        WHERE r.source_type = 'poi' AND r.canonical_poi_id = p.id
          AND o.source = 'openstreetmap' AND o.source_id = '{SOURCE_ID}'
        """
    )


def downgrade() -> None:
    # Không khôi phục nhãn cũ — cùng lý do ở 0031.
    op.execute(
        f"DELETE FROM poi_category_overrides WHERE source = 'openstreetmap' AND source_id = '{SOURCE_ID}'"
    )

"""Ghi đè TÊN cho POI mà nguồn (OSM) ghi sai chính tả.

Revision ID: 0034_poi_name_overrides
Revises: 0033_explored_cells

Đo được thật (2026-10-10): câu "Hiến máu ở đâu được" không ra trung tâm hiến
máu gần nhất vì node OSM ``node/4981926121`` ghi tên "Trung Tâm Hiến Múa Nhân
Đạo" — BM25 không bao giờ khớp được chữ "máu", còn kênh vector chỉ thấy nó
ngang ngửa chùa và hội quán.

Cùng lý do với ``poi_category_overrides`` (0031): sửa thẳng trong ``pois`` thì
mất khi dựng DB mới (import OSM chèn lại đúng tên sai), nên lưu theo
``(source, source_id)`` và để ``poi_import.import_osm_elements`` áp lại sau mỗi
lượt import. Bảng riêng thay vì thêm cột vào 0031: bảng đó bắt buộc
``category`` — một bản ghi chỉ sửa tên mà phải chép lại category hiện có thì
sẽ âm thầm ghi đè ngược khi danh mục đổi.

``normalized_name`` lưu sẵn chứ không tính bằng SQL: cách chuẩn hoá thật là
``poi_features.normalize_text`` (bỏ dấu, đ→d, gộp ký tự lạ thành khoảng
trắng), viết lại bằng SQL là thêm một bản sao dễ lệch. Unit test kiểm hai giá
trị khớp nhau cho từng dòng chèn ở đây.

SQL áp ghi đè được chép vào đây thay vì import từ ``app.poi_import`` — cùng
lý do ở 0005: migration phải đứng yên khi code app đổi.
"""

import sqlalchemy as sa
from alembic import op

revision = "0034_poi_name_overrides"
down_revision = "0033_explored_cells"
branch_labels = None
depends_on = None

# (source, source_id, name, normalized_name, reason) — test đọc hằng này.
OVERRIDES = (
    (
        "openstreetmap",
        "node/4981926121",
        "Trung Tâm Hiến Máu Nhân Đạo",
        "trung tam hien mau nhan dao",
        'OSM ghi "Hiến Múa" (sai chính tả): câu "hiến máu" không khớp được BM25.',
    ),
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE poi_name_overrides (
            source TEXT NOT NULL,
            source_id TEXT NOT NULL,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (source, source_id)
        )
        """
    )
    insert = sa.text(
        """
        INSERT INTO poi_name_overrides (source, source_id, name, normalized_name, reason)
        VALUES (:source, :source_id, :name, :normalized_name, :reason)
        """
    )
    connection = op.get_bind()
    for source, source_id, name, normalized_name, reason in OVERRIDES:
        connection.execute(
            insert,
            {
                "source": source,
                "source_id": source_id,
                "name": name,
                "normalized_name": normalized_name,
                "reason": reason,
            },
        )
    # ``updated_at`` mới hơn doc OpenSearch => `reindex --missing-only` thấy POI
    # là "stale" và index lại tên đúng.
    op.execute(
        """
        UPDATE pois AS p SET
            name = o.name,
            normalized_name = o.normalized_name,
            updated_at = NOW()
        FROM poi_source_records AS r
        JOIN poi_name_overrides AS o ON o.source = r.source AND o.source_id = r.source_id
        WHERE r.source_type = 'poi' AND r.canonical_poi_id = p.id
        """
    )


def downgrade() -> None:
    # Không khôi phục tên sai — cùng lý do ở 0031.
    op.execute("DROP TABLE IF EXISTS poi_name_overrides")

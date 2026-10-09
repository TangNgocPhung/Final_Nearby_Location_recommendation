"""Tạp hoá gắn ``shop=department_store`` không phải trung tâm thương mại.

Revision ID: 0035_department_store_not_mall
Revises: 0034_poi_name_overrides

Đo được thật (2026-10-10): OSM ở VN dùng ``shop=department_store`` cho tạp
hoá ("bách hoá" dịch thẳng) — 535 POI mang category ``shopping_mall`` từ thẻ
này, chỉ 10 là bách hoá lớn thật (Lotte Department Store, Parkson,
Takashimaya, Union Square, Vincom Plaza Gò Vấp, "Trung tâm Thương mại Thủ
Đức"). Phần còn lại hiện ảnh bìa TTTM, khớp BM25/danh mục khi tìm "trung tâm
thương mại", và vắng mặt khi tìm cửa hàng tiện lợi.

``poi_features.osm_category`` đã sửa cho lượt import mới, nhưng import không
ghi lại ``category`` cho POI đã có (xem ``poi_import._merge_poi``), nên POI cũ
phải sửa ở đây. Đổi sang ``convenience`` khi POI:

- đang là ``shopping_mall`` và có bản ghi nguồn ``shop=department_store``;
- không có bản ghi nguồn nào mang thẻ ``shop`` khác (vd ``shop=mall`` ở POI
  gộp từ nhiều nguồn);
- tên không chứa dấu hiệu bách hoá lớn (``MARKERS``, bản sao của
  ``poi_features._DEPARTMENT_STORE_MARKERS`` — test kiểm hai bản khớp nhau),
  so trên ``normalized_name`` bỏ khoảng trắng — đúng cách ``is_real_mall``
  chuẩn hoá tên;
- không nằm trong ``poi_category_overrides`` (ghi đè tay thắng mọi suy luận).

``updated_at = NOW()`` để ``reindex --missing-only`` thấy POI là "stale" và
đồng bộ lại doc OpenSearch.

SQL được chép vào đây thay vì import từ ``app`` — cùng lý do ở 0005: migration
phải đứng yên khi code app đổi.
"""

from alembic import op

revision = "0035_department_store_not_mall"
down_revision = "0034_poi_name_overrides"
branch_labels = None
depends_on = None

# Bản sao của `poi_features._DEPARTMENT_STORE_MARKERS` — test đọc hằng này.
MARKERS = (
    "lottedepartmentstore",
    "parkson",
    "takashimaya",
    "unionsquare",
    "trungtamthuongmai",
    "tttm",
    "vincom",
)

_MARKER_REGEX = "(" + "|".join(MARKERS) + ")"


def _retag(from_category: str, to_category: str) -> str:
    return f"""
        UPDATE pois AS p SET
            category = '{to_category}',
            category_label = 'Mua sắm',
            updated_at = NOW()
        WHERE p.category = '{from_category}'
          AND replace(p.normalized_name, ' ', '') !~ '{_MARKER_REGEX}'
          AND EXISTS (
              SELECT 1 FROM poi_source_records AS r
              WHERE r.canonical_poi_id = p.id AND r.source_type = 'poi'
                AND r.raw_payload -> 'tags' ->> 'shop' = 'department_store'
          )
          AND NOT EXISTS (
              SELECT 1 FROM poi_source_records AS r
              WHERE r.canonical_poi_id = p.id AND r.source_type = 'poi'
                AND r.raw_payload -> 'tags' ->> 'shop' <> 'department_store'
          )
          AND NOT EXISTS (
              SELECT 1 FROM poi_source_records AS r
              JOIN poi_category_overrides AS o ON o.source = r.source AND o.source_id = r.source_id
              WHERE r.canonical_poi_id = p.id AND r.source_type = 'poi'
          )
        """


def upgrade() -> None:
    op.execute(_retag("shopping_mall", "convenience"))


def downgrade() -> None:
    # Chỉ trả lại POI mà MỌI bản ghi nguồn đều là `shop=department_store` —
    # cùng điều kiện như upgrade, nên tạp hoá thật (`shop=convenience`) không
    # bị kéo sang TTTM.
    op.execute(_retag("convenience", "shopping_mall"))

"""Đồng bộ toàn bộ POI từ PostGIS sang OpenSearch.

Chạy: ``python -m app.search.reindex`` (tùy chọn ``--recreate`` để xóa và dựng
lại chỉ mục). Đây là "indexing worker" bản batch; PostGIS vẫn là nguồn sự thật,
lệnh này chỉ dựng lại lớp chỉ mục truy xuất.
"""

from __future__ import annotations

import argparse
import logging

import psycopg
from psycopg.rows import dict_row

from ..config import settings
from .client import get_admin_client, is_search_configured
from .index import INDEX_NAME, bulk_actions, ensure_index

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("nearby-search-reindex")

_SELECT_POIS = """
    SELECT
        id::text AS id, name, normalized_name, description, category,
        category_label, tags, brand, district, price_level,
        rating::float8 AS rating, popularity_score,
        ST_Y(location::geometry) AS latitude,
        ST_X(location::geometry) AS longitude,
        h3_r7, h3_r8, h3_r9, embedding, updated_at
    FROM pois
    ORDER BY id
"""


def _iter_pois(database_url: str, batch_size: int):
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.cursor(name="reindex_cursor") as cursor:
            cursor.itersize = batch_size
            cursor.execute(_SELECT_POIS)
            batch: list[dict] = []
            for row in cursor:
                batch.append(dict(row))
                if len(batch) >= batch_size:
                    yield batch
                    batch = []
            if batch:
                yield batch


def reindex(recreate: bool = False, batch_size: int = 500) -> int:
    if not is_search_configured():
        logger.error("OpenSearch chưa được cấu hình (OPENSEARCH_URL rỗng hoặc SEARCH_BACKEND=postgis)")
        return 0
    # Client quản trị: timeout dài, có thử lại. Client truy vấn có timeout 1 giây
    # nên xoá/tạo chỉ mục và bulk index sẽ đổ giữa chừng.
    client = get_admin_client()
    if client is None:
        logger.error("Không tạo được OpenSearch client")
        return 0

    from opensearchpy import helpers

    if recreate:
        # ignore_unavailable: chỉ mục chưa tồn tại không phải lỗi, và tránh
        # kiểm-tra-rồi-xoá vốn có khoảng trống ở giữa.
        logger.info("Xóa chỉ mục cũ %s (nếu có)", INDEX_NAME)
        client.indices.delete(index=INDEX_NAME, ignore_unavailable=True)
    ensure_index(client)

    total = 0
    for batch in _iter_pois(settings.database_url, batch_size):
        actions = bulk_actions(batch)
        if not actions:
            continue
        success, errors = helpers.bulk(client, actions, stats_only=False, raise_on_error=False)
        total += success
        if errors:
            logger.warning("%d document lỗi khi index", len(errors))
    client.indices.refresh(index=INDEX_NAME)
    logger.info("Đã index %d POI vào %s", total, INDEX_NAME)
    return total


def _existing_ids(client: Any) -> set[str]:
    """Toàn bộ ``poi_id`` ĐÃ có trong chỉ mục — dùng cho `reindex_missing` để
    biết POI nào cần bỏ qua (đã có embedding thật, không cần tính lại)."""
    from opensearchpy import helpers

    return {
        hit["_id"]
        for hit in helpers.scan(
            client, index=INDEX_NAME, query={"query": {"match_all": {}}}, _source=False
        )
    }


def reindex_missing(batch_size: int = 500) -> int:
    """Chỉ index những POI CHƯA có trong chỉ mục — không đụng tới POI đã có
    (giữ nguyên embedding thật đã tính từ trước, không gọi lại Ollama cho
    chúng).

    Dùng khi Postgres vừa nhận thêm POI mới (vd một lượt `import_osm_pois`)
    mà không muốn trả giá tính lại embedding cho toàn bộ chỉ mục — đo được
    thật (2026-09-20): một lượt import OSM full-bbox thêm ~15k POI mới trong
    khi ~8.9k POI cũ đã index xong từ trước; `reindex()` (đầy đủ) sẽ gọi lại
    Ollama cho CẢ ~24k, còn hàm này chỉ gọi cho phần mới.
    """
    if not is_search_configured():
        logger.error("OpenSearch chưa được cấu hình (OPENSEARCH_URL rỗng hoặc SEARCH_BACKEND=postgis)")
        return 0
    client = get_admin_client()
    if client is None:
        logger.error("Không tạo được OpenSearch client")
        return 0

    from opensearchpy import helpers

    ensure_index(client)
    existing = _existing_ids(client)
    logger.info("Chỉ mục đã có %d POI, đang tìm phần còn thiếu trong Postgres", len(existing))

    total = 0
    skipped = 0
    for batch in _iter_pois(settings.database_url, batch_size):
        missing = [row for row in batch if row["id"] not in existing]
        skipped += len(batch) - len(missing)
        if not missing:
            continue
        actions = bulk_actions(missing)
        if not actions:
            continue
        success, errors = helpers.bulk(client, actions, stats_only=False, raise_on_error=False)
        total += success
        if errors:
            logger.warning("%d document lỗi khi index", len(errors))
    client.indices.refresh(index=INDEX_NAME)
    logger.info("Đã index %d POI mới, bỏ qua %d POI đã có sẵn", total, skipped)
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="Đồng bộ POI từ PostGIS sang OpenSearch")
    parser.add_argument("--recreate", action="store_true", help="Xóa và dựng lại chỉ mục")
    parser.add_argument(
        "--missing-only",
        action="store_true",
        help="Chỉ index POI chưa có trong chỉ mục, không tính lại embedding cho POI đã có",
    )
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()
    if args.missing_only:
        reindex_missing(batch_size=args.batch_size)
    else:
        reindex(recreate=args.recreate, batch_size=args.batch_size)


if __name__ == "__main__":
    main()

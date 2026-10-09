"""Đồng bộ toàn bộ POI từ PostGIS sang OpenSearch.

Chạy: ``python -m app.search.reindex`` (tùy chọn ``--recreate`` để xóa và dựng
lại chỉ mục, ``--missing-only [--dry-run]`` để chỉ bù phần còn thiếu/cũ). Đây là "indexing worker" bản batch; PostGIS vẫn là nguồn sự thật,
lệnh này chỉ dựng lại lớp chỉ mục truy xuất.
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime
from typing import Any

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


_SELECT_POI_VERSIONS = "SELECT id::text AS id, updated_at FROM pois"

_SELECT_POIS_BY_ID = _SELECT_POIS.replace("ORDER BY id", "WHERE id = ANY(%s::uuid[]) ORDER BY id")


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _index_state(client: Any) -> tuple[dict[str, datetime | None], set[str]]:
    """``updated_at`` của từng doc đang có trong chỉ mục, và tập id doc CHƯA có
    vector. Quét riêng hai lượt để khỏi kéo 1024 số thực của mỗi doc về chỉ
    để biết nó có ``embedding`` hay không."""
    from opensearchpy import helpers

    versions = {
        hit["_id"]: _parse_timestamp((hit.get("_source") or {}).get("updated_at"))
        for hit in helpers.scan(
            client, index=INDEX_NAME, query={"query": {"match_all": {}}}, _source=["updated_at"]
        )
    }
    without_vector = {
        hit["_id"]
        for hit in helpers.scan(
            client,
            index=INDEX_NAME,
            query={"query": {"bool": {"must_not": {"exists": {"field": "embedding"}}}}},
            _source=False,
        )
    }
    return versions, without_vector


def plan_missing(
    db_versions: dict[str, datetime | None],
    indexed_versions: dict[str, datetime | None],
    without_vector: set[str],
) -> dict[str, list[str]]:
    """Chia POI cần (re)index theo lý do; POI không nằm trong kết quả là đã
    đồng bộ, không gọi Ollama lại:

    - ``missing``: chưa có trong chỉ mục.
    - ``no_embedding``: có doc nhưng thiếu vector (Ollama lỗi ở lượt trước).
    - ``stale``: Postgres có ``updated_at`` mới hơn doc (hoặc doc thiếu
      ``updated_at``).
    """
    plan: dict[str, list[str]] = {"missing": [], "no_embedding": [], "stale": []}
    for poi_id, db_updated_at in sorted(db_versions.items()):
        if poi_id not in indexed_versions:
            plan["missing"].append(poi_id)
        elif poi_id in without_vector:
            plan["no_embedding"].append(poi_id)
        else:
            indexed_updated_at = indexed_versions[poi_id]
            if indexed_updated_at is None or (
                db_updated_at is not None and db_updated_at > indexed_updated_at
            ):
                plan["stale"].append(poi_id)
    return plan


def _load_db_versions(database_url: str) -> dict[str, datetime | None]:
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        rows = connection.execute(_SELECT_POI_VERSIONS).fetchall()
    return {row["id"]: row["updated_at"] for row in rows}


def _load_rows(database_url: str, poi_ids: list[str]) -> list[dict]:
    # Mở kết nối ngắn cho từng lô thay vì giữ một cursor suốt vài giờ tính
    # embedding (một transaction treo lâu giữ snapshot, chặn VACUUM).
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        return [dict(row) for row in connection.execute(_SELECT_POIS_BY_ID, (poi_ids,))]


def reindex_missing(batch_size: int = 50, dry_run: bool = False) -> dict[str, int]:
    """Chỉ index POI chưa có trong chỉ mục, doc thiếu vector, hoặc doc cũ hơn
    Postgres — không đụng tới POI đã đồng bộ (giữ nguyên embedding thật đã
    tính, không gọi lại Ollama cho chúng).

    Dùng khi Postgres vừa nhận thêm POI mới (vd một lượt `import_osm_pois`)
    mà không muốn trả giá tính lại embedding cho toàn bộ chỉ mục — đo được
    thật (2026-09-20): một lượt import OSM full-bbox thêm ~15k POI mới trong
    khi ~8.9k POI cũ đã index xong từ trước; `reindex()` (đầy đủ) sẽ gọi lại
    Ollama cho CẢ ~24k, còn hàm này chỉ gọi cho phần cần.

    POI nào Ollama không trả được vector vẫn được ghi (partial update, xem
    `index._bulk_action`) nên không bao giờ làm mất vector cũ; doc mới khi đó
    vắng ``embedding`` và sẽ được lượt chạy sau nhặt lại (``no_embedding``).
    """
    stats = {"indexed": 0, "without_embedding": 0, "errors": 0}
    if not is_search_configured():
        logger.error("OpenSearch chưa được cấu hình (OPENSEARCH_URL rỗng hoặc SEARCH_BACKEND=postgis)")
        return stats
    client = get_admin_client()
    if client is None:
        logger.error("Không tạo được OpenSearch client")
        return stats

    from opensearchpy import helpers

    ensure_index(client)
    indexed_versions, without_vector = _index_state(client)
    db_versions = _load_db_versions(settings.database_url)
    plan = plan_missing(db_versions, indexed_versions, without_vector)
    orphans = len(indexed_versions.keys() - db_versions.keys())
    logger.info(
        "Postgres %d POI, chỉ mục %d doc (%d thiếu vector, %d không còn trong Postgres); "
        "cần index: %d chưa có, %d thiếu vector, %d cũ hơn Postgres",
        len(db_versions), len(indexed_versions), len(without_vector), orphans,
        len(plan["missing"]), len(plan["no_embedding"]), len(plan["stale"]),
    )
    if dry_run:
        return stats

    pending = plan["missing"] + plan["no_embedding"] + plan["stale"]
    failed_ids: list[str] = []
    for offset in range(0, len(pending), batch_size):
        rows = _load_rows(settings.database_url, pending[offset : offset + batch_size])
        actions = bulk_actions(rows)
        failed_ids.extend(action["_id"] for action in actions if action["_op_type"] == "update")
        success, errors = helpers.bulk(client, actions, stats_only=False, raise_on_error=False)
        stats["indexed"] += success
        if errors:
            stats["errors"] += len(errors)
            logger.warning("%d document lỗi khi index, vd: %s", len(errors), errors[0])
        logger.info(
            "Tiến độ %d/%d POI (%d chưa lấy được embedding)",
            min(offset + batch_size, len(pending)), len(pending), len(failed_ids),
        )
    stats["without_embedding"] = len(failed_ids)
    client.indices.refresh(index=INDEX_NAME)
    logger.info(
        "Đã index %d POI, %d lỗi; %d POI chưa lấy được embedding (giữ vector cũ nếu có)%s",
        stats["indexed"], stats["errors"], len(failed_ids),
        f", vd: {', '.join(failed_ids[:20])}" if failed_ids else "",
    )
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Đồng bộ POI từ PostGIS sang OpenSearch")
    parser.add_argument("--recreate", action="store_true", help="Xóa và dựng lại chỉ mục")
    parser.add_argument(
        "--missing-only",
        action="store_true",
        help=(
            "Chỉ index POI chưa có trong chỉ mục, doc thiếu vector hoặc cũ hơn Postgres; "
            "không tính lại embedding cho POI đã đồng bộ"
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Cùng --missing-only: chỉ đếm, không ghi gì"
    )
    parser.add_argument("--batch-size", type=int, default=None)
    args = parser.parse_args()
    if args.missing_only:
        reindex_missing(batch_size=args.batch_size or 50, dry_run=args.dry_run)
    else:
        reindex(recreate=args.recreate, batch_size=args.batch_size or 500)


if __name__ == "__main__":
    main()

"""Đo riêng đóng góp của kênh Vector trước khi bàn tới việc nới `_gate_by_text_
relevance` (xem `search/retrieval.py`).

Ablation (A-E) đo nDCG của CẢ pipeline sau gate — không tách được câu hỏi
"Vector có tìm ra candidate nào BM25 không tìm ra không?" vì gate đã cắt hết
candidate ngoài tập BM25 trước khi tính điểm. Script này gọi thẳng hai kênh,
so tập kết quả trước khi qua gate/RRF, để trả lời đúng câu hỏi đó.

Chạy: python scripts/check_vector_overlap.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.embeddings import semantic_embedding  # noqa: E402
from app.search import query as query_builder  # noqa: E402
from app.search.client import get_client  # noqa: E402
from app.search.retrieval import PER_CHANNEL_SIZE, _search_hits  # noqa: E402

JUDGMENTS_PATH = PROJECT_ROOT / "tests" / "fixtures" / "relevance_judgments.json"
TOP_N = 20  # cắt ở top-N để so sánh — đúng độ sâu candidate pool thực tế hay dùng


def main() -> None:
    cases = json.loads(JUDGMENTS_PATH.read_text(encoding="utf-8"))
    client = get_client()
    if client is None:
        print("Không kết nối được OpenSearch")
        return

    for case in cases:
        query_text = case["query"]
        lat, lon, radius = case["latitude"], case["longitude"], case["radius"]
        judged = set(case.get("relevance", {}))

        bm25_hits = _search_hits(
            client, query_builder.bm25_body(query_text, lat, lon, radius, None, PER_CHANNEL_SIZE)
        )
        bm25_ids = [poi_id for poi_id, _ in bm25_hits[:TOP_N]]

        embedding = semantic_embedding(query_text)
        if embedding is None:
            print(f"[{case.get('group')}] {query_text!r}: KHÔNG lấy được embedding, bỏ qua")
            continue
        vector_hits = _search_hits(
            client, query_builder.vector_body(embedding, lat, lon, radius, None, PER_CHANNEL_SIZE)
        )
        vector_ids = [poi_id for poi_id, _ in vector_hits[:TOP_N]]

        bm25_set = set(bm25_ids)
        vector_set = set(vector_ids)
        overlap = bm25_set & vector_set
        vector_only = vector_set - bm25_set
        vector_only_relevant = vector_only & judged

        print(f"\n[{case.get('group')}] {query_text!r}")
        print(f"  BM25 top{TOP_N}: {len(bm25_set)} | Vector top{TOP_N}: {len(vector_set)}")
        print(f"  overlap: {len(overlap)} ({len(overlap) / max(len(vector_set), 1):.0%} của Vector)")
        print(f"  vector-only: {len(vector_only)}")
        if vector_only:
            print(f"    trong đó nằm trong relevance judgment: {len(vector_only_relevant)}")
            if vector_only_relevant:
                print(f"    -> {sorted(vector_only_relevant)}")


if __name__ == "__main__":
    main()

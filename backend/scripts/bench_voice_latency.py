"""Đo thời gian từng bước của tìm kiếm giọng nói: ``api._voice_search("phở")``
quanh Quận 1 — cùng đường ``rank_pois`` -> ``multi_channel_candidates`` với
/api/v1/search.

    python -m scripts.bench_voice_latency <nhãn> <số lượt> [--unload]

So hai bản code: giải nén ``backend/app`` của từng commit vào thư mục riêng
rồi chạy với ``PYTHONPATH=<thư mục đó>``, xen kẽ trước/sau vài vòng.

- ``--unload``: dỡ bge-m3 khỏi Ollama trước lượt đầu (mô phỏng mô hình nguội).
- Mỗi bước in (bắt đầu -> kết thúc) tính từ đầu lượt và tên thread, để thấy
  bước nào chồng lên nhau.
- Lượt rơi về PostGIS bị bỏ khỏi thống kê: đó là đường khác hẳn, không so được.
- Đừng đo khi job reindex đang chạy: nó chiếm OpenSearch và Ollama, mỗi truy
  vấn mất 4–8 s (đo 2026-10-10).
"""

import json
import statistics
import sys
import threading
import time
import urllib.request

label, runs = sys.argv[1], int(sys.argv[2])
unload = "--unload" in sys.argv

from app import api, embeddings  # noqa: E402
from app.config import settings  # noqa: E402
from app.search import retrieval  # noqa: E402

events: list[tuple[str, float, float, str]] = []
t_run = [0.0]


def record(name, fn):
    def wrapper(*args, **kwargs):
        t0 = time.perf_counter()
        try:
            return fn(*args, **kwargs)
        finally:
            events.append((name, t0 - t_run[0], time.perf_counter() - t_run[0], threading.current_thread().name))

    return wrapper


def channel_of(body):
    query = str(body.get("query"))
    if "'knn'" in query:
        return "os:knn"
    if "multi_match" in query:
        return "os:bm25"
    if "'terms'" in query:
        return "os:h3"
    return "os:geo"


class Proxy:
    def __init__(self, client):
        self._client = client

    def search(self, index, body):
        return record(channel_of(body), self._client.search)(index=index, body=body)


_real_get_client = retrieval.get_client
retrieval.get_client = lambda: Proxy(_real_get_client()) if _real_get_client() is not None else None
embeddings.semantic_embedding = record("embed", embeddings.semantic_embedding)
if hasattr(retrieval, "semantic_embedding"):  # bản cũ gọi thẳng
    retrieval.semantic_embedding = record("embed", retrieval.semantic_embedding)
retrieval.hydrate_candidates = record("hydrate", retrieval.hydrate_candidates)
retrieval._trending_ids = record("trending", retrieval._trending_ids)
retrieval.search_available = record("search_available", retrieval.search_available)
api.parse_location = record("parse_location", api.parse_location)

# Lượt nào rơi về PostGIS thì không so được — ghi lại backend thật của từng lượt.
from app import ranking  # noqa: E402

backend_of_run: list[str] = []
_real_mcc = ranking.multi_channel_candidates


def _mcc(*args, **kwargs):
    if kwargs.get("telemetry") is None and len(args) <= 6:
        kwargs["telemetry"] = {}
    result = _real_mcc(*args, **kwargs)
    telemetry = kwargs.get("telemetry") or (args[6] if len(args) > 6 else None) or {}
    degraded = telemetry.get("degradedChannels")
    backend_of_run.append("postgis" if result is None else f"opensearch degraded={degraded}")
    return result


ranking.multi_channel_candidates = _mcc


def unload_bge_m3():
    body = json.dumps({"model": settings.ollama_embedding_model, "input": "x", "keep_alive": 0}).encode()
    req = urllib.request.Request(
        f"{settings.ollama_url.rstrip('/')}/api/embed", data=body, headers={"Content-Type": "application/json"}
    )
    urllib.request.urlopen(req, timeout=120).read()
    time.sleep(2)
    ps = json.load(urllib.request.urlopen(f"{settings.ollama_url.rstrip('/')}/api/ps", timeout=10))
    print("Ollama đang nạp:", [m["name"] for m in ps.get("models", [])])


if unload:
    unload_bge_m3()

totals = []
postgis_runs = 0
for i in range(runs):
    events.clear()
    backend_of_run.clear()
    t_run[0] = time.perf_counter()
    results = api._voice_search("phở", 10.7757, 106.7009)
    total = time.perf_counter() - t_run[0]
    if any(b == "postgis" for b in backend_of_run) or not backend_of_run:
        postgis_runs += 1
    else:
        totals.append(total)
    names = [r.get("name") for r in results][:5]
    print(f"\n[{label}] lượt {i + 1}: tổng {total * 1000:.0f} ms, {len(results)} kết quả, backend {backend_of_run}, top: {names}")
    for name, start, end, thread in sorted(events, key=lambda e: e[1]):
        print(f"    {name:<17} {start * 1000:7.0f} → {end * 1000:7.0f}  ({(end - start) * 1000:5.0f} ms)  {thread}")
    time.sleep(0.5)

print(f"\n[{label}] {postgis_runs} lượt rơi về PostGIS (bỏ khỏi thống kê)")
steady = totals[1:] or totals
if steady:
    print(
        f"[{label}] lượt OpenSearch đầu {totals[0] * 1000:.0f} ms; các lượt sau (n={len(steady)}) "
        f"median {statistics.median(steady) * 1000:.0f} ms, min {min(steady) * 1000:.0f}, max {max(steady) * 1000:.0f}"
    )

"""Semantic embedding thật qua Ollama (bge-m3) — thay hashing trick cho kênh
Vector của search (lộ trình Phase 13).

Vì sao tách khỏi ``poi_features.text_embedding`` thay vì sửa thẳng hàm đó:
nhiều migration (0015, 0017, 0018, 0019, 0020) đã ĐÓNG BĂNG một bản sao riêng
của thuật toán hashing-v2-64, đúng theo nguyên tắc "migration phải đứng yên
theo thời gian" ghi trong migration 0005. Sửa ``text_embedding`` tại chỗ không
phá các bản sao đó (chúng độc lập), nhưng đổi luôn ý nghĩa của một hàm mà
migration 0003 (duy nhất còn import trực tiếp) từng dùng — coi như viết lại
lịch sử một migration đã áp dụng. An toàn hơn là để ``text_embedding`` (hashing)
nguyên vẹn làm hàm mặc định cho pipeline nhập OSM, còn tầng OpenSearch (nơi
thực sự cần độ chính xác ngữ nghĩa) chuyển hẳn sang module này.

Model 1024 chiều — khác hẳn 64 chiều của hashing — nên KHÔNG thể trộn hai
loại vector trong cùng một trường ``knn_vector`` của OpenSearch. Toàn bộ index
phải build lại bằng module này (xem ``scripts/reindex`` / ``app.search.reindex``),
không có đường "vá dần từng POI".

Ollama hiện CHỈ chạy local (chưa deploy production) — ``settings.ollama_url``
rỗng nghĩa là "chưa cấu hình", và mọi lỗi mạng đều trả ``None`` thay vì raise:
gọi bên phải coi đó là "kênh vector tạm tắt", đúng triết lý graceful-degradation
đã dùng cho OSRM/thời tiết/ảnh trong project này — không được để một dịch vụ
phụ trợ chết làm sập cả tìm kiếm.
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request
from typing import Any

from .config import settings

logger = logging.getLogger("nearby-embeddings")

# bge-m3 (Ollama) xuất vector 1024 chiều — đo được thật qua /api/embed.
EMBEDDING_DIMENSION = 1024
EMBEDDING_MODEL = "bge-m3"

REQUEST_TIMEOUT_SECONDS = 10.0
# Chỉ cho lần nạp sẵn lúc khởi động: nạp bge-m3 từ đĩa mất ~10.6s, vượt
# REQUEST_TIMEOUT_SECONDS. Chạy ở thread nền nên chờ lâu không chặn ai.
WARMUP_TIMEOUT_SECONDS = 120.0


def semantic_embedding(text: str, *, timeout: float = REQUEST_TIMEOUT_SECONDS) -> list[float] | None:
    """Vector ngữ nghĩa cho MỘT chuỗi văn bản, hoặc ``None`` nếu Ollama không
    tới được / model chưa có / văn bản rỗng.

    Dùng CHUNG hàm này cho cả embedding lúc index POI lẫn lúc truy vấn — bắt
    buộc, vì k-NN chỉ so sánh được hai vector cùng một không gian biểu diễn.
    """
    cleaned = text.strip()
    if not cleaned or not settings.ollama_url:
        return None

    body = json.dumps(
        {
            "model": settings.ollama_embedding_model,
            "input": cleaned,
            "keep_alive": settings.ollama_embedding_keep_alive,
        }
    ).encode("utf-8")
    url = f"{settings.ollama_url.rstrip('/')}/api/embed"
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload: dict[str, Any] = json.load(response)
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as error:
        logger.warning("Không lấy được semantic embedding qua Ollama: %s", error)
        return None

    embeddings = payload.get("embeddings")
    if not embeddings or not isinstance(embeddings, list) or not embeddings[0]:
        logger.warning("Ollama trả response không có embeddings: %r", payload)
        return None
    return [float(value) for value in embeddings[0]]


_warmup_lock = threading.Lock()
_warmup_thread: threading.Thread | None = None


def warmup_in_progress() -> bool:
    with _warmup_lock:
        return _warmup_thread is not None and _warmup_thread.is_alive()


def start_warmup() -> bool:
    """Nạp sẵn bge-m3 ở thread nền, để lượt tìm kiếm sau không bị timeout và
    mất kênh vector (chỉ còn BM25 — câu mô tả dài như "chỗ nào yên tĩnh để
    ngồi làm việc" khi đó chỉ ra 1 kết quả).

    Gọi lúc khởi động và mỗi khi `query_embedding` quá hạn. Chỉ một lần nạp
    chạy cùng lúc: mỗi truy vấn hỏng mà mở thêm một thread nữa thì chỉ chồng
    thêm request vào hàng đợi Ollama. Trả về có mở thread mới hay không."""
    global _warmup_thread
    if not settings.ollama_url:
        return False
    with _warmup_lock:
        if _warmup_thread is not None and _warmup_thread.is_alive():
            return False
        _warmup_thread = threading.Thread(
            target=semantic_embedding,
            args=("khởi động",),
            kwargs={"timeout": WARMUP_TIMEOUT_SECONDS},
            name="embedding-warmup",
            daemon=True,
        )
        _warmup_thread.start()
        return True


def query_embedding(text: str) -> list[float] | None:
    """Embedding cho truy vấn NGƯỜI DÙNG: chờ tối đa
    ``settings.ollama_query_embedding_timeout_seconds`` thay vì 10 s.

    Đo 2026-10-10: bge-m3 đã nạp thì embed mất 230–270 ms (1,6 s khi reindex
    tranh Ollama); bge-m3 bị dỡ thì lượt đó mất 11–13 s vì chờ nạp mô hình.
    Thà trả BM25 ngay rồi nạp ở nền cho lượt sau còn hơn bắt người dùng — nhất
    là người khiếm thị đang chờ giọng đọc — ngồi im hơn 10 s.

    Đang nạp ở nền thì bỏ qua luôn, không gọi: request mới cũng chỉ xếp hàng
    sau lần nạp đó và chắc chắn quá hạn. Job reindex không đi qua đây — nó gọi
    thẳng `semantic_embedding` với timeout mặc định.
    """
    if not settings.ollama_url or not text.strip():
        return None
    if warmup_in_progress():
        logger.info("bge-m3 đang được nạp ở nền, bỏ kênh vector lượt này")
        return None
    embedding = semantic_embedding(text, timeout=settings.ollama_query_embedding_timeout_seconds)
    if embedding is None:
        start_warmup()
    return embedding


def available() -> bool:
    """Ollama có đang phục vụ đúng model không. Dùng cho /health và để reindex
    fail sớm, dễ hiểu thay vì lỗi rải rác 8891 lần."""
    return semantic_embedding("kiểm tra kết nối") is not None

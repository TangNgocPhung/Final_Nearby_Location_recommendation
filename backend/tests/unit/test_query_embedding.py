"""Embed cho truy vấn người dùng: timeout ngắn, quá hạn thì nạp bge-m3 ở nền.

Đo 2026-10-10: bge-m3 bị dỡ khỏi Ollama thì một lượt tìm kiếm giọng nói mất
11–13 s, gần hết là chờ nạp mô hình (timeout cũ 10 s)."""

import threading

import pytest

from app import embeddings
from app.config import settings


@pytest.fixture(autouse=True)
def _ollama(monkeypatch):
    monkeypatch.setattr(settings, "ollama_url", "http://ollama.test:11434", raising=False)
    monkeypatch.setattr(settings, "ollama_query_embedding_timeout_seconds", 2.5, raising=False)
    monkeypatch.setattr(embeddings, "_warmup_thread", None)
    yield
    thread = embeddings._warmup_thread
    if thread is not None:
        thread.join(5)


def test_dung_timeout_ngan_cua_config(monkeypatch) -> None:
    calls: list[float] = []

    def fake(text: str, *, timeout: float = embeddings.REQUEST_TIMEOUT_SECONDS):
        calls.append(timeout)
        return [0.5]

    monkeypatch.setattr(embeddings, "semantic_embedding", fake)

    assert embeddings.query_embedding("phở") == [0.5]
    assert calls == [2.5]
    assert embeddings._warmup_thread is None


def test_qua_han_thi_nap_o_nen_voi_timeout_dai(monkeypatch) -> None:
    calls: list[float] = []
    loading = threading.Event()

    def fake(text: str, *, timeout: float = embeddings.REQUEST_TIMEOUT_SECONDS):
        calls.append(timeout)
        if timeout == embeddings.WARMUP_TIMEOUT_SECONDS:
            loading.wait(5)
            return [0.5]
        return None

    monkeypatch.setattr(embeddings, "semantic_embedding", fake)

    assert embeddings.query_embedding("phở") is None
    assert embeddings.warmup_in_progress()
    # Lượt kế tiếp trong lúc đang nạp: bỏ qua ngay, không gọi Ollama thêm.
    assert embeddings.query_embedding("bún bò") is None
    loading.set()
    embeddings._warmup_thread.join(5)

    assert calls == [2.5, embeddings.WARMUP_TIMEOUT_SECONDS]
    assert not embeddings.warmup_in_progress()


def test_chi_mot_luong_nap_cung_luc(monkeypatch) -> None:
    loading = threading.Event()
    calls: list[str] = []

    def fake(text: str, *, timeout: float = embeddings.REQUEST_TIMEOUT_SECONDS):
        calls.append(text)
        loading.wait(5)
        return [0.5]

    monkeypatch.setattr(embeddings, "semantic_embedding", fake)

    assert embeddings.start_warmup() is True
    assert embeddings.start_warmup() is False
    loading.set()
    embeddings._warmup_thread.join(5)

    assert len(calls) == 1
    assert embeddings.start_warmup() is True


def test_chua_cau_hinh_ollama_thi_khong_goi_gi(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ollama_url", "", raising=False)

    def fake(*args, **kwargs):
        raise AssertionError("không được gọi Ollama")

    monkeypatch.setattr(embeddings, "semantic_embedding", fake)

    assert embeddings.query_embedding("phở") is None
    assert embeddings.start_warmup() is False


def test_reindex_van_dung_timeout_mac_dinh() -> None:
    """Chỉ truy vấn tương tác mới bị cắt ngắn; reindex vẫn chờ đủ 10 s."""
    import inspect

    from app.search import index

    assert inspect.signature(embeddings.semantic_embedding).parameters["timeout"].default == 10.0
    assert "query_embedding" not in inspect.getsource(index)

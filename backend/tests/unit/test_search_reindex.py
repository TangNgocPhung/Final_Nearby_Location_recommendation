from datetime import datetime, timedelta, timezone

from app.embeddings import EMBEDDING_DIMENSION
from app.search import index as index_module
from app.search.index import bulk_actions
from app.search.reindex import _parse_timestamp, plan_missing

T0 = datetime(2026, 9, 25, 11, 52, 16, 844540, tzinfo=timezone.utc)


def _row(poi_id="poi-1"):
    return {
        "id": poi_id,
        "name": "Cà Phê Sài Gòn",
        "description": "Quán cà phê",
        "category": "cafe",
        "tags": ["cafe"],
        "latitude": 10.77,
        "longitude": 106.70,
        "updated_at": T0,
    }


def test_doc_co_vector_thi_ghi_de_ca_document(monkeypatch) -> None:
    monkeypatch.setattr(index_module, "semantic_embedding", lambda text: [0.1] * EMBEDDING_DIMENSION)
    [action] = bulk_actions([_row()])

    assert action["_op_type"] == "index"
    assert action["_id"] == "poi-1"
    assert action["_source"]["embedding"] == [0.1] * EMBEDDING_DIMENSION


def test_ollama_loi_thi_partial_update_khong_lam_mat_vector_cu(monkeypatch) -> None:
    """`_op_type: index` thay CẢ document: doc đang có vector mà bị ghi bằng
    document thiếu `embedding` là mất vector. Partial update chỉ gộp các
    trường gửi lên (không có `embedding`) nên vector cũ còn nguyên; với POI
    chưa có trong chỉ mục thì `doc_as_upsert` vẫn tạo doc mới."""
    monkeypatch.setattr(index_module, "semantic_embedding", lambda text: None)
    [action] = bulk_actions([_row()])

    assert action["_op_type"] == "update"
    assert action["doc_as_upsert"] is True
    assert "_source" not in action
    assert "embedding" not in action["doc"]
    assert action["doc"]["poi_id"] == "poi-1"


def test_index_document_le_cung_khong_ghi_de_vector(monkeypatch) -> None:
    calls = []

    class FakeClient:
        def index(self, **kwargs):
            calls.append(("index", kwargs))

        def update(self, **kwargs):
            calls.append(("update", kwargs))

    monkeypatch.setattr(index_module, "semantic_embedding", lambda text: None)
    index_module.index_document(FakeClient(), _row())

    [(method, kwargs)] = calls
    assert method == "update"
    assert kwargs["body"]["doc_as_upsert"] is True
    assert "embedding" not in kwargs["body"]["doc"]


def test_plan_chi_lay_poi_thieu_thieu_vector_hoac_cu_hon_postgres() -> None:
    db = {
        "synced": T0,
        "missing": T0,
        "no-vector": T0,
        "stale": T0 + timedelta(minutes=1),
        "doc-khong-co-updated-at": T0,
        "db-khong-co-updated-at": None,
    }
    indexed = {
        "synced": T0,
        "no-vector": T0,
        "stale": T0,
        "doc-khong-co-updated-at": None,
        "db-khong-co-updated-at": T0,
        "orphan": T0,  # còn trong chỉ mục nhưng đã xoá khỏi Postgres: không đụng tới
    }
    plan = plan_missing(db, indexed, without_vector={"no-vector"})

    assert plan == {
        "missing": ["missing"],
        "no_embedding": ["no-vector"],
        "stale": ["doc-khong-co-updated-at", "stale"],
    }


def test_plan_rong_khi_chi_muc_da_dong_bo() -> None:
    db = {"a": T0, "b": T0}
    assert plan_missing(db, dict(db), without_vector=set()) == {
        "missing": [],
        "no_embedding": [],
        "stale": [],
    }


def test_parse_timestamp_doc_duoc_dinh_dang_opensearch_tra_ve() -> None:
    assert _parse_timestamp("2026-09-25T11:52:16.844540+00:00") == T0
    assert _parse_timestamp("2026-09-25T11:52:16.844540Z") == T0
    assert _parse_timestamp(None) is None
    assert _parse_timestamp("rác") is None

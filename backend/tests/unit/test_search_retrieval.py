import threading
import time

from app.config import settings
from app.search import retrieval
from app.search.client import is_search_configured, reset_client_cache


# --- _gate_by_text_relevance ---------------------------------------------------
#
# Đo được thật (không phải giả định): truy vấn "bệnh viện" trả "Phở Nhà Mình"
# ở rank 0 — không qua BM25/vector, chỉ vì gần + đang trending. Bốn test dưới
# khoá lại đúng hành vi phải có sau khi vá.


def test_gate_bo_candidate_chi_geo_trending_khi_da_co_candidate_khop_chu() -> None:
    # RRF xếp "gan-trending" (chỉ geo+trending) TRƯỚC "lien-quan" (có bm25) —
    # đúng tình huống lỗi đã đo được. Candidate không khớp chữ phải bị bỏ hẳn,
    # không chỉ bị đẩy xuống (danh sách bị độn đủ 50 bằng quán ăn/trường học).
    fused = [("gan-trending", 0.05), ("lien-quan", 0.03)]
    channels = {"bm25": ["lien-quan"], "geo": ["gan-trending", "lien-quan"], "trending": ["gan-trending"]}

    gated = retrieval._gate_by_text_relevance(fused, channels, "benh vien")

    assert [poi_id for poi_id, _ in gated] == ["lien-quan"]


def test_gate_khong_tinh_vector_la_bang_chung_lien_quan() -> None:
    """k-NN luôn trả đủ k hit kể cả khi không liên quan — với truy vấn nêu
    LOẠI địa điểm, candidate chỉ có ở kênh vector (vd. "Công viên" cho "bệnh
    viện") không được giữ."""
    fused = [("cong-vien", 0.06), ("benh-vien", 0.04)]
    channels = {"bm25": ["benh-vien"], "vector": ["cong-vien", "benh-vien"], "geo": ["cong-vien"]}

    gated = retrieval._gate_by_text_relevance(fused, channels, "benh vien")

    assert [poi_id for poi_id, _ in gated] == ["benh-vien"]


def test_gate_bo_sung_vector_cho_truy_van_mo_ta_khi_bm25_khop_it() -> None:
    """Đo 2026-10-08: "chỗ nào yên tĩnh để ngồi làm việc" — BM25 khớp đúng 1
    POI, cổng cũ cắt cả danh sách còn 1. Truy vấn mô tả (không nêu loại) thì
    bổ sung kênh vector, xếp SAU nhóm khớp chữ; geo/trending vẫn bị bỏ."""
    fused = [("vec-a", 0.06), ("gan-trending", 0.05), ("khop-chu", 0.04), ("vec-b", 0.03)]
    channels = {
        "bm25": ["khop-chu"],
        "vector": ["vec-a", "khop-chu", "vec-b"],
        "geo": ["gan-trending"],
        "trending": ["gan-trending"],
    }

    gated = retrieval._gate_by_text_relevance(fused, channels, "chỗ nào yên tĩnh để ngồi làm việc")

    assert [poi_id for poi_id, _ in gated] == ["khop-chu", "vec-a", "vec-b"]


def test_gate_chi_bo_sung_phan_dau_kenh_vector() -> None:
    """Đuôi k-NN phẳng điểm, toàn POI tên chung chung ("Bãi đỗ xe" x13) — chỉ
    lấy MAX_SEMANTIC_BACKFILL hit đầu của kênh vector."""
    vector = ["khop-chu"] + [f"v{i}" for i in range(30)]
    fused = [("khop-chu", 1.0)] + [(poi_id, 0.5) for poi_id in reversed(vector[1:])]
    channels = {"bm25": ["khop-chu"], "vector": vector}

    gated = retrieval._gate_by_text_relevance(fused, channels, "yên tĩnh làm việc")

    kept = {poi_id for poi_id, _ in gated[1:]}
    assert kept == set(vector[1 : retrieval.MAX_SEMANTIC_BACKFILL])


def test_gate_khong_bo_sung_vector_khi_bm25_da_khop_du() -> None:
    fused = [(f"p{i}", 1.0 - i / 10) for i in range(7)]
    channels = {"bm25": [f"p{i}" for i in range(5)], "vector": ["p5", "p6"]}

    gated = retrieval._gate_by_text_relevance(fused, channels, "yên tĩnh làm việc")

    assert [poi_id for poi_id, _ in gated] == [f"p{i}" for i in range(5)]


def test_gate_giu_nguyen_thu_tu_rrf_trong_nhom_khop_chu() -> None:
    fused = [("b", 0.5), ("a", 0.4), ("d", 0.3), ("c", 0.2)]
    channels = {"bm25": ["a", "b"], "geo": ["c", "d"]}

    gated = retrieval._gate_by_text_relevance(fused, channels, "ca phe")

    assert [poi_id for poi_id, _ in gated] == ["b", "a"]


def test_gate_khong_ap_dung_khi_khong_co_query_text() -> None:
    """Duyệt theo vị trí thuần (không gõ chữ) — geo là kênh chính đáng, không gate."""
    fused = [("gan-trending", 0.05), ("lien-quan", 0.03)]
    channels = {"bm25": ["lien-quan"], "geo": ["gan-trending", "lien-quan"]}

    gated = retrieval._gate_by_text_relevance(fused, channels, "")

    assert gated == fused


def test_gate_khong_doi_gi_khi_khong_co_candidate_lien_quan() -> None:
    """BM25/vector không trả candidate nào (chỉ trending/geo) — không có gì để
    ưu tiên, giữ nguyên thứ tự RRF thay vì đẩy hết vào "supplementary"."""
    fused = [("gan-trending", 0.05), ("khac", 0.03)]
    channels = {"bm25": [], "geo": ["gan-trending", "khac"]}

    gated = retrieval._gate_by_text_relevance(fused, channels, "mot truy van hiem")

    assert gated == fused


def test_gate_chi_giu_dau_kenh_vector_khi_bm25_rong() -> None:
    """Đo 2026-10-09: câu dài "Tôi muốn kiếm 1 quán cà phê yên tĩnh để học bài"
    làm BM25 rỗng (minimum_should_match 70%), cổng cũ trả nguyên RRF → tiệm
    hoa, sân bóng, trường tiểu học (gần + trending) đứng trên quán cà phê."""
    fused = [("tiem-hoa", 0.06), ("truong-hoc", 0.05), ("ca-phe", 0.04)]
    channels = {
        "bm25": [],
        "vector": ["ca-phe"],
        "geo": ["tiem-hoa", "truong-hoc", "ca-phe"],
        "trending": ["tiem-hoa"],
    }

    gated = retrieval._gate_by_text_relevance(
        fused, channels, "Tôi muốn kiếm 1 quán cà phê yên tĩnh để học bài"
    )

    assert [poi_id for poi_id, _ in gated] == ["ca-phe"]


# --- Ngưỡng nền của kênh vector (đo 2026-10-10 tại 10.7604, 106.6516, 3 km) ----

# "Hiến máu ở đâu được", điểm cosinesimil thật: hai nơi hiến máu, rồi một dãy
# hội quán/nhà thờ/chùa sát nhau, nền (hạng 20) 0.7295.
HIEN_MAU = [
    ("hien-mau", 0.7977), ("truyen-mau", 0.7692), ("ha-chuong", 0.7443), ("mercy", 0.7412),
    ("nghia-nhuan", 0.7401), ("khiet-tam", 0.7366), ("cho-thuoc", 0.7351), ("dong-tu", 0.7351),
    ("ho-le", 0.7348), ("phuoc-kien", 0.7330),
] + [(f"chua-{i}", 0.7328 - i * 0.0003) for i in range(9)] + [("nen", 0.7295)] + [
    (f"duoi-{i}", 0.72 - i * 0.001) for i in range(30)
]
# "Tôi muốn kiếm 1 quán cà phê yên tĩnh để học bài": 15 hit đầu đều là quán cà
# phê, điểm phẳng (hạng 10 chỉ kém hạng 1 0.024), nền 0.7958.
CA_PHE = [
    ("tea-time", 0.8257), ("hello", 0.8166), ("ka-tea", 0.8160), ("like", 0.8144), ("coffee-4", 0.8142),
    ("got", 0.8131), ("nho-kafe", 0.8117), ("ban", 0.8071), ("ranh", 0.8035), ("nanbiri", 0.8016),
] + [(f"cafe-{i}", 0.8005 - i * 0.0005) for i in range(9)] + [("nen", 0.7958)] + [
    (f"duoi-{i}", 0.79 - i * 0.001) for i in range(30)
]


def _vector_channel(hits):
    ids = [poi_id for poi_id, _ in hits]
    return ids, dict(hits)


def _rrf_order(ids):
    return [(poi_id, 1.0 / (60 + rank)) for rank, poi_id in enumerate(ids)]


def test_gate_bm25_rong_chi_giu_hit_vector_noi_len_khoi_nen() -> None:
    """Bản cũ nhận mù 10 hit đầu nên "Hiến máu ở đâu được" ra Hội quán Hà
    Chương, Chùa Tuyền Lâm. Giờ chỉ giữ hit vượt nền ít nhất nửa khoảng nền→đầu."""
    ids, scores = _vector_channel(HIEN_MAU)

    gated = retrieval._gate_by_text_relevance(
        _rrf_order(ids), {"bm25": [], "vector": ids}, "Hiến máu ở đâu được", scores
    )

    assert [poi_id for poi_id, _ in gated] == ["hien-mau", "truyen-mau"]


def test_gate_bm25_rong_van_giu_nhieu_quan_ca_phe() -> None:
    """Lý do bổ sung vector tồn tại (đo 2026-10-09): câu dài làm BM25 rỗng mà
    đầu kênh vector toàn quán cà phê — ngưỡng nền không được cắt mất chúng chỉ
    vì điểm phẳng."""
    ids, scores = _vector_channel(CA_PHE)

    gated = retrieval._gate_by_text_relevance(
        _rrf_order(ids), {"bm25": [], "vector": ids}, "Tôi muốn kiếm 1 quán cà phê yên tĩnh để học bài", scores
    )

    assert [poi_id for poi_id, _ in gated] == ids[:7]


def test_gate_bo_sung_vector_khi_bm25_khop_it_cung_qua_nguong_nen() -> None:
    """BM25 "Hiến máu" (đã bỏ từ đệm) khớp đúng trung tâm hiến máu; bổ sung từ
    vector chỉ thêm Truyền máu Huyết học, không thêm chùa/hội quán."""
    ids, scores = _vector_channel(HIEN_MAU)
    channels = {"bm25": ["hien-mau"], "vector": ids, "geo": ["ha-chuong"]}

    gated = retrieval._gate_by_text_relevance(_rrf_order(ids), channels, "Hiến máu", scores)

    assert [poi_id for poi_id, _ in gated] == ["hien-mau", "truyen-mau"]


def test_gate_khong_bo_sung_khi_vector_khong_xac_nhan_bm25() -> None:
    """Đo 2026-10-10: "hien mau o dau" (không dấu) — BM25 khớp đúng trung tâm
    hiến máu, nhưng đầu kênh vector là tiệm làm đẹp, tiệm giày và không có POI
    khớp chữ nào. Vector không thấy cái BM25 thấy thì không bổ sung."""
    rac = [("hoa-beauty", 0.7756), ("may-beauty", 0.7660), ("mit", 0.7604), ("hai-lua", 0.7596)]
    ids, scores = _vector_channel(rac + [(f"x{i}", 0.75 - i * 0.001) for i in range(30)])
    fused = [("hien-mau", 0.05)] + [(poi_id, 0.04) for poi_id in ids]

    gated = retrieval._gate_by_text_relevance(fused, {"bm25": ["hien-mau"], "vector": ids}, "hien mau", scores)

    assert [poi_id for poi_id, _ in gated] == ["hien-mau"]


def test_semantic_head_khong_ap_nguong_khi_kenh_vector_thua() -> None:
    """Vùng thưa: kênh vector trả ít hơn SEMANTIC_FLOOR_RANK hit — không có nền
    để so, giữ phần đầu như cũ."""
    ids, scores = _vector_channel([("a", 0.9), ("b", 0.7), ("c", 0.6)])

    assert retrieval._semantic_head({"vector": ids}, scores) == ["a", "b", "c"]


def test_multi_channel_embedding_cau_nguyen_van_khi_co_semantic_text(monkeypatch) -> None:
    """BM25 nhận câu đã bỏ từ đệm, kênh vector nhận câu nguyên văn."""
    bm25_texts: list[str] = []
    embedded: list[str] = []

    def fake_bm25_body(text, *args):
        bm25_texts.append(text)
        return {"channel": "bm25"}

    def fake_embedding(text):
        embedded.append(text)
        return [0.1]

    monkeypatch.setattr(retrieval, "search_available", lambda: True)
    monkeypatch.setattr(retrieval, "get_client", lambda: object())
    monkeypatch.setattr(retrieval.query_builder, "bm25_body", fake_bm25_body)
    monkeypatch.setattr(retrieval.query_builder, "vector_body", lambda *args: {"channel": "vector"})
    monkeypatch.setattr(retrieval, "semantic_embedding", fake_embedding)
    monkeypatch.setattr(retrieval, "_search_hits", lambda client, body: [("p1", 1.0)])
    monkeypatch.setattr(retrieval, "_spatial_channels", lambda *args: ({"geo": ["p1"]}, {}))
    monkeypatch.setattr(retrieval, "_trending_ids", lambda *args: [])
    monkeypatch.setattr(retrieval, "hydrate_candidates", lambda ranked, *args, **kwargs: [{"id": ranked[0][0]}])
    monkeypatch.setattr(settings, "opensearch_knn_enabled", True, raising=False)

    result = retrieval.multi_channel_candidates(
        10.7604, 106.6516, 3000, "Hiến máu", None, 100, semantic_text="Hiến máu ở đâu được"
    )

    assert result == [{"id": "p1"}]
    assert bm25_texts == ["Hiến máu"]
    assert embedded == ["Hiến máu ở đâu được"]


def test_multi_channel_returns_none_when_not_configured(monkeypatch) -> None:
    monkeypatch.setattr(settings, "opensearch_url", "", raising=False)
    reset_client_cache()

    result = retrieval.multi_channel_candidates(10.77, 106.70, 3000, "cà phê", None, 100)

    assert result is None


def test_multi_channel_returns_none_when_backend_forced_postgis(monkeypatch) -> None:
    monkeypatch.setattr(settings, "search_backend", "postgis", raising=False)
    monkeypatch.setattr(settings, "opensearch_url", "http://localhost:9200", raising=False)
    reset_client_cache()

    assert is_search_configured() is False
    assert retrieval.multi_channel_candidates(10.0, 106.0, 1000, None, None, 50) is None


def test_multi_channel_falls_back_when_cluster_unreachable(monkeypatch) -> None:
    # Cấu hình trỏ tới cổng không có ai lắng nghe -> ping fail -> None (fallback).
    monkeypatch.setattr(settings, "search_backend", "auto", raising=False)
    monkeypatch.setattr(settings, "opensearch_url", "http://127.0.0.1:1", raising=False)
    reset_client_cache()

    assert retrieval.multi_channel_candidates(10.0, 106.0, 1000, "phở", None, 50) is None

    reset_client_cache()


# --- Hit BM25 chỉ khớp nhờ gộp nhầm dấu ------------------------------------------
#
# Đo 2026-10-10 (chế độ giọng nói, "quán phở" quanh 10.7757, 106.7009): BM25
# trả 11 quán phở rồi tới "Nhà Hát Thành Phố", "Bảo tàng Thành phố"… vì
# vi_folded biến cả "phở" lẫn "phố" thành "pho". Diversify kéo ngay POI khác
# loại đầu tiên lên sau hai quán phở → "Nhà Hát Thành Phố" đứng hạng 3.


def _hit(poi_id: str, name: str, label: str = "Ăn uống", tags: list[str] | None = None) -> dict:
    return {
        "_score": 1.0,
        "_source": {"poi_id": poi_id, "name": name, "category_label": label, "tags": tags or []},
    }


def _bm25_response() -> dict:
    return {
        "hits": {
            "hits": [
                _hit("pho-nha-minh", "Phở Nhà Mình", tags=["restaurant"]),
                _hit("pho-hien", "Pho Hien", tags=["restaurant"]),
                _hit("nha-hat", "Nhà Hát Thành Phố", "Ga tàu"),
                _hit("bao-tang", "Bảo tàng Thành phố", "Văn hóa", ["museum"]),
                _hit("phong-kham", "Trung Tâm Y Tế Dự Phòng - Phòng Khám", "Y tế", ["hospital"]),
            ]
        }
    }


def test_bm25_bo_hit_pho_khop_nham_pho() -> None:
    filtered = retrieval._drop_mark_collisions(_bm25_response(), "phở")

    ids = [poi_id for poi_id, _ in retrieval.query_builder.extract_ranked_hits(filtered)]
    assert ids == ["pho-nha-minh", "pho-hien"]


def test_bm25_khong_loc_khi_go_khong_dau() -> None:
    response = _bm25_response()

    assert retrieval._drop_mark_collisions(response, "pho") is response


def test_bm25_giu_nguyen_khi_loc_het() -> None:
    """Gõ sai dấu ("phơ") thì không hit nào khớp đúng dấu — khớp nhờ bỏ dấu
    vẫn hơn trả rỗng. ("Pho Hien" không dấu thì vẫn khớp nên bỏ khỏi đây.)"""
    response = _bm25_response()
    response["hits"]["hits"] = [
        hit for hit in response["hits"]["hits"] if hit["_source"]["poi_id"] != "pho-hien"
    ]

    assert retrieval._drop_mark_collisions(response, "phơ") is response


class _Bm25OnlyClient:
    def __init__(self) -> None:
        self.bodies: list[dict] = []

    def search(self, index: str, body: dict) -> dict:
        self.bodies.append(body)
        if "multi_match" in str(body["query"]):
            return _bm25_response()
        # Kênh không gian: mọi POI, cái khớp nhầm dấu ở gần nhất.
        ids = ["nha-hat", "bao-tang", "phong-kham", "pho-nha-minh", "pho-hien"]
        return {"hits": {"hits": [{"_source": {"poi_id": poi_id}, "_score": None} for poi_id in ids]}}


def test_multi_channel_khong_dua_poi_khop_nham_dau_vao_ung_vien(monkeypatch) -> None:
    client = _Bm25OnlyClient()
    hydrated: dict = {}

    def fake_hydrate(ranked, *args, **kwargs):
        hydrated["ids"] = [poi_id for poi_id, _ in ranked]
        hydrated["bm25"] = kwargs["bm25_scores"]
        return []

    monkeypatch.setattr(retrieval, "search_available", lambda: True)
    monkeypatch.setattr(retrieval, "get_client", lambda: client)
    monkeypatch.setattr(retrieval, "_trending_ids", lambda *args: [])
    monkeypatch.setattr(retrieval, "hydrate_candidates", fake_hydrate)
    monkeypatch.setattr(settings, "opensearch_knn_enabled", False, raising=False)

    retrieval.multi_channel_candidates(10.7757, 106.7009, 2000, "phở", None, 100)

    assert sorted(hydrated["ids"]) == ["pho-hien", "pho-nha-minh"]
    assert set(hydrated["bm25"]) == {"pho-hien", "pho-nha-minh"}
    bm25_body = next(body for body in client.bodies if "multi_match" in str(body["query"]))
    assert {"name", "tags", "search_keywords"} <= set(bm25_body["_source"])


# --- Chạy song song các kênh ---------------------------------------------------
#
# Đo 2026-10-10 (voice "phở", Quận 1): BM25 ~200 ms, embed ~250 ms, k-NN
# ~450 ms, geo ~250 ms, h3 ~250 ms chạy TUẦN TỰ — riêng phần truy xuất đã
# ~1,4 s. Các kênh không phụ thuộc nhau nên phải chạy cùng lúc.


def _channel_of(body: dict) -> str:
    query = str(body["query"])
    if "'knn'" in query:
        return "vector"
    if "multi_match" in query:
        return "bm25"
    if "'terms'" in query:
        return "h3"
    return "geo"


class _ParallelClient:
    """Mỗi truy vấn đứng chờ ở một barrier đủ 4 bên (bm25, vector, geo, h3):
    chạy tuần tự thì truy vấn đầu tiên không bao giờ qua được barrier."""

    def __init__(self, parties: int = 4, fail: str | None = None) -> None:
        self.barrier = threading.Barrier(parties, timeout=5)
        self.fail = fail
        self.channels: list[str] = []

    def search(self, index: str, body: dict) -> dict:
        channel = _channel_of(body)
        self.channels.append(channel)
        if channel == self.fail:
            raise RuntimeError(f"{channel} hỏng")
        self.barrier.wait()
        return {"hits": {"hits": [{"_source": {"poi_id": f"{channel}-1"}, "_score": 1.0}]}}


def _wire(monkeypatch, client, embedding=lambda text: [0.1, 0.2]) -> dict:
    captured: dict = {}

    def fake_hydrate(ranked, *args, **kwargs):
        captured["ids"] = [poi_id for poi_id, _ in ranked]
        captured["channels"] = kwargs["channels"]
        return [{"id": poi_id} for poi_id, _ in ranked]

    monkeypatch.setattr(retrieval, "search_available", lambda: True)
    monkeypatch.setattr(retrieval, "get_client", lambda: client)
    monkeypatch.setattr(retrieval, "_trending_ids", lambda *args: [])
    monkeypatch.setattr(retrieval, "hydrate_candidates", fake_hydrate)
    monkeypatch.setattr(retrieval, "query_embedding", embedding)
    monkeypatch.setattr(settings, "opensearch_knn_enabled", True, raising=False)
    monkeypatch.setattr(settings, "geo_channel", "both", raising=False)
    return captured


def test_cac_kenh_chay_song_song(monkeypatch) -> None:
    client = _ParallelClient()
    _wire(monkeypatch, client)
    telemetry: dict = {}

    result = retrieval.multi_channel_candidates(
        10.7757, 106.7009, 2000, "phở", None, 100, telemetry=telemetry
    )

    assert result is not None
    assert sorted(client.channels) == ["bm25", "geo", "h3", "vector"]
    assert telemetry["channelsUsed"] == ["bm25", "geo", "h3", "vector"]
    assert telemetry["degradedChannels"] is None


def test_embed_qua_han_chi_bo_kenh_vector(monkeypatch) -> None:
    """bge-m3 chưa nạp → `query_embedding` trả None sau timeout ngắn. Truy vấn
    vẫn đi OpenSearch với 3 kênh còn lại, và việc mất kênh phải hiện ra."""
    client = _ParallelClient(parties=3)
    captured = _wire(monkeypatch, client, embedding=lambda text: None)
    telemetry: dict = {}

    result = retrieval.multi_channel_candidates(
        10.7757, 106.7009, 2000, "phở", None, 100, telemetry=telemetry
    )

    assert result is not None
    assert "vector" not in client.channels
    assert telemetry["channelsUsed"] == ["bm25", "geo", "h3"]
    assert telemetry["degradedChannels"] == ["vector"]
    assert captured["ids"] == ["bm25-1"]


def test_knn_loi_chi_bo_kenh_vector(monkeypatch) -> None:
    client = _ParallelClient(parties=3, fail="vector")
    _wire(monkeypatch, client)
    telemetry: dict = {}

    result = retrieval.multi_channel_candidates(
        10.7757, 106.7009, 2000, "phở", None, 100, telemetry=telemetry
    )

    assert result is not None
    assert telemetry["degradedChannels"] == ["vector"]
    assert "vector" not in telemetry["channelsUsed"]


def test_bm25_loi_roi_ve_postgis_khong_cho_kenh_vector(monkeypatch) -> None:
    """Lỗi ở kênh bắt buộc (BM25/geo/h3) vẫn rơi về PostGIS như trước — và trả
    về ngay, không ngồi chờ kênh vector đang embed dở."""
    release = threading.Event()

    def slow_embedding(text: str) -> None:
        release.wait(5)
        return None

    client = _ParallelClient(parties=2, fail="bm25")
    _wire(monkeypatch, client, embedding=slow_embedding)

    started = time.perf_counter()
    try:
        result = retrieval.multi_channel_candidates(10.7757, 106.7009, 2000, "phở", None, 100)
        elapsed = time.perf_counter() - started
    finally:
        release.set()

    assert result is None
    assert elapsed < 2


def test_khong_co_query_chi_chay_kenh_khong_gian(monkeypatch) -> None:
    client = _ParallelClient(parties=2)

    def no_embedding(text: str) -> None:
        raise AssertionError("không có chữ thì không được embed")

    _wire(monkeypatch, client, embedding=no_embedding)
    telemetry: dict = {}

    result = retrieval.multi_channel_candidates(
        10.7757, 106.7009, 2000, None, None, 100, telemetry=telemetry
    )

    assert result is not None
    assert sorted(client.channels) == ["geo", "h3"]
    assert telemetry["degradedChannels"] is None


def test_spatial_channels_dung_executor_khi_co(monkeypatch) -> None:
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setattr(settings, "geo_channel", "both", raising=False)
    client = _ParallelClient(parties=2)

    with ThreadPoolExecutor(max_workers=2) as pool:
        channels, _info = retrieval._spatial_channels(
            client, 10.7757, 106.7009, 2000, None, executor=pool
        )

    assert channels == {"geo": ["geo-1"], "h3": ["h3-1"]}

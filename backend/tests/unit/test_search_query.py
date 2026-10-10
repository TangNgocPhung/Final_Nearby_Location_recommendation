import unicodedata

from app.search import query as q


def test_bm25_body_has_fuzzy_geo_and_category_filters() -> None:
    body = q.bm25_body("ca phe", 10.77, 106.70, 3000, "cafe", 50)

    should = body["query"]["bool"]["must"][0]["bool"]["should"]
    folded_match = should[0]["multi_match"]
    assert folded_match["fuzziness"] == "AUTO:5,8"
    assert "name^3" in folded_match["fields"]

    filters = body["query"]["bool"]["filter"]
    assert {"term": {"category_label.raw": "cafe"}} in filters
    geo = [f for f in filters if "geo_distance" in f][0]["geo_distance"]
    assert geo["distance"] == "3000m"
    assert geo["location"] == {"lat": 10.77, "lon": 106.70}


def test_bm25_body_strict_field_has_no_fuzziness() -> None:
    """``.strict`` (giữ dấu thanh điệu) KHÔNG được fuzzy — nếu fuzzy thì "viện"
    và "viên" (khác đúng 1 ký tự) sẽ lại khớp mờ, xoá tác dụng phân biệt dấu
    thanh mà field này tồn tại để giải quyết (xem docstring `bm25_body`)."""
    body = q.bm25_body("bệnh viện", 10.77, 106.70, 3000, None, 50)

    should = body["query"]["bool"]["must"][0]["bool"]["should"]
    strict_match = should[1]["multi_match"]
    assert "fuzziness" not in strict_match
    assert "name.strict^5" in strict_match["fields"]


def test_bm25_body_without_category_has_only_geo_filter() -> None:
    body = q.bm25_body("pho", 10.0, 106.0, 1000, None, 10)
    filters = body["query"]["bool"]["filter"]

    assert all("term" not in f for f in filters)
    assert len(filters) == 1


def test_geo_body_sorts_by_distance_and_has_no_text_clause() -> None:
    body = q.geo_body(10.0, 106.0, 2000, None, 25)

    assert "must" not in body["query"]["bool"]
    assert body["sort"][0]["_geo_distance"]["order"] == "asc"
    assert body["size"] == 25


def test_vector_body_carries_embedding_and_filter() -> None:
    embedding = [0.1] * 64
    body = q.vector_body(embedding, 10.0, 106.0, 2000, "cafe", 30)

    knn = body["query"]["knn"]["embedding"]
    assert knn["vector"] == embedding
    assert knn["k"] == 30
    inner = knn["filter"]["bool"]["filter"]
    assert {"term": {"category_label.raw": "cafe"}} in inner


def test_extract_ranked_ids_prefers_source_then_id() -> None:
    response = {
        "hits": {
            "hits": [
                {"_id": "ignored", "_source": {"poi_id": "p1"}},
                {"_id": "p2", "_source": {}},
            ]
        }
    }

    assert q.extract_ranked_ids(response) == ["p1", "p2"]


def test_extract_ranked_ids_handles_empty() -> None:
    assert q.extract_ranked_ids({}) == []
    assert q.extract_ranked_ids({"hits": {"hits": []}}) == []


def test_bm25_fuzzy_khong_ap_len_am_tiet_ngan() -> None:
    """Âm tiết <= 4 ký tự không được khớp mờ: với "AUTO" (=3,6), "benh" sửa 1 ký
    tự thành "ben"/"binh" và "bệnh viện" trả Công viên Bến Bạch Đằng / Công
    viên Lãnh Binh Thăng (đo được 19/09/2026)."""
    body = q.bm25_body("bệnh viện", 10.77, 106.70, 3000, None, 50)

    folded_match = body["query"]["bool"]["must"][0]["bool"]["should"][0]["multi_match"]
    low, high = folded_match["fuzziness"].removeprefix("AUTO:").split(",")
    assert int(low) >= 5


def test_bm25_tim_ca_trong_tu_vung_cua_loai_dia_diem() -> None:
    """Không có `search_keywords`, truy vấn "xem phim" không khớp trường nào của
    một rạp tên "CGV Vincom Đồng Khởi" — BM25 rỗng, cổng liên quan nhường cho
    RRF và kết quả là POI gần nhất bất kể loại gì (đo 19/09/2026).

    Boost đặt ngang `category_label` (^2 fold, ^3 strict): cùng là tín hiệu
    LOẠI, không được thắng khớp theo TÊN (`name^3` / `name.strict^5`)."""
    body = q.bm25_body("xem phim", 10.77, 106.70, 3000, None, 50)
    should = body["query"]["bool"]["must"][0]["bool"]["should"]

    assert "search_keywords^2" in should[0]["multi_match"]["fields"]
    assert "search_keywords.strict^3" in should[1]["multi_match"]["fields"]


# --- Cổng token: dấu thanh và danh từ đầu chung chung (đo 2026-10-08) --------


def _text_clause(query_text: str) -> dict:
    body = q.bm25_body(query_text, 10.7757, 106.7009, 3000, None, 50)
    return body["query"]["bool"]["must"][0]["bool"]


def _gate(query_text: str) -> dict:
    return _text_clause(query_text)["filter"][0]["bool"]


def test_quan_pho_chi_bat_buoc_pho_va_phai_dung_dau() -> None:
    """"quán phở" từng trả "Nhà Hát Thành Phố", "Phố Nhật Quán", "Phòng Quản
    lý..." và bỏ sót "Phở Nhà Mình" 174 m: fold gộp phở/phố, quán/quản, còn
    "2<70%" bắt buộc cả chữ "quán". Giờ chỉ "phở" bắt buộc, và chỉ khớp trên
    ``.strict`` với đúng dấu hoặc không dấu — không bao giờ "phố"."""
    gate = _gate("quán phở")

    assert len(gate["should"]) == 1
    match = gate["should"][0]["multi_match"]
    alternatives = set(match["query"].split())
    assert {"phở", "pho"} <= alternatives
    assert "phố" not in alternatives
    assert all(field.endswith(".strict") for field in match["fields"])
    assert "fuzziness" not in match


def test_token_khong_dau_van_khop_moi_dau_qua_vi_folded() -> None:
    """Gõ không dấu là chuyện thường: "pho" vẫn phải khớp "Phở" lẫn "Pho Hien"
    qua ``vi_folded`` (có fuzzy như clause chấm điểm). Không dùng
    ``name.prefix``: edge-ngram cho "pho" khớp vào "Phòng"."""
    match = _gate("pho")["should"][0]["multi_match"]

    assert match["query"] == "pho"
    assert "name" in match["fields"]
    assert not any(field.startswith("name.prefix") for field in match["fields"])
    assert not any(field.endswith(".strict") for field in match["fields"])
    assert match["fuzziness"] == "AUTO:5,8"


def test_quan_khong_dau_cung_la_danh_tu_dau_chung() -> None:
    gate = _gate("quan pho")

    assert [clause["multi_match"]["query"] for clause in gate["should"]] == ["pho"]


def test_truy_van_tron_dau_xet_tung_token() -> None:
    """Người gõ dấu nửa vời ("pho bò"): token nào có dấu mới bị đòi đúng dấu."""
    clauses = [clause["multi_match"] for clause in _gate("pho bò")["should"]]

    assert clauses[0]["query"] == "pho" and "fuzziness" in clauses[0]
    assert set(clauses[1]["query"].split()) >= {"bò", "bo"}
    assert "fuzziness" not in clauses[1]


def test_danh_tu_dau_giu_lai_khi_bo_di_lam_doi_loai() -> None:
    """"quán bar" -> "bar" mất loại bar, "quán ăn" -> "ăn" mất loại nhà hàng,
    "tiệm bánh" -> "bánh" mất loại tiệm bánh: giữ bắt buộc. "quán cà phê" ->
    "cà phê" vẫn là cafe, "cửa hàng tiện lợi" -> "tiện lợi" vẫn là tiện lợi:
    bỏ được."""

    def required(query_text: str) -> int:
        return len(_gate(query_text)["should"])

    assert required("quán bar") == 2
    assert required("quán ăn") == 2
    assert required("tiệm bánh") == 2
    assert required("quán cà phê") == 2  # "cà", "phê"
    assert required("cửa hàng tiện lợi") == 2  # "tiện", "lợi"


def test_quan_truoc_so_la_quan_huyen_khong_phai_quan_an() -> None:
    assert len(_gate("quan 1")["should"]) == 2


def test_quan_co_dau_khac_khong_phai_danh_tu_dau() -> None:
    """"quận" (gõ có dấu) không phải "quán" — vẫn bắt buộc."""
    assert len(_gate("quận phở")["should"]) == 2


def test_danh_tu_dau_dung_mot_minh_van_bat_buoc() -> None:
    assert len(_gate("quán")["should"]) == 1
    assert len(_gate("phở quán")["should"]) == 2


def test_hai_kieu_dat_dau_va_nfd_deu_duoc_chap_nhan() -> None:
    """DB có cả "Hoà" lẫn "Hòa" (328 / 1279 tên, đếm 2026-10-08) và 59 tên
    lưu NFD — gõ kiểu nào cũng phải khớp tên viết kiểu kia."""
    alternatives = set(_gate("hoà")["should"][0]["multi_match"]["query"].split())

    assert {"hoà", "hòa", "hoa"} <= alternatives
    assert unicodedata.normalize("NFD", "hòa") in alternatives
    assert q._tone_placements("thủy") == {"thủy", "thuỷ"}
    assert q._tone_placements("khoẻ") == {"khoẻ", "khỏe"}
    # Không thuộc vần mở oa/oe/uy: chỉ một cách viết.
    assert q._tone_placements("quý") == {"quý"}
    assert q._tone_placements("hoàng") == {"hoàng"}
    assert q._tone_placements("phở") == {"phở"}


def test_query_tokens_chuan_hoa_nfd() -> None:
    assert q.query_tokens(unicodedata.normalize("NFD", "Quán Phở")) == ["quán", "phở"]


def test_minimum_should_match_ap_len_cong_token(monkeypatch) -> None:
    """"2<70%" giờ đếm trên token BẮT BUỘC của cổng, không còn trên từng
    multi_match chấm điểm — ``best_fields`` đòi mọi token khớp trong CÙNG một
    trường, không có chỗ đặt "token này phải đúng dấu"."""
    text = _text_clause("cơm tấm")

    assert text["filter"][0]["bool"]["minimum_should_match"] == "2<70%"
    for clause in text["should"]:
        if "multi_match" in clause:
            assert "minimum_should_match" not in clause["multi_match"]

    monkeypatch.setattr(q.settings, "search_text_min_should_match", "")
    assert _gate("cơm tấm")["minimum_should_match"] == 1


def test_thuong_khi_ten_chua_nguyen_cum() -> None:
    phrases = [clause for clause in _text_clause("quan pho")["should"] if "match_phrase" in clause]

    assert phrases == [{"match_phrase": {"name": {"query": "quan pho", "boost": 2}}}]


def test_truy_van_khong_co_chu_khong_co_cong() -> None:
    assert "filter" not in _text_clause("!!!")

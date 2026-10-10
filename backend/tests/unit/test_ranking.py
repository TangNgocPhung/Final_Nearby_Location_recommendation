from copy import deepcopy

import pytest

from app.config import settings
from app.ranking import _relevance_sort_key, diversify, ensure_distance_diversity, insert_sponsored, rerank


def candidate(
    poi_id: str,
    category: str,
    *,
    distance: float = 500,
    text: float = 0.8,
    rating: float = 4.5,
    popularity: float = 0.7,
    trending: float = 0.0,
) -> dict:
    return {
        "id": poi_id,
        "category": category,
        "distanceMeters": distance,
        "textScore": text,
        "rating": rating,
        "popularityScore": popularity,
        "trendingScore": trending,
    }


def test_rerank_prefers_stronger_relevance_signals() -> None:
    weak = candidate("weak", "park", distance=2000, text=0.2, rating=3.0, popularity=0.2)
    strong = candidate("strong", "cafe", distance=200, text=0.95, rating=4.9, popularity=0.95)

    ranked = rerank(deepcopy([weak, strong]))

    assert [item["id"] for item in ranked] == ["strong", "weak"]
    assert ranked[0]["score"] > ranked[1]["score"]


def test_rerank_gate_day_candidate_khong_lien_quan_van_ban_xuong_sau() -> None:
    """Đo được thật: truy vấn "cà phê" (radius 3km, limit 50) vẫn xếp "Phở Nhà
    Mình" (không BM25, không vector, chỉ gần 174m + đang trending cao) ở HẠNG 1
    — vì `_gate_by_text_relevance` ở tầng retrieval chỉ quyết định ai LỌT VÀO
    candidate pool, còn `rerank` tính điểm và sắp xếp lại TỪ ĐẦU, ghi đè hoàn
    toàn thứ tự đó. Ứng viên gần + trending nhưng KHÔNG có bm25Score/vectorScore
    phải luôn đứng sau ứng viên có tín hiệu văn bản khi có query text, bất kể
    điểm số tuyến tính cao thấp ra sao."""
    no_text_signal = candidate(
        "gan-trending", "restaurant", distance=174, text=0.0, rating=4.6, popularity=0.9, trending=0.8
    )
    no_text_signal["vectorScore"] = None
    has_bm25 = candidate(
        "co-bm25", "cafe", distance=1500, text=0.6, rating=4.0, popularity=0.5, trending=0.0
    )
    has_bm25["vectorScore"] = None
    has_vector_only = candidate(
        "co-vector", "cafe", distance=1500, text=0.0, rating=4.0, popularity=0.5, trending=0.0
    )
    has_vector_only["vectorScore"] = 0.8

    ranked = rerank(deepcopy([no_text_signal, has_bm25, has_vector_only]), has_query_text=True)

    assert ranked[-1]["id"] == "gan-trending"
    assert {ranked[0]["id"], ranked[1]["id"]} == {"co-bm25", "co-vector"}


def test_rerank_khong_gate_khi_khong_co_query_text() -> None:
    """Duyệt theo vị trí thuần — không có "liên quan văn bản" nào để so sánh,
    điểm tuyến tính (đặc biệt khoảng cách) mới là thứ quyết định thứ tự."""
    close_no_signal = candidate("gan", "restaurant", distance=174, text=1.0, trending=0.8)
    close_no_signal["vectorScore"] = None
    far_with_signal = candidate("xa", "cafe", distance=1500, text=1.0)
    far_with_signal["vectorScore"] = None

    ranked = rerank(deepcopy([close_no_signal, far_with_signal]), has_query_text=False)

    assert ranked[0]["id"] == "gan"


@pytest.mark.xfail(
    reason=(
        "Giới hạn ĐÃ BIẾT của embedding hashing-v2-64, cố ý CHƯA vá bằng "
        "ngưỡng vectorScore (xem thảo luận Phase 6.5): đo được thật trên "
        "truy vấn 'mỳ cay' — 'Bảo tàng Thành phố' (mô tả hoàn toàn không liên "
        "quan) nhận vectorScore=0.647 do trùng ngẫu nhiên vài slot băm, đứng "
        "TRÊN cả candidate khớp BM25 thật. Không đặt ngưỡng tạm vì không có "
        "bằng chứng ngưỡng nào tách được match thật khỏi hash collision một "
        "cách ổn định (candidate khớp thật đo được chỉ 0.737, cách 0.647 rất "
        "gần). Test này XFAIL có chủ đích — khi Phase semantic embedding thay "
        "hashing bằng model thật, test sẽ tự PASS (xpass) và đó là tín hiệu "
        "để xoá marker này đi, không phải để sửa rerank."
    ),
    strict=False,
)
def test_vector_hashing_false_positive_khong_duoc_thang_bm25_that() -> None:
    """Dùng ĐÚNG con số đo thật từ API (truy vấn "mỳ cay", không phải tái tạo
    qua `rerank` — công thức tuyến tính có quá nhiều tín hiệu phụ (popularity/
    trending/context/regionCtr...) để tái tạo chính xác bằng tay; test trên số
    ``score`` cuối cùng đã đo mới trung thực với lỗi thật đang xảy ra."""
    museum_false_positive = {
        "id": "museum-khong-lien-quan",
        "textScore": 0.0,
        "vectorScore": 0.647,
        "score": 0.474654,
        "distanceMeters": 177,
    }
    real_bm25_vector_match = {
        "id": "nha-hang-that",
        "textScore": 0.9,
        "vectorScore": 0.737,
        "score": 0.404866,
        "distanceMeters": 1436,
    }

    ranked = sorted(
        [museum_false_positive, real_bm25_vector_match], key=_relevance_sort_key(has_query_text=True)
    )

    assert ranked[0]["id"] == "nha-hang-that"


def test_category_boost_changes_score_without_removing_other_signals() -> None:
    original = candidate("one", "cafe")

    regular_score = rerank(deepcopy([original]))[0]["score"]
    boosted_score = rerank(deepcopy([original]), category_boost={"cafe": 0.2})[0]["score"]

    assert boosted_score == pytest.approx(regular_score + 0.2)


def test_diversify_prevents_three_consecutive_categories_when_possible() -> None:
    results = [
        candidate("c1", "cafe"),
        candidate("c2", "cafe"),
        candidate("c3", "cafe"),
        candidate("p1", "park"),
    ]

    diversified = diversify(results, max_run=2)

    assert [item["id"] for item in diversified] == ["c1", "c2", "p1", "c3"]


def test_cong_chat_luong_khong_cho_rating_cao_lat_nguoc_khop_van_ban(monkeypatch) -> None:
    """Đo được thật trên dữ liệu đang chạy (3.010 POI, truy vấn "bệnh viện",
    bán kính 3km): `Bệnh Viện Mắt Sài Gòn` có textScore = 1.0000 — tức BM25 CAO
    NHẤT trong tập ứng viên — nhưng chỉ xếp HẠNG 7 (score 0.395), trong khi
    `Công viên Bến Bạch Đằng` (textScore 0.7893) xếp HẠNG 1 (score 0.546).

    Công viên vẫn có BM25 cao vì analyzer đã fold `category_label` "công viên"
    thành token `vien`, trùng với "bệnh viện" — field `.strict` của Phase 10
    kéo bệnh viện lên đầu BM25 nhưng KHÔNG xoá được điểm của công viên. Phần
    lật ngược đến từ rating 4.6 và popularity 0.96 (dữ liệu seed): hai tín hiệu
    này cho công viên +0.158 điểm chuẩn hoá, còn lợi thế văn bản của bệnh viện
    chỉ +0.052 — gấp ba lần.

    Cổng chất lượng nhân trọng số rating/popularity với
    (textScore / max textScore) ** mũ, nên ứng viên khớp văn bản kém hơn hẳn
    không còn cưỡi lên rating/popularity để thắng. Đo A/B trên cùng một tập
    ứng viên (truy xuất một lần, chấm điểm nhiều lần): hạng của bệnh viện đi
    từ 7 (mũ=0) lên 3-4 (mũ=2) và bão hoà ở đó — mũ=3 không cải thiện thêm.
    Đo hai lần ở hai thời điểm ra 7->3 và 7->4; chênh lệch là do trending/
    recency tính lại theo từng giây nên tập ứng viên hai lần không giống hệt.
    Ba truy vấn đã gán nhãn "cà phê"/"công viên"/"bảo tàng" giữ nguyên hạng 1
    ở mọi mũ, và "cơm tấm" đi từ 3 lên 2.

    Hai ứng viên dưới đây đặt CÙNG khoảng cách để cô lập đúng phần tín hiệu
    chất lượng; mũ=0 giữ lại hành vi cũ, dùng làm mốc đối chứng.
    """
    cong_vien = candidate(
        "cong-vien", "park", distance=800, text=0.7893, rating=4.6, popularity=0.96
    )
    benh_vien = candidate(
        "benh-vien", "hospital", distance=800, text=1.0, rating=None, popularity=0.0
    )

    def khoang_cach(mu: float) -> float:
        monkeypatch.setattr(settings, "ranking_quality_gate_exponent", mu)
        diem = {
            item["id"]: item["score"]
            for item in rerank(deepcopy([cong_vien, benh_vien]), has_query_text=True)
        }
        return diem["cong-vien"] - diem["benh-vien"]

    cu = khoang_cach(0.0)  # mốc đối chứng: đúng hành vi trước khi có cổng
    moi = khoang_cach(2.0)

    assert cu > 0, "mốc đối chứng: tắt cổng thì công viên dẫn trước"
    assert moi < cu, "bật cổng phải thu hẹp khoảng cách"
    # Ở cặp CÔ LẬP này công viên vẫn dẫn: cổng chỉ hạ bớt phần rating/
    # popularity, không xoá hẳn. Trong tập ứng viên thật (100 ứng viên, còn
    # spatial/context/trending khác nhau) mức hạ đó đủ đưa bệnh viện từ hạng 7
    # lên hạng 3-4 — ghi lại giới hạn này ở đây để lần sau không ai tưởng cổng
    # là lời giải trọn vẹn.
    assert moi > 0


def test_cong_chat_luong_khong_doi_gi_khi_khong_co_query_text(monkeypatch) -> None:
    """Duyệt theo vị trí (không có query text) thì mọi ứng viên có textScore =
    1.0 như nhau, nên cổng phải mở hoàn toàn — nếu không, một thay đổi nhắm vào
    đường TÌM KIẾM sẽ âm thầm đổi luôn đường DUYỆT."""
    a = candidate("a", "park", distance=800, text=1.0, rating=4.6, popularity=0.96)
    b = candidate("b", "hospital", distance=800, text=1.0, rating=None, popularity=0.0)

    monkeypatch.setattr(settings, "ranking_quality_gate_exponent", 0.0)
    tat = rerank(deepcopy([a, b]), has_query_text=False)
    monkeypatch.setattr(settings, "ranking_quality_gate_exponent", 2.0)
    bat = rerank(deepcopy([a, b]), has_query_text=False)

    assert [i["id"] for i in tat] == [i["id"] for i in bat]
    assert [i["score"] for i in tat] == [i["score"] for i in bat]


# --- truy vấn nêu loại địa điểm (đo 2026-10-09) ---------------------------------
#
# "quán bình dân" xếp UBND phường 8 ở hạng 2: BM25 khớp mờ "quan"/"dan" trên
# từ khoá nhóm hành chính ("cơ quan", "nhân dân"), UBND gần hơn nên điểm cao
# hơn, rồi `diversify` còn kéo thêm loại khác chen vào giữa các quán cơm.

RESTAURANT = frozenset({"restaurant"})


def test_truy_van_neu_loai_day_ung_vien_khac_loai_xuong_sau() -> None:
    ubnd = candidate("ubnd", "government", distance=500, text=0.11)
    quan_com = candidate("quan-com", "restaurant", distance=1200, text=1.0, rating=3.0)

    ranked = rerank(deepcopy([ubnd, quan_com]), has_query_text=True, intent_categories=RESTAURANT)

    assert [item["id"] for item in ranked] == ["quan-com", "ubnd"]


def test_khong_neu_loai_thi_khong_doi_thu_tu() -> None:
    near = candidate("near", "government", distance=100)
    far = candidate("far", "restaurant", distance=2500)

    ranked = rerank(deepcopy([near, far]), has_query_text=True)

    assert [item["id"] for item in ranked] == ["near", "far"]


def test_diversify_khong_chen_loai_khac_vao_giua_loai_duoc_hoi() -> None:
    results = [
        candidate("r1", "restaurant"),
        candidate("r2", "restaurant"),
        candidate("r3", "restaurant"),
        candidate("g1", "government"),
    ]

    diversified = diversify(results, max_run=2, intent_categories=RESTAURANT)

    assert [item["id"] for item in diversified] == ["r1", "r2", "r3", "g1"]


def test_luat_khoang_cach_khong_keo_ung_vien_khac_loai_len_top() -> None:
    results = [candidate(f"r{i}", "restaurant", distance=200) for i in range(3)]
    results.append(candidate("g-xa", "government", distance=2500))

    ordered = ensure_distance_diversity(results, k=3, intent_categories=RESTAURANT)

    assert "g-xa" not in [item["id"] for item in ordered[:3]]


def test_tai_tro_khac_loai_khong_duoc_chen_vao_top() -> None:
    results = [candidate(f"r{i}", "restaurant") for i in range(3)]
    results.append({**candidate("g-tt", "government"), "sponsored": True})

    ordered = insert_sponsored(results, intent_categories=RESTAURANT)

    assert [item["id"] for item in ordered] == ["r0", "r1", "r2", "g-tt"]


# --- truy vấn nêu loại KÈM tên riêng (đo 2026-10-10) ----------------------------
#
# "nhà thờ Đức Bà" quanh Quận 1: "nhà thờ" là từ khoá loại place_of_worship, mà
# POI "Nhà thờ Đức Bà" lại gắn loại landmark, nên luật lệch loại đẩy nó ra sau
# mọi nơi thờ tự và "Đền Sri Thenday Yutthapani" (chỉ khớp qua search_keywords,
# gần hơn) lên hạng 1.

WORSHIP = frozenset({"place_of_worship"})


def named(poi_id: str, name: str, category: str, **kwargs) -> dict:
    return {**candidate(poi_id, category, **kwargs), "name": name}


def test_ten_chua_tron_cum_truy_van_thang_luat_lech_loai() -> None:
    den_sri = named("den-sri", "Đền Sri Thenday Yutthapani", "place_of_worship", distance=244, text=0.15)
    vinh_hoi = named("vinh-hoi", "Nhà thờ Vĩnh Hội", "place_of_worship", distance=1508, text=0.43)
    duc_ba = named("duc-ba", "Nhà thờ Đức Bà", "landmark", distance=499, text=1.0)

    ranked = rerank(
        deepcopy([den_sri, vinh_hoi, duc_ba]),
        has_query_text=True,
        intent_categories=WORSHIP,
        query_text="nhà thờ Đức Bà",
    )

    assert ranked[0]["id"] == "duc-ba"


def test_chi_chua_phan_ten_rieng_thi_van_bi_ha() -> None:
    """Đòi trọn cụm: "Nhà Sách Đức Bà Hoà Binh" (367 m) có "đức bà" nhưng không
    phải thứ người dùng tìm khi gõ "nhà thờ Đức Bà"."""
    nha_sach = named("nha-sach", "Nhà Sách Đức Bà Hoà Binh", "bookstore", distance=367, text=0.6)
    den_sri = named("den-sri", "Đền Sri Thenday Yutthapani", "place_of_worship", distance=244, text=0.15)

    ranked = rerank(
        deepcopy([nha_sach, den_sri]),
        has_query_text=True,
        intent_categories=WORSHIP,
        query_text="nhà thờ Đức Bà",
    )

    assert [item["id"] for item in ranked] == ["den-sri", "nha-sach"]


def test_ten_khop_khong_dau_khi_ten_poi_khong_dau() -> None:
    den_sri = named("den-sri", "Đền Sri Thenday Yutthapani", "place_of_worship", distance=244, text=0.15)
    duc_ba = named("duc-ba", "Nha tho Duc Ba", "landmark", distance=499, text=1.0)

    ranked = rerank(
        deepcopy([den_sri, duc_ba]),
        has_query_text=True,
        intent_categories=WORSHIP,
        query_text="nha tho duc ba",
    )

    assert ranked[0]["id"] == "duc-ba"


def test_truy_van_thuan_loai_khong_mien_ha_hang_theo_ten() -> None:
    """"quán bình dân" bỏ từ khoá loại xong là rỗng: không có tên riêng nào để
    miễn, UBND vẫn phải đứng sau quán cơm."""
    ubnd = named("ubnd", "Ủy ban nhân dân Phường 8", "government", distance=500, text=0.11)
    quan_com = named("quan-com", "Cơm Tấm Cô Ba", "restaurant", distance=1200, text=1.0, rating=3.0)

    ranked = rerank(
        deepcopy([ubnd, quan_com]),
        has_query_text=True,
        intent_categories=RESTAURANT,
        query_text="quán bình dân",
    )

    assert [item["id"] for item in ranked] == ["quan-com", "ubnd"]


def test_truy_van_thuan_loai_khong_day_ten_chua_tu_khoa_len_dau() -> None:
    """"cà phê" là thuần loại: quán tên "Cà phê X" xa hơn không được nhảy lên
    trước quán cà phê gần hơn chỉ vì tên chứa từ khoá."""
    gan = named("gan", "Highlands Coffee", "cafe", distance=100)
    xa = named("xa", "Cà phê Vợt", "cafe", distance=1800)

    ranked = rerank(
        deepcopy([xa, gan]), has_query_text=True, intent_categories=frozenset({"cafe"}), query_text="cà phê"
    )

    assert [item["id"] for item in ranked] == ["gan", "xa"]

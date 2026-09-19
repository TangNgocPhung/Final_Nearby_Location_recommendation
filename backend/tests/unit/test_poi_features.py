import math

import h3
import pytest

from app.poi_features import (
    EMBEDDING_DIMENSION,
    dedupe_fingerprint,
    h3_cells,
    normalize_osm_element,
    normalize_district,
    normalize_text,
    text_embedding,
)
from app.poi_import import build_overpass_query, parse_bbox


def test_vietnamese_text_normalization_is_deterministic() -> None:
    assert normalize_text("  Cà phê Đường Sách! ") == "ca phe duong sach"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("District 1", "Quận 1"),
        ("Quan 7", "Quận 7"),
        ("Quận Tân Bình", "Quận Tân Bình"),
        ("Bình Thạnh", "Quận Bình Thạnh"),
        ("Xuân Hòa", None),
    ],
)
def test_district_normalization_rejects_ward_names(raw: str, expected: str | None) -> None:
    assert normalize_district(raw) == expected


def test_embedding_has_fixed_dimension_and_unit_norm() -> None:
    first = text_embedding(("Cà phê", "không gian yên tĩnh", "wifi"))
    second = text_embedding(("Cà phê", "không gian yên tĩnh", "wifi"))
    assert first == second
    assert len(first) == EMBEDDING_DIMENSION
    assert math.sqrt(sum(value * value for value in first)) == pytest.approx(1.0, abs=1e-6)


@pytest.mark.parametrize(
    "word",
    ["phở", "bún", "cơm", "bánh", "cà", "phê", "trà", "mì", "hủ", "tiếu", "chợ", "quán"],
)
def test_single_word_query_never_yields_zero_vector(word: str) -> None:
    """Vector toàn 0 làm OpenSearch từ chối k-NN và kênh Vector ANN chết âm thầm.

    Ở v1 hai slot băm có thể trùng nhau và triệt tiêu; "phở" là một ca dính lỗi
    thật, đúng từ khoá ví dụ của đề tài.
    """
    assert any(text_embedding((word,)))


def test_embedding_slots_never_collide_across_alphabet() -> None:
    """Quét rộng: không từ đơn nào trong bảng chữ cái tiếng Việt không dấu được
    phép cho vector 0, vì slot thứ hai luôn lệch khỏi slot thứ nhất."""
    alphabet = "abcdefghiklmnopqrstuvxy"
    empty = [
        first + second
        for first in alphabet
        for second in alphabet
        if not any(text_embedding((first + second,)))
    ]
    assert empty == []


def test_h3_cells_have_expected_resolutions() -> None:
    cells = h3_cells(10.7757, 106.7009)
    assert {key: h3.get_resolution(value) for key, value in cells.items()} == {
        "r7": 7,
        "r8": 8,
        "r9": 9,
    }


def test_osm_element_is_mapped_to_canonical_shape() -> None:
    poi = normalize_osm_element(
        {
            "type": "node",
            "id": 123,
            "lat": 10.7757,
            "lon": 106.7009,
            "tags": {
                "name": "Cà phê Thử Nghiệm",
                "amenity": "cafe",
                "opening_hours": "Mo-Su 07:00-22:00",
                "addr:district": "Quận 1",
                "internet_access": "wlan",
            },
        }
    )
    assert poi is not None
    assert poi["category"] == "cafe"
    assert poi["source_id"] == "node/123"
    assert poi["district"] == "Quận 1"
    assert len(poi["embedding"]) == EMBEDDING_DIMENSION
    assert poi["amenities"]["internet_access"] == "wlan"


def test_bbox_and_overpass_query_are_bounded() -> None:
    bbox = parse_bbox("10.70,106.60,10.90,106.82")
    query = build_overpass_query(bbox)
    assert 'nwr["name"]["amenity"' in query
    assert "10.7,106.6,10.9,106.82" in query


def test_fingerprint_changes_with_location() -> None:
    first = dedupe_fingerprint("Cà phê A", "cafe", 10.77, 106.70)
    second = dedupe_fingerprint("Cà phê A", "cafe", 10.78, 106.70)
    assert first != second


# --- Từ vựng tiếng Việt theo loại địa điểm (rạp chiếu phim) -------------------
#
# Bối cảnh: truy vấn "xem phim" trả về bảo tàng và quán phở (đo 19/09/2026).
# Nguyên nhân không phải ở thuật toán mà ở TỪ VỰNG: không trường nào của một
# rạp chứa chữ người Việt dùng để gọi nó.

from app.poi_features import (  # noqa: E402
    CATEGORY_KEYWORDS,
    CATEGORY_MAP,
    categories_for_query,
    category_keywords,
    osm_category,
)


def test_rap_chieu_phim_co_nhan_rieng_khong_gop_vao_giai_tri() -> None:
    """Nhãn là trường BM25 chấm điểm cao (`category_label^2`) và cũng là chip
    lọc; gộp rạp vào "Giải trí" chung với bar/pub thì mất cả hai."""
    assert osm_category({"amenity": "cinema"}) == ("cinema", "Xem phim")
    # Các loại "Giải trí" còn lại giữ nguyên nhãn cũ.
    assert osm_category({"amenity": "bar"}) == ("bar", "Giải trí")
    assert osm_category({"leisure": "playground"}) == ("playground", "Giải trí")


def test_san_bay_nhan_dien_qua_khoa_aeroway() -> None:
    """`aeroway=aerodrome` không nằm trong bốn khoá amenity/tourism/leisure/
    shop mà `osm_category` từng duyệt — thiếu khoá này là lý do Tân Sơn Nhất
    chưa bao giờ được nhập dù đã có mặt trong OSM."""
    assert osm_category({"aeroway": "aerodrome"}) == ("airport", "Sân bay")
    assert osm_category({"aeroway": "helipad"}) is None


def test_spa_nhan_dien_qua_leisure_spa() -> None:
    """`leisure=spa` từng không nằm trong danh sách giá trị lọc của khoá
    `leisure` (`poi_import.OSM_FILTERS`), nên không có spa nào được nhập —
    truy vấn "spa" vì vậy có BM25 rỗng và rơi về ứng viên gần nhất bất kể
    loại gì, đúng lớp lỗi đã sửa cho sân bay."""
    assert osm_category({"leisure": "spa"}) == ("spa", "Spa")
    # Khoá `leisure` đã được `osm_category` duyệt từ trước; các giá trị khác
    # của nó giữ nguyên hành vi cũ.
    assert osm_category({"leisure": "park"}) == ("park", "Công viên")


@pytest.mark.parametrize(
    "query",
    ["xem phim", "Xem Phim", "rạp chiếu phim", "rap chieu phim", "coi phim", "phim"],
)
def test_moi_cach_goi_rap_deu_dan_ve_cung_mot_loai(query: str) -> None:
    """Gõ không dấu là trường hợp phổ biến nhất chứ không phải ngoại lệ, nên
    "rap chieu phim" phải cho cùng kết quả với "rạp chiếu phim"."""
    assert categories_for_query(query) == ("cinema",)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("cà phê", ("cafe",)),
        ("bệnh viện", ("hospital",)),
        ("công viên", ("park",)),
        ("siêu thị", ("supermarket",)),
        ("nhà thuốc", ("pharmacy",)),
        ("khách sạn", ("hotel",)),
    ],
)
def test_moi_loai_deu_co_tu_vung_tieng_viet_cua_no(
    query: str, expected: tuple[str, ...]
) -> None:
    """Đo được trên production 19/09/2026: "siêu thị" trả về ngân hàng và
    những POI gần nhất, dù `shop=supermarket` có đầy trong dữ liệu — không
    trường nào của một siêu thị chứa chữ "siêu thị" (tên là Co.opmart, Bách
    hóa Xanh; thẻ OSM là "supermarket"; nhãn là "Mua sắm").

    Cùng một lỗi với "xem phim", nên phải cùng một cách chữa cho MỌI loại chứ
    không chỉ loại nào vừa có người báo."""
    assert categories_for_query(query) == expected


@pytest.mark.parametrize("query", ["", None, "nguyễn huệ", "phở", "landmark 81"])
def test_truy_van_khong_nham_loai_nao_thi_tra_rong(query: str | None) -> None:
    """Tên riêng KHÔNG được suy thành loại. Vì thế bảng từ khoá cố ý không
    nhận âm tiết đơn như "trường" ("Công trường Lam Sơn" là địa danh thật)."""
    assert categories_for_query(query) == ()


@pytest.mark.parametrize(
    "query", ["công trường lam sơn", "công trường quốc tế", "trường sa"]
)
def test_dia_danh_chua_chu_truong_khong_bi_hieu_thanh_truong_hoc(query: str) -> None:
    assert categories_for_query(query) == ()


def test_tu_khoa_mot_am_tiet_khop_theo_ranh_gioi_tu() -> None:
    """"phim" nằm GIỮA một từ khác không được tính là khớp — đúng loại lỗi mà
    fuzzy "AUTO" từng gây ra cho "bệnh viện" (xem `search.query.bm25_body`)."""
    assert categories_for_query("phimosis") == ()
    assert categories_for_query("xemphim") == ()


def test_bang_tu_khoa_chi_chua_loai_co_that() -> None:
    """Từ khoá gắn theo `category`, nên một mã gõ sai sẽ im lặng không bao giờ
    khớp POI nào."""
    known = {category for category, _label in CATEGORY_MAP.values()}
    assert set(CATEGORY_KEYWORDS) <= known


def test_category_keywords_tra_rong_cho_loai_khong_ton_tai() -> None:
    assert category_keywords("khong-co-loai-nay") == ()
    assert category_keywords(None) == ()
    assert "rạp chiếu phim" in category_keywords("cinema")
    assert "siêu thị" in category_keywords("supermarket")


def test_moi_loai_trong_category_map_deu_co_tu_khoa() -> None:
    """Thiếu một loại là lặp lại đúng lỗi "siêu thị": loại đó tồn tại trong dữ
    liệu nhưng người dùng gõ tiếng Việt thì không tìm ra."""
    known = {category for category, _label in CATEGORY_MAP.values()}
    assert set(CATEGORY_KEYWORDS) == known


def test_tags_cua_poi_khong_bi_nhet_tu_khoa_truy_xuat() -> None:
    """Từ vựng truy xuất chỉ sống trong chỉ mục (`search.index.build_document`).
    Nhét vào `tags` thì trang chi tiết hiện ra bảy chip đồng nghĩa của cùng một
    từ, mà `tags` vốn là token OSM thô hiển thị cho người dùng."""
    poi = normalize_osm_element(
        {
            "type": "node",
            "id": 555,
            "lat": 10.7789,
            "lon": 106.7029,
            "tags": {"name": "CGV Vincom", "amenity": "cinema"},
        }
    )
    assert poi is not None
    assert poi["category_label"] == "Xem phim"
    assert poi["tags"] == ["cinema"]

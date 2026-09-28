from app.storefront import best_match, core_name, decide, match_score, normalize, pano_center_x


def test_normalize_bo_dau_va_d():
    assert normalize("Khách sạn ĐÔNG Đô!") == "khach san dong do"


def test_core_name_bo_tu_chi_loai():
    assert core_name("Khách sạn Trung Mai") == "trung mai"
    assert core_name("Trung Mai Hotel") == "trung mai"
    # Bỏ hết thì còn quá ngắn → giữ tên đầy đủ.
    assert core_name("Cafe") == "cafe"


def test_so_khop_chiu_loi_doc_sai_mot_chu():
    # Số liệu thật ở Trung Mai: model đọc ảnh 360° đúng, ảnh ban ngày sai MAI→NAM.
    assert match_score("Trung Mai", "TRUNG MAI") == 1.0
    assert match_score("Trung Mai", "TRUNG MAI HOTEL") == 1.0
    assert 0.7 <= match_score("Trung Mai", "TRUNG NAM HOTEL") < 0.85
    assert match_score("Trung Mai", "TOMAS") < 0.5


def test_best_match_chon_dong_giong_nhat():
    score, text = best_match("Trung Mai", ["HOTEL", "KHU VUC TRUONG HOC", "TRUNG MAI"])
    assert (score, text) == (1.0, "TRUNG MAI")


def _reading(image_id, captured, score, texts, distance=15.0, quality=0.8):
    return {
        "imageId": image_id,
        "capturedAt": captured,
        "distanceMeters": distance,
        "quality": quality,
        "texts": texts,
        "score": score,
        "matchedText": texts[0] if texts else None,
    }


def test_mot_anh_khop_manh_la_xac_minh():
    result = decide("Trung Mai", [_reading("a", "2025-08-28T10:00:00+00:00", 1.0, ["TRUNG MAI"])])
    assert result["status"] == "verified"
    assert result["evidence"]["imageId"] == "a"


def test_hai_anh_khop_vua_la_xac_minh_mot_anh_thi_khong():
    weak = _reading("a", "2025-08-28T10:00:00+00:00", 0.78, ["TRUNG NAM HOTEL"])
    assert decide("Trung Mai", [weak])["status"] == "unreadable"
    weak2 = _reading("b", "2023-08-19T10:00:00+00:00", 0.75, ["TRUNG MAl"])
    assert decide("Trung Mai", [weak, weak2])["status"] == "verified"


def test_anh_moi_ro_thay_bien_khac_la_mismatch():
    readings = [
        _reading("moi", "2025-08-28T10:00:00+00:00", 0.1, ["PHỞ HÙNG", "HOTEL"]),
        _reading("cu", "2019-03-01T10:00:00+00:00", 1.0, ["TRUNG MAI"]),
    ]
    result = decide("Trung Mai", readings)
    assert result["status"] == "mismatch"
    assert result["evidence"]["imageId"] == "moi"
    assert "PHỞ HÙNG" in result["matchedText"]


def test_anh_moi_khong_doc_duoc_khong_phai_bang_chung_dong_cua():
    readings = [
        # Mới hơn nhưng chỉ đọc được chữ chung chung (xe che / tối).
        _reading("moi", "2025-08-28T10:00:00+00:00", 0.1, ["HOTEL", "30m"]),
        _reading("cu", "2019-03-01T10:00:00+00:00", 1.0, ["TRUNG MAI"]),
    ]
    assert decide("Trung Mai", readings)["status"] == "verified"


def test_anh_moi_mo_hoac_xa_khong_tinh():
    readings = [
        _reading("mo", "2025-08-28T10:00:00+00:00", 0.1, ["PHỞ HÙNG"], quality=0.1),
        _reading("xa", "2025-08-28T10:00:00+00:00", 0.1, ["PHỞ HÙNG"], distance=40.0),
        _reading("cu", "2019-03-01T10:00:00+00:00", 1.0, ["TRUNG MAI"]),
    ]
    assert decide("Trung Mai", readings)["status"] == "verified"


def test_khong_co_anh():
    assert decide("Trung Mai", [])["status"] == "no_imagery"


def test_tam_anh_360_dung_huong():
    # Số liệu thật ở Trung Mai: hướng máy quay 118,1°, hướng tới quán 184,3°.
    assert round(pano_center_x({"compassAngle": 118.1, "bearingToPoi": 184.3}), 3) == 0.684

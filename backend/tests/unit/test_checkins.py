"""Check-in khám phá AR — phần kiểm được mà không cần database.

Hành vi cần PostGIS (khoảng cách thật, một lượt mỗi POI, chuyển sang tài khoản
khi đăng nhập) đã đo trên database dev khi dựng tính năng. Ở đây khoá lại bán
kính, cách tính huy hiệu và các ràng buộc phải chặn TRƯỚC khi mở kết nối.
"""

import pytest
from pydantic import ValidationError

from app import checkins
from app.models import CheckInRequest
from app.poi_features import CATEGORY_MAP

KNOWN_CATEGORIES = {category for category, _ in CATEGORY_MAP.values()}


def test_ban_kinh_mac_dinh_cong_sai_so_gps() -> None:
    assert checkins.allowed_distance("cafe", None) == 50
    assert checkins.allowed_distance("cafe", 12) == 62


def test_sai_so_gps_co_tran() -> None:
    """Máy báo sai số 2 km không được vì thế mà check-in từ nhà."""
    assert checkins.allowed_distance("cafe", 2_000) == 50 + checkins.MAX_ACCURACY_ALLOWANCE_METERS


def test_sai_so_am_khong_lam_hep_ban_kinh() -> None:
    assert checkins.allowed_distance("cafe", -40) == 50


def test_khu_dat_rong_co_ban_kinh_rong_hon() -> None:
    """Toạ độ công viên là tâm khu đất; đứng ở cổng đã cách vài trăm mét."""
    assert checkins.allowed_distance("park", 0) == 350
    assert checkins.allowed_distance(None, 0) == checkins.CHECKIN_RADIUS_METERS


def test_moi_loai_trong_cau_hinh_deu_ton_tai() -> None:
    """Gõ sai tên loại (``coffee`` thay vì ``cafe``) thì huy hiệu không bao giờ
    đạt được mà không có lỗi nào báo ra."""
    configured = set(checkins.WIDE_CATEGORY_RADIUS) | set(checkins.EXCLUDED_CATEGORIES)
    for badge in checkins.BADGES:
        configured |= set(badge["categories"])
    assert configured <= KNOWN_CATEGORIES


def test_id_huy_hieu_khong_trung() -> None:
    ids = [badge["id"] for badge in checkins.BADGES]
    assert len(ids) == len(set(ids))


def _badge(progress: list[dict], badge_id: str) -> dict:
    return next(badge for badge in progress if badge["id"] == badge_id)


def test_chua_check_in_thi_chua_dat_huy_hieu_nao() -> None:
    progress = checkins.badge_progress([])
    assert len(progress) == len(checkins.BADGES)
    assert not any(badge["earned"] for badge in progress)


def test_huy_hieu_theo_loai_chi_dem_dung_loai() -> None:
    progress = checkins.badge_progress(["cafe", "cafe", "restaurant", "cafe"])
    coffee = _badge(progress, "coffee_hunter")
    assert coffee["earned"] and coffee["progress"] == 3
    foodie = _badge(progress, "foodie")
    assert not foodie["earned"] and foodie["progress"] == 1
    assert _badge(progress, "first_step")["earned"]


def test_tien_do_khong_vuot_muc_tieu() -> None:
    """Thanh tiến độ "7/3" trông như lỗi hiển thị."""
    coffee = _badge(checkins.badge_progress(["cafe"] * 7), "coffee_hunter")
    assert coffee["progress"] == coffee["goal"] == 3


def test_huy_hieu_da_sac_dem_so_loai_khong_dem_so_luot() -> None:
    assert not _badge(checkins.badge_progress(["cafe"] * 10), "variety")["earned"]
    variety = _badge(checkins.badge_progress(["cafe", "park", "museum", "bar", "market"]), "variety")
    assert variety["earned"]


def test_id_khong_phai_uuid_tra_not_found_khong_cham_database() -> None:
    """`poi_id` không phải UUID thì psycopg ném lỗi kiểu dữ liệu -> 500."""
    assert checkins.check_in("phien-1", "../../etc", 10.77, 106.70, 5)["status"] == "not_found"


def test_tom_tat_rong_van_co_du_huy_hieu() -> None:
    """Giao diện vẽ danh sách huy hiệu (đã đạt và chưa) ngay cả khi chưa có phiên."""
    empty = checkins.badge_summary_empty()
    assert empty["total"] == 0 and empty["checkins"] == []
    assert len(empty["badges"]) == len(checkins.BADGES)


def test_request_kiem_toa_do() -> None:
    with pytest.raises(ValidationError):
        CheckInRequest(poi_id="11111111-1111-4111-8111-111111111111", latitude=91, longitude=0)
    with pytest.raises(ValidationError):
        CheckInRequest(poi_id="khong-phai-uuid", latitude=10, longitude=106)

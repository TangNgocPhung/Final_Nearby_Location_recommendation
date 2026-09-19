"""Địa điểm đã lưu — phần kiểm được mà không cần database.

Mấy hành vi cần database (ON CONFLICT cập nhật thay vì nhân đôi, một `home`
cho mỗi chủ sở hữu, xoá phải kèm `owner_id`, POI bị xoá thì địa điểm đã lưu
vẫn còn) đã đo trực tiếp trên PostGIS khi dựng tính năng. Ở đây chỉ khoá lại
những ràng buộc thuần Python — chúng phải chặn TRƯỚC khi mở kết nối, vì một
request sai không đáng tốn một kết nối database.
"""

import pytest
from pydantic import ValidationError

from app import saved_places
from app.models import SavedPlaceRequest


def test_kind_la_tap_dong() -> None:
    """Thêm một `kind` mới phải sửa cả CHECK constraint trong migration 0016.
    Danh sách ở hai nơi lệch nhau thì database từ chối, còn API thì không."""
    assert saved_places.KINDS == ("saved", "home", "work")
    assert set(saved_places.DEFAULT_LABELS) == set(saved_places.KINDS)


def test_kind_la_khong_hop_le_thi_tu_choi_truoc_khi_cham_database() -> None:
    with pytest.raises(ValueError, match="kind"):
        saved_places.save_place("phien-1", poi_id="x", kind="favourite")


def test_diem_tu_do_thieu_toa_do_bi_tu_choi_truoc_khi_cham_database() -> None:
    """Không có POI thì toạ độ là thứ DUY NHẤT xác định địa điểm. Thiếu nó mà
    vẫn mở kết nối thì lỗi chỉ lộ ra ở tầng SQL, kèm thông báo khó hiểu."""
    with pytest.raises(ValueError, match="latitude"):
        saved_places.save_place("phien-1", label="Nhà")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("11111111-1111-1111-1111-111111111111", True),
        ("không-phải-uuid", False),
        ("", False),
        (None, False),
    ],
)
def test_is_uuid(value: str | None, expected: bool) -> None:
    assert saved_places.is_uuid(value) is expected


def test_xoa_voi_id_khong_phai_uuid_tra_false_chu_khong_no() -> None:
    """`place_id` đến thẳng từ URL nên người dùng gõ gì cũng được. Không chặn
    ở đây thì psycopg ném lỗi kiểu dữ liệu và API trả 500 thay vì 404."""
    assert saved_places.delete_place("phien-1", "../../etc/passwd") is False


def test_request_phai_co_poi_hoac_toa_do() -> None:
    with pytest.raises(ValidationError):
        SavedPlaceRequest(kind="home", label="Nhà")


def test_request_chi_can_toa_do_la_du() -> None:
    """Đúng tình huống "lưu địa chỉ nhà": nhà không có trong dữ liệu POI."""
    payload = SavedPlaceRequest(latitude=10.7626, longitude=106.6819, kind="home")
    assert payload.poi_id is None
    assert payload.kind == "home"


def test_request_chi_can_poi_la_du() -> None:
    payload = SavedPlaceRequest(poi_id="10000000-0000-0000-0000-000000000029")
    assert payload.latitude is None
    assert payload.kind == "saved"


def test_toa_do_ngoai_dai_bi_tu_choi() -> None:
    with pytest.raises(ValidationError):
        SavedPlaceRequest(latitude=91.0, longitude=106.7)

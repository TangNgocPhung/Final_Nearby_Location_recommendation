"""Admin thêm địa danh — các ràng buộc phải chặn TRƯỚC khi mở kết nối database.

Hành vi cần PostGIS (tạo POI + bài giới thiệu một transaction, chặn trùng theo
tên + khoảng cách, gắn vào POI có sẵn, cache thuyết minh bị xoá) đã đo trên
database test khi dựng tính năng.
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app import landmarks_admin, tts
from app.auth import AuthUser
from app.models import LandmarkStory, NewLandmarkRequest

ADMIN = AuthUser(id="1", username="adm", display_name=None, role="admin", is_active=True)
SOURCE = "https://vi.wikipedia.org/wiki/Dinh_%C4%90%E1%BB%99c_L%E1%BA%ADp"


def _story(**overrides) -> dict:
    return {
        "content_type": "historical",
        "intro": "Địa danh thử nghiệm dùng để kiểm tra luồng admin thêm địa danh.",
        "source": SOURCE,
        **overrides,
    }


def _new(**overrides) -> dict:
    return {
        "name": "Địa danh thử",
        "latitude": 10.77,
        "longitude": 106.69,
        "category": "landmark",
        **_story(),
        **overrides,
    }


def test_bai_hop_le_duoc_nhan() -> None:
    story = LandmarkStory(**_story(historical_events=[{"description": "Sự kiện A", "source": SOURCE}]))
    assert story.historical_events[0].source == SOURCE


@pytest.mark.parametrize("content_type", ["medical", "", "food"])
def test_loai_khong_phai_dia_danh_bi_tu_choi(content_type: str) -> None:
    """Bệnh viện không phải địa danh săn được (xem docstring `explore`)."""
    with pytest.raises(ValidationError):
        LandmarkStory(**_story(content_type=content_type))


@pytest.mark.parametrize("source", ["", "wikipedia", "ftp://x.test/a", "javascript:alert(1)", "https://a b.test"])
def test_nguon_phai_la_url_http(source: str) -> None:
    with pytest.raises(ValidationError):
        LandmarkStory(**_story(source=source))


def test_moi_claim_phai_co_nguon() -> None:
    with pytest.raises(ValidationError):
        LandmarkStory(**_story(historical_events=[{"description": "Không có nguồn"}]))
    with pytest.raises(ValidationError):
        LandmarkStory(**_story(interesting_facts=[{"description": "Nguồn hỏng", "source": "không phải url"}]))


def test_gioi_han_do_dai_va_so_luong() -> None:
    with pytest.raises(ValidationError):
        LandmarkStory(**_story(intro="ngắn"))
    claim = {"description": "Một sự kiện", "source": SOURCE}
    with pytest.raises(ValidationError):
        LandmarkStory(**_story(historical_events=[claim] * 13))


def test_loai_poi_moi_chi_trong_danh_sach_cho_phep() -> None:
    NewLandmarkRequest(**_new(category="museum"))
    with pytest.raises(ValidationError):
        NewLandmarkRequest(**_new(category="restaurant"))


def test_toa_do_ngoai_viet_nam_bi_tu_choi_truoc_khi_mo_ket_noi(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args, **_kwargs):  # pragma: no cover
        raise AssertionError("không được mở kết nối khi toạ độ sai")

    monkeypatch.setattr(landmarks_admin.auth, "_connect", fail)
    # Đảo vĩ độ/kinh độ: (106.7, 10.77) bị pydantic chặn; (40, 100) hợp lệ về miền giá trị
    # nhưng nằm ngoài Việt Nam.
    with pytest.raises(landmarks_admin.LandmarkError, match="ngoài Việt Nam"):
        landmarks_admin.create_landmark(ADMIN, NewLandmarkRequest(**_new(latitude=40, longitude=100)).model_dump())


def test_claim_luu_voi_verified_true_va_bo_khoang_trang() -> None:
    stored = json.loads(
        landmarks_admin._claims_json([{"title": "", "description": "  Mô tả  ", "source": f" {SOURCE} "}])
    )
    assert stored == [{"title": None, "description": "Mô tả", "source": SOURCE, "verified": True}]


def test_xoa_cache_thuyet_minh_cua_dung_poi(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tts, "CACHE_DIR", tmp_path)
    poi, other = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
    for name in (f"{poi}_vi.json", f"{poi}_vi.wav", f"{poi}_en.json", f"{other}_vi.json"):
        (tmp_path / name).write_text("x")
    tts.invalidate(poi)
    assert sorted(path.name for path in tmp_path.iterdir()) == [f"{other}_vi.json"]

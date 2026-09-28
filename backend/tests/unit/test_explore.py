"""Săn địa danh — phần kiểm được không cần database/Ollama.

Hành vi cần database (ON CONFLICT một lượt khám phá / người / POI, ảnh trùng
sha256 là một ảnh, ảnh pending không bao giờ lộ qua /visitor-photos) đã đo trực
tiếp trên PostGIS khi dựng tính năng. Ở đây khoá lại các quy tắc thuần Python:
bán kính, bộ sưu tập, kết luận từ câu trả lời của model, xử lý ảnh.
"""

import base64
import io

import pytest
from PIL import Image

from app import explore


def _jpeg(width: int = 800, height: int = 600, exif_gps: bool = False) -> bytes:
    image = Image.new("RGB", (width, height), (120, 160, 200))
    out = io.BytesIO()
    kwargs = {}
    if exif_gps:
        exif = Image.Exif()
        exif[0x010F] = "PhoneMaker"  # Make
        exif[0x8825] = {2: (10.0, 46.0, 30.0)}  # GPSInfo: vĩ độ nhà riêng
        kwargs["exif"] = exif
    image.save(out, format="JPEG", **kwargs)
    return out.getvalue()


# --- Bán kính ---------------------------------------------------------------------


def test_cong_vien_duoc_ban_kinh_rong_hon_toa_nha() -> None:
    """Toạ độ công viên là tâm khu đất rộng — đứng ở cổng đã cách vài trăm mét."""
    assert explore.discover_radius("park") > explore.discover_radius("landmark")
    assert explore.discover_radius("museum") == explore.DEFAULT_RADIUS_METERS


def test_sai_so_gps_duoc_cong_them_nhung_co_tran() -> None:
    base = explore.discover_radius("landmark")
    assert explore.allowed_distance("landmark", 20) == base + 20
    # Thiết bị báo sai số 2 km không được vì thế mà "khám phá" từ nhà.
    assert explore.allowed_distance("landmark", 2_000) == base + explore.MAX_ACCURACY_ALLOWANCE_METERS
    assert explore.allowed_distance("landmark", None) == base
    assert explore.allowed_distance("landmark", -5) == base


# --- Bộ sưu tập ---------------------------------------------------------------------


def test_moi_dia_danh_deu_thuoc_di_san_sai_gon() -> None:
    for category, content_type in [("museum", "historical"), ("park", "nature"), ("market", "cultural")]:
        assert "di-san-sai-gon" in explore.collections_for(category, content_type)


@pytest.mark.parametrize(
    ("category", "content_type", "expected"),
    [
        ("museum", "historical", {"di-san-sai-gon", "bao-tang", "cong-trinh-lich-su"}),
        ("landmark", "architectural", {"di-san-sai-gon", "cong-trinh-lich-su"}),
        ("park", "historical", {"di-san-sai-gon", "cong-vien-xanh"}),
        ("park", "nature", {"di-san-sai-gon", "cong-vien-xanh"}),
        ("market", "cultural", {"di-san-sai-gon", "nhip-song-sai-gon"}),
    ],
)
def test_quy_tac_bo_suu_tap(category: str, content_type: str, expected: set[str]) -> None:
    assert set(explore.collections_for(category, content_type)) == expected


def test_moi_bo_suu_tap_trong_quy_tac_deu_duoc_khai_bao() -> None:
    """Quy tắc trả một id không có trong COLLECTIONS thì tiến độ bộ đó biến mất
    lặng lẽ khỏi giao diện."""
    produced = set()
    for category in ("museum", "landmark", "park", "theme_park", "market", "post_office"):
        for content_type in explore.HUNTABLE_CONTENT_TYPES:
            produced.update(explore.collections_for(category, content_type))
    assert produced <= set(explore.COLLECTION_IDS)


def test_benh_vien_khong_phai_dia_danh_san() -> None:
    assert "medical" not in explore.HUNTABLE_CONTENT_TYPES


def test_tien_do_bo_suu_tap() -> None:
    places = [
        {"collections": ["di-san-sai-gon", "bao-tang"], "discovered": True},
        {"collections": ["di-san-sai-gon", "bao-tang"], "discovered": False},
        {"collections": ["di-san-sai-gon", "cong-vien-xanh"], "discovered": True},
    ]
    progress = {item["id"]: item for item in explore.collection_progress(places)}
    assert progress["di-san-sai-gon"]["total"] == 3
    assert progress["di-san-sai-gon"]["discovered"] == 2
    assert progress["cong-vien-xanh"]["completed"] is True
    assert progress["bao-tang"]["completed"] is False
    # Bộ không có địa danh nào thì không hiện "0/0".
    assert "nhip-song-sai-gon" not in progress


def test_teaser_khong_lo_noi_dung() -> None:
    text = explore.teaser("historical", ["Sự kiện bí mật"], ["Điều bí mật", "Điều thứ hai"])
    assert text == "Câu chuyện lịch sử · 1 sự kiện · 2 điều thú vị"
    assert "bí mật" not in text


# --- Kết luận từ model thị giác -----------------------------------------------------


def test_doc_json_boc_trong_markdown() -> None:
    content = 'Kết quả:\n```json\n{"match": "yes", "confidence": 0.9, "seen": "Mặt tiền nhà thờ gạch đỏ"}\n```'
    assert explore.parse_verdict(content) == {
        "match": "yes",
        "confidence": 0.9,
        "seen": "Mặt tiền nhà thờ gạch đỏ",
    }


@pytest.mark.parametrize(
    "content",
    [None, "", "không có json", '{"match": "maybe"}', "[1, 2]", '{"match": "yes", "confidence": }'],
)
def test_cau_tra_loi_hong_thi_none(content: str | None) -> None:
    assert explore.parse_verdict(content) is None


def test_do_tin_cay_bi_kep_ve_0_1() -> None:
    assert explore.parse_verdict('{"match": "yes", "confidence": 7}')["confidence"] == 1.0
    assert explore.parse_verdict('{"match": "no", "confidence": "abc"}')["confidence"] == 0.0


@pytest.mark.parametrize(
    ("verdict", "expected"),
    [
        ({"match": "yes", "confidence": 0.8}, "verified"),
        ({"match": "yes", "confidence": 0.3}, "pending"),
        ({"match": "no", "confidence": 0.9}, "rejected"),
        # "Không" nhưng không chắc: vị trí đã đúng, không để model 4B tự bác.
        ({"match": "no", "confidence": 0.4}, "pending"),
        ({"match": "unsure", "confidence": 0.99}, "pending"),
        (None, "pending"),
    ],
)
def test_ket_luan_anh(verdict: dict | None, expected: str) -> None:
    assert explore.decide_photo(verdict) == expected


def test_model_khong_chay_thi_khong_goi_mang(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(explore.settings, "ollama_url", "")

    def fail(*_args, **_kwargs):  # pragma: no cover - chỉ chạy khi có lỗi
        raise AssertionError("không được gọi Ollama khi chưa cấu hình")

    monkeypatch.setattr(explore.urllib.request, "urlopen", fail)
    assert explore.check_photo(b"x", "Dinh Độc Lập", None, "landmark") is None


# --- Ảnh ------------------------------------------------------------------------------


def test_giai_ma_data_url() -> None:
    raw = _jpeg()
    encoded = "data:image/jpeg;base64," + base64.b64encode(raw).decode()
    assert explore.decode_upload(encoded) == raw


@pytest.mark.parametrize("payload", ["không phải base64!!", ""])
def test_base64_hong_bi_tu_choi(payload: str) -> None:
    with pytest.raises(ValueError):
        explore.decode_upload(payload)


def test_anh_qua_lon_bi_tu_choi_truoc_khi_giai_ma() -> None:
    with pytest.raises(ValueError, match="quá lớn"):
        explore.decode_upload("A" * (explore.MAX_UPLOAD_BYTES * 2))


def test_tep_khong_phai_anh_bi_tu_choi() -> None:
    with pytest.raises(ValueError, match="không phải ảnh"):
        explore.prepare_photo(b"%PDF-1.4 day la file pdf gia duoi jpg")


def test_anh_qua_nho_bi_tu_choi() -> None:
    with pytest.raises(ValueError, match="quá nhỏ"):
        explore.prepare_photo(_jpeg(120, 90))


def test_anh_duoc_thu_nho_va_co_thumbnail() -> None:
    photo = explore.prepare_photo(_jpeg(4000, 3000))
    assert max(photo["width"], photo["height"]) == explore.MAX_IMAGE_SIDE
    thumb = Image.open(io.BytesIO(photo["thumbnail"]))
    assert max(thumb.size) <= explore.THUMB_SIDE
    assert len(photo["sha256"]) == 64


def test_exif_gps_bi_xoa_truoc_khi_luu() -> None:
    """Ảnh chọn từ thư viện có thể mang toạ độ nhà riêng — không được lưu lại."""
    original = _jpeg(exif_gps=True)
    assert Image.open(io.BytesIO(original)).getexif().get(0x8825) is not None
    stored = Image.open(io.BytesIO(explore.prepare_photo(original)["image"]))
    assert not stored.getexif()

"""Chế độ giọng nói — hiểu câu nói và cả luồng hội thoại, không cần database.

Các hàm truy cập dữ liệu (tìm kiếm, có bài thuyết minh không, đang ở đâu) được
tiêm vào ``respond`` nên cả luồng tìm → chọn → dẫn đường chạy được trong test.
"""

import pytest

from app import voice

HERE = (10.7757, 106.7009)

PHO = [
    {"id": "p1", "name": "Phở Nhà Mình", "address": "38 Pasteur", "latitude": 10.7748, "longitude": 106.6996,
     "openNow": True, "closesInMinutes": 30, "rating": 4.6},
    {"id": "p2", "name": "Phở Hòa", "address": "260C Pasteur", "latitude": 10.7890, "longitude": 106.6910,
     "openNow": None, "rating": None},
    {"id": "p3", "name": "Phở Lệ", "address": "413 Nguyễn Trãi", "latitude": 10.7560, "longitude": 106.6780,
     "openNow": False, "opensInMinutes": 45, "rating": 4.2},
    {"id": "p4", "name": "Phở Bắc Hải", "address": "Q.1", "latitude": 10.7770, "longitude": 106.7020,
     "openNow": True, "rating": 4.0},
]


def _turn(text: str, state: dict | None = None, results: list | None = None, story: bool = False):
    return voice.respond(
        text,
        *HERE,
        state,
        search=lambda _q, _lat, _lng: list(results if results is not None else PHO),
        has_story=lambda _id: story,
        where=lambda _lat, _lng: {"match": {"name": "Chợ Bến Thành", "address": "Lê Lợi, Q.1", "distanceMeters": 12}},
    )


# --- Hiểu câu nói -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [("số hai", 2), ("chọn cái thứ ba", 3), ("2", 2), ("số mười một", 11), ("đầu tiên", 1), ("thứ tư", 4)],
)
def test_so_thu_tu(text: str, expected: int) -> None:
    assert voice.ordinal(text) == expected


@pytest.mark.parametrize("text", ["chùa bà", "quán gần nhất", "bay lên", "tắm"])
def test_khong_nham_tu_thuong_thanh_so(text: str) -> None:
    """Bỏ dấu thì "bà" → "ba" (3), "tắm" → "tam" (8)... — phải so trên chữ có dấu."""
    assert voice.ordinal(text) is None


def test_trong_danh_sach_noi_so_la_chon() -> None:
    assert voice.parse("số hai", "results") == {"intent": "select", "index": 2}


def test_chua_co_danh_sach_thi_so_la_mot_phan_cau_tim() -> None:
    assert voice.parse("quán ba miền", "idle")["intent"] == "search"


def test_dung_khac_dung() -> None:
    """"đúng rồi" bỏ dấu cũng là "dung roi" — không được làm dừng dẫn đường."""
    assert voice.parse("dừng lại", "navigating")["intent"] == "stop"
    assert voice.parse("đúng rồi", "navigating")["intent"] != "stop"


def test_toi_chua_an_la_tim_kiem_khong_phai_hoi_duong() -> None:
    assert voice.parse("tôi chưa ăn sáng", "idle")["intent"] == "search"


def test_di_don_le_la_lenh_di_nhung_tim_quan_di_thi_khong() -> None:
    assert voice.parse("đi", "selected")["intent"] == "navigate"
    assert voice.parse("số hai đi", "results") == {"intent": "navigate", "index": 2}
    assert voice.parse("tìm quán phở đi", "results")["intent"] == "search"


def test_chon_bang_ten() -> None:
    assert voice.parse("phở hòa", "results", [p["name"] for p in PHO]) == {"intent": "select", "index": 2}


def test_bo_tu_dem_nhung_giu_dau_va_vi_tri() -> None:
    assert voice.clean_query("tìm cho tôi quán phở gần đây") == "quán phở"
    assert voice.clean_query("cà phê gần Bến Thành") == "cà phê gần Bến Thành"


# --- Soạn câu nói -------------------------------------------------------------------


def test_khoang_cach_doc_tron() -> None:
    assert voice.say_distance(143) == "140 mét"
    assert voice.say_distance(4) == "10 mét"
    assert voice.say_distance(1500) == "1,5 ki lô mét"
    assert voice.say_distance(2000) == "2 ki lô mét"


def test_khong_co_gio_mo_cua_thi_khong_noi_dang_mo() -> None:
    assert voice.say_open({"openNow": None}) == ""
    assert voice.say_open({"openNow": True, "closesInMinutes": 20}) == "đang mở cửa, sắp đóng sau 20 phút"
    assert voice.say_open({"openNow": False, "opensInMinutes": 45}) == "đang đóng cửa, mở lại sau 45 phút"


def test_huong_la_ban() -> None:
    assert voice.compass_word(0) == "bắc"
    assert voice.compass_word(95) == "đông"
    assert voice.compass_word(225) == "tây nam"
    assert voice.compass_word(350) == "bắc"


# --- Cả luồng hội thoại -------------------------------------------------------------


def test_luong_tim_chon_dan_duong() -> None:
    first = _turn("tìm quán phở gần đây")
    assert first["state"]["stage"] == "results"
    assert "Tìm thấy 4 địa điểm" in first["speech"]
    assert "Số 1: Phở Nhà Mình" in first["speech"]
    assert "Số 4" not in first["speech"]  # mỗi lượt đọc PAGE_SIZE kết quả
    assert "nói “thêm”" in first["speech"]

    more = _turn("thêm", first["state"])
    assert "Số 4: Phở Bắc Hải" in more["speech"]

    chosen = _turn("số hai", more["state"])
    assert chosen["state"]["stage"] == "selected"
    assert chosen["state"]["selected"]["id"] == "p2"
    assert "260C Pasteur" in chosen["speech"]
    assert "thuyết minh" not in chosen["speech"]  # POI không có bài thuyết minh

    go = _turn("dẫn đường", chosen["state"])
    assert go["action"]["type"] == "navigate"
    assert go["action"]["poiId"] == "p2"
    assert go["state"]["stage"] == "navigating"

    stop = _turn("dừng", go["state"])
    assert stop["action"] == {"type": "stop_navigation"}
    assert stop["state"]["stage"] == "selected"


def test_khoang_cach_tinh_tu_nguoi_dung() -> None:
    result = _turn("phở")
    distances = [poi["distanceMeters"] for poi in result["state"]["results"]]
    assert distances[0] == round(voice.haversine_m(*HERE, PHO[0]["latitude"], PHO[0]["longitude"]))
    # State chỉ mang các trường cần thiết, không cả trăm trường của kết quả xếp hạng.
    assert set(result["state"]["results"][0]) <= {
        "id", "name", "address", "latitude", "longitude", "distanceMeters", "openNow",
        "closesInMinutes", "opensInMinutes", "rating", "categoryLabel",
    }


def test_so_ngoai_danh_sach() -> None:
    state = _turn("phở")["state"]
    reply = _turn("số chín", state)
    assert "chỉ có 4 địa điểm" in reply["speech"]
    assert reply["state"]["stage"] == "results"


def test_khong_tim_thay() -> None:
    reply = _turn("tiệm sửa đồng hồ", results=[])
    assert "Không tìm thấy" in reply["speech"]
    assert reply["state"]["stage"] == "idle"


def test_nhac_lai_cau_vua_noi() -> None:
    first = _turn("phở")
    assert _turn("nhắc lại", first["state"])["speech"] == first["speech"]


def test_thuyet_minh_chi_khi_co_bai() -> None:
    selected = _turn("số một", _turn("phở")["state"], story=True)
    assert "“thuyết minh”" in selected["speech"]
    narrate = _turn("thuyết minh", selected["state"], story=True)
    assert narrate["action"] == {"type": "narrate", "poiId": "p1", "name": "Phở Nhà Mình"}
    assert _turn("thuyết minh", selected["state"], story=False)["action"] is None


def test_toi_dang_o_dau() -> None:
    assert _turn("tôi đang ở đâu")["speech"] == "Bạn đang ngay tại Chợ Bến Thành, Lê Lợi, Q.1."


def test_con_bao_xa_khi_dang_dan_duong() -> None:
    go = _turn("dẫn đường", _turn("số một", _turn("phở")["state"])["state"])
    reply = _turn("còn bao xa", go["state"])
    assert "Còn khoảng" in reply["speech"] and "Phở Nhà Mình" in reply["speech"]


def test_thoat() -> None:
    assert _turn("thoát")["action"] == {"type": "exit"}


def test_state_la_tu_client_gui_len_nen_phai_chiu_duoc_state_rong_hoac_la() -> None:
    assert _turn("thêm", {"stage": "không-hợp-lệ"})["intent"] == "search"
    assert _turn("số một", {})["intent"] == "search"

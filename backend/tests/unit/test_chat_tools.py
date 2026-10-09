"""Chat có ngữ cảnh — bộ lọc, câu hỏi tiếp và chọn công cụ, tất cả bằng luật."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app import chat_tools

NOW = datetime(2026, 10, 10, 15, 0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))


def _poi(index: int, **extra) -> dict:
    return {
        "id": f"id-{index}",
        "name": f"Quán Số {index}",
        "latitude": 10.77 + index * 0.001,
        "longitude": 106.70,
        "distanceMeters": 100 * index,
        **extra,
    }


def _last(count: int = 8, **extra) -> dict:
    return {"kind": "search", "query": "cà phê", "radius": 3000, "results": [_poi(i) for i in range(1, count + 1)], "page_start": 0, **extra}


# --- Bộ lọc ---------------------------------------------------------------------


def test_cat_cum_loc_khoi_cau_tim_kiem_giu_dau():
    filters = chat_tools.extract_filters("Quán cà phê có wifi đang mở cửa gần đây")
    assert set(filters.keys) == {"wifi", "open_now"}
    assert filters.text == "Quán cà phê gần đây"


def test_mo_khuya_khong_bi_hieu_thanh_dang_mo():
    filters = chat_tools.extract_filters("quán nào còn mở khuya")
    assert filters.keys == ("open_late",)


def test_cho_dau_xe_o_to_cat_ca_loai_xe():
    filters = chat_tools.extract_filters("nhà hàng có chỗ đậu xe ô tô")
    assert filters.keys == ("parking",)
    assert filters.text == "nhà hàng"


def test_dieu_kien_chua_du_du_lieu_thi_bao_ro():
    filters = chat_tools.extract_filters("quán phở giá rẻ")
    assert filters.keys == ()
    assert filters.unsupported == ("cheap",)
    assert filters.text == "quán phở"
    assert "chưa đủ để lọc theo giá rẻ" in chat_tools.filter_note((), filters.unsupported)


def test_cau_khong_co_loc_giu_nguyen():
    filters = chat_tools.extract_filters("Quán cà phê yên tĩnh")
    assert not filters
    assert filters.text == "Quán cà phê yên tĩnh"


def test_loc_chi_giu_noi_chac_chan_va_dem_cho_thieu_du_lieu():
    results = [
        {"id": "a", "openNow": True, "amenities": {"internet_access": "wlan"}},
        {"id": "b", "openNow": True, "amenities": {"internet_access": "no"}},
        {"id": "c", "openNow": None, "amenities": {}},
        {"id": "d", "openNow": False, "amenities": {"internet_access": "wlan"}},
    ]
    kept, unknown = chat_tools.apply_filters(results, ("open_now", "wifi"), NOW)
    assert [poi["id"] for poi in kept] == ["a"]
    assert unknown == 1
    note = chat_tools.filter_note(("open_now", "wifi"), (), unknown)
    assert "1 chỗ khác chưa có dữ liệu" in note


def test_mo_khuya_xet_gio_22h30_toi_nay():
    late = {"id": "late", "openingHours": {"parseStatus": "parsed", "periods": [{"days": [5], "opens": "18:00", "closes": "23:59"}]}}
    early = {"id": "early", "openingHours": {"parseStatus": "parsed", "periods": [{"days": [5], "opens": "07:00", "closes": "21:00"}]}}
    kept, _ = chat_tools.apply_filters([late, early], ("open_late",), NOW)
    assert [poi["id"] for poi in kept] == ["late"]


# --- Câu hỏi tiếp ---------------------------------------------------------------


def test_so_thu_tu_tro_vao_the_dang_hien_thi():
    plan = chat_tools.follow_up("Số 2 mấy giờ đóng cửa?", _last(), 10.77, 106.70)
    assert plan["type"] == "answer"
    assert plan["focus"] == "id-2"
    assert plan["question"] == "hours"


def test_so_thu_tu_tinh_tren_trang_dang_xem():
    plan = chat_tools.follow_up("cái thứ hai", _last(page_start=5), 10.77, 106.70)
    assert plan["focus"] == "id-7"


def test_chi_duong_tra_kem_nut_chi_duong():
    plan = chat_tools.follow_up("chỉ đường tới số 1", _last(), 10.77, 106.70)
    assert plan["directions"] == {"poiId": "id-1", "name": "Quán Số 1"}
    assert "Chỉ đường" in plan["reply"]


def test_quan_1_khong_phai_so_thu_tu():
    # Bỏ dấu thì "Quận 1" = "quan 1" — không được hiểu là "quán số 1".
    assert chat_tools._ordinal("cafe quan 1", 5) is None


def test_nhac_ten_quan_trong_danh_sach():
    last = _last()
    last["results"][2]["name"] = "Highlands Coffee Nguyễn Huệ"
    plan = chat_tools.follow_up("Highlands Coffee ở đâu?", last, 10.77, 106.70)
    assert plan["focus"] == "id-3"
    assert plan["question"] == "address"


def test_quan_do_tro_vao_dia_diem_vua_hoi():
    plan = chat_tools.follow_up("chỉ đường tới đó", _last(focus="id-4"), 10.77, 106.70)
    assert plan["focus"] == "id-4"


def test_con_cho_khac_sang_trang_ke():
    plan = chat_tools.follow_up("Còn chỗ khác không?", _last(), 10.77, 106.70)
    assert plan["type"] == "page"
    assert [poi["id"] for poi in plan["results"]] == ["id-6", "id-7", "id-8"]


def test_het_danh_sach_thi_goi_y_mo_rong():
    plan = chat_tools.follow_up("còn chỗ khác không", _last(count=3), 10.77, 106.70)
    assert plan["type"] == "clarify"
    assert "xa hơn" in plan["reply"]


def test_gan_hon_xep_lai_theo_khoang_cach():
    last = _last(count=3)
    last["results"].reverse()
    plan = chat_tools.follow_up("gần hơn", last, 10.77, 106.70)
    assert plan["type"] == "reorder"
    assert plan["results"][0]["id"] == "id-1"


def test_xa_hon_chay_lai_voi_ban_kinh_gap_doi():
    plan = chat_tools.follow_up("xa hơn nữa", _last(), 10.77, 106.70)
    assert plan == {"type": "rerun", "radius": 6000}


def test_chi_noi_dieu_kien_loc_thi_loc_lai_truy_van_cu():
    plan = chat_tools.follow_up("Chỗ nào đang mở cửa?", _last(filters=["wifi"]), 10.77, 106.70)
    assert plan["type"] == "rerun"
    assert plan["filters"] == ("wifi", "open_now")


def test_hoi_gio_ma_khong_noi_cho_nao_thi_hoi_lai():
    plan = chat_tools.follow_up("mấy giờ đóng cửa?", _last(), 10.77, 106.70)
    assert plan["type"] == "clarify"


def test_cau_co_chu_de_moi_la_tim_moi():
    assert chat_tools.follow_up("còn quán phở nào khác không", _last(), 10.77, 106.70) is None
    assert chat_tools.follow_up("cây xăng gần nhất", _last(), 10.77, 106.70) is None
    assert chat_tools.follow_up("số 2", None, 10.77, 106.70) is None


def test_tra_loi_gio_mo_cua_tu_du_lieu_that():
    poi = {"name": "Quán A", "openNow": True, "closesInMinutes": 90, "openingRaw": "Mo-Su 07:00-16:30"}
    reply = chat_tools.answer_about(poi, "hours", NOW)
    assert "đóng cửa lúc 16:30" in reply
    assert "1 giờ 30 phút" in reply
    assert "chưa có giờ" in chat_tools.answer_about({"name": "Quán B"}, "hours", NOW)


# --- Công cụ chuyên biệt --------------------------------------------------------


def test_chon_cong_cu_theo_cau_hoi():
    assert chat_tools.detect_tool("cây xăng Petrolimex gần nhất")["params"]["brand"] == "petrolimex"
    assert chat_tools.detect_tool("đổ xăng ô tô")["params"]["vehicle"] == "car"
    assert chat_tools.detect_tool("trạm sạc vinfast cho ô tô")["params"] == {"vehicle": "car", "network": "vinfast", "open_now": False}
    assert chat_tools.detect_tool("tìm nhà vệ sinh miễn phí")["params"]["free_only"] is True
    assert chat_tools.detect_tool("Circle K gần đây")["params"]["brand"] == "circle_k"
    assert chat_tools.detect_tool("chỗ gửi xe ô tô 3 tiếng")["params"] == {"vehicle": "car", "minutes": 180}
    assert chat_tools.detect_tool("hôm nay trời có mưa không")["tool"] == "weather"


def test_khong_chuyen_cong_cu_khi_cau_tim_loai_khac():
    # "có chỗ đậu xe" là bộ lọc của quán, không phải tìm bãi gửi xe.
    message = "quán cà phê có chỗ đậu xe"
    assert chat_tools.detect_tool(message, chat_tools.extract_filters(message)) is None
    assert chat_tools.detect_tool("quán cà phê gần cây xăng") is None
    # Bỏ dấu "mua" ≠ "mưa".
    assert chat_tools.detect_tool("chỗ nào có mua sim") is None
    assert chat_tools.detect_tool("điện thoại hết pin") is None


def test_ban_kinh_trong_cau_bi_kep_theo_cong_cu():
    tool = chat_tools.detect_tool("gửi xe trong 20km", radius_m=20_000)
    assert tool["params"]["radius"] == 5_000


def test_bo_loc_cong_cu_khong_ho_tro_thi_bao_bo_qua():
    params, ignored = chat_tools.refine_tool_params("fuel", {"vehicle": "motorbike"}, ("open_now", "wifi"))
    assert params["open_now"] is True
    assert ignored == ("wifi",)


def test_the_cay_xang_co_thoi_gian_va_trang_thai():
    found = {
        "vehicle": "motorbike",
        "results": [{"id": "x", "name": "Petrolimex 12", "brand": "Petrolimex", "driveMinutes": 4, "fuels": ["RON 95", "E5"], "hours": {"openNow": True}, "distanceMeters": 900}],
    }
    card = chat_tools._fuel_cards(found)[0]
    assert card["detail"] == "4 phút xe máy · RON 95, E5 · Đang mở"
    assert chat_tools.compact(card)["openNow"] is True
    assert chat_tools.listing([card], "Cây xăng gần bạn nhất:") == "Cây xăng gần bạn nhất: Petrolimex 12 (4 phút)."


def test_goi_y_cau_tiep_tu_hieu_duoc():
    # Mọi câu gợi ý phải đi đúng đường hỏi tiếp, không rơi về tìm mới.
    for reply in chat_tools.quick_replies("search", 8):
        assert chat_tools.follow_up(reply, _last(), 10.77, 106.70) is not None, reply


def test_loc_tren_ten_loai_thi_di_duong_nhanh_theo_loai():
    assert chat_tools.plain_category(chat_tools.extract_filters("Cà phê có wifi đang mở cửa")) == "cafe"
    # Còn ý khác ngoài tên loại thì để BM25/Vector đọc.
    assert chat_tools.plain_category(chat_tools.extract_filters("cà phê yên tĩnh có wifi")) is None


def test_the_bai_xe_va_tram_sac():
    parking_found = {
        "minutes": 180,
        "results": [
            {"id": "p1", "name": "Bãi A", "walkMinutes": 2, "price": {"estimatedCost": 0, "tier": "openstreetmap"}, "hours": {}},
            {"id": "p2", "name": "Bãi B", "walkMinutes": 3, "price": {"estimatedCost": 45000, "tier": "reference"}, "hours": {}},
        ],
    }
    first, second = chat_tools._parking_cards(parking_found)
    assert first["detail"] == "2 phút đi bộ · Miễn phí"
    assert second["detail"] == "3 phút đi bộ · ~45.000đ cho 3 giờ (tham khảo)"
    charging_found = {"mode": "motorbike", "results": [{"id": "c", "name": "Trạm", "network": "VinFast / V-Green", "driveMinutes": 2, "hours": {}}]}
    assert chat_tools._charging_cards(charging_found)[0]["categoryLabel"] == "Trạm sạc VinFast / V-Green"

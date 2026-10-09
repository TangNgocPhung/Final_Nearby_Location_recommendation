"""Tìm cửa hàng tiện lợi — nhận chuỗi theo thẻ hoặc tên, và lọc."""

from app import convenience


def _store(code: str, open_now: bool | None = None) -> dict:
    return {"brandCode": code, "hours": {"openNow": open_now}}


def test_nhan_chuoi_theo_the_hoac_ten() -> None:
    assert convenience.chain_of("Circle K", {}) == ("circle_k", "Circle K")
    assert convenience.chain_of("Cửa hàng", {"brand": "FamilyMart"}) == ("familymart", "FamilyMart")
    # Dấu gạch, dấu nháy, dấu chấm trong tên chuỗi không làm trượt.
    assert convenience.chain_of("7-Eleven Lê Lợi", {}) == ("seven_eleven", "7-Eleven")
    assert convenience.chain_of("B's Mart", {}) == ("bsmart", "B's mart")
    assert convenience.chain_of("Co.op Food Hồng Bàng", {}) == ("coop_food", "Co.op Food")
    assert convenience.chain_of("Bách Hóa XANH", {}) == ("bach_hoa_xanh", "Bách Hóa Xanh")
    # VinMart+ đã đổi tên thành WinMart+ — cùng một chuỗi.
    assert convenience.chain_of("VinMart+", {}) == ("winmart", "WinMart+")
    # "Bách hóa" trơn là tạp hoá, không phải Bách Hóa Xanh.
    assert convenience.chain_of("Bách hóa Thanh Hương", {}) == ("other", None)
    assert convenience.chain_of("Tạp hóa cô Mai", {}) == ("other", None)


def test_loc_chuoi_va_dang_mo() -> None:
    stores = [_store("circle_k", True), _store("gs25", False), _store("other")]
    assert convenience.filter_stores(stores, brand="circle_k") == [stores[0]]
    assert convenience.filter_stores(stores, brand="chain") == stores[:2]
    assert convenience.filter_stores(stores, brand="other") == [stores[2]]
    # "Đang mở" chỉ loại cửa hàng chắc chắn đóng — chưa rõ giờ vẫn giữ.
    assert convenience.filter_stores(stores, open_now=True) == [stores[0], stores[2]]


def test_bo_chuoi_do_gia_dung_bi_gan_variety_store() -> None:
    assert convenience.is_convenience("Miniso", {"shop": "variety_store", "brand": "Miniso"}) is False
    assert convenience.is_convenience("Cửa hàng", {"brand": "Daiso"}) is False
    assert convenience.is_convenience("Tạp hóa cô Mai", {"shop": "variety_store"}) is True
    assert convenience.is_convenience("Circle K", {}) is True

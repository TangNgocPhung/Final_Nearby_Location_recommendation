"""Tìm nhà vệ sinh — nguồn, phí, lọc, và nhập WC không tên từ OSM."""

from app import poi_import, toilets
from app.poi_features import normalize_osm_element


def _item(kind: str, fee: bool | None = None, wheelchair: str | None = None, open_now: bool | None = None) -> dict:
    return {"kind": kind, "fee": fee, "wheelchair": wheelchair, "hours": {"openNow": open_now}}


def test_nguon_theo_loai_dia_diem() -> None:
    assert toilets.kind_of("toilets") == "public"
    assert toilets.kind_of("fuel") == "fuel"
    assert toilets.kind_of("shopping_mall", "Saigon Centre", {"shop": "mall"}) == "mall"
    assert toilets.kind_of("cafe", "Highlands", {"toilets": "yes"}) == "venue"
    # Không ghi toilets=yes thì không nhận là nơi có WC.
    assert toilets.kind_of("cafe", "Highlands", {}) is None


def test_department_store_chi_nhan_bach_hoa_lon_that() -> None:
    """`shop=department_store` ở VN phần lớn là tạp hoá — không phải TTTM có WC."""
    dep = {"shop": "department_store"}
    assert toilets.kind_of("shopping_mall", "Lotte Department Store", dep) == "mall"
    assert toilets.kind_of("shopping_mall", "Trung tâm Thương mại Thủ Đức", dep) == "mall"
    assert toilets.kind_of("shopping_mall", "Tiffany & Co. Vietnam", dep) is None
    assert toilets.kind_of("shopping_mall", "Tạp hóa cô Mai", dep) is None
    # Tạp hoá mà ghi rõ có WC thì vẫn nhận, nhưng là "có WC cho khách".
    assert toilets.kind_of("shopping_mall", "Tạp hóa cô Mai", {**dep, "toilets": "yes"}) == "venue"


def test_phi_tu_the_fee_hoac_charge() -> None:
    assert toilets.fee_of({"fee": "no"}) is False
    assert toilets.fee_of({"fee": "yes"}) is True
    assert toilets.fee_of({"charge": "2000 VND"}) is True
    assert toilets.fee_of({}) is None


def test_loc_chi_bo_noi_chac_chan_khong_dat() -> None:
    items = [
        _item("public", fee=False, wheelchair="yes", open_now=True),
        _item("public", fee=True, wheelchair="no", open_now=False),
        _item("fuel"),
    ]
    assert toilets.filter_toilets(items, source="public") == items[:2]
    # Chưa rõ phí / lối xe lăn / giờ thì vẫn giữ — đa số WC không ghi.
    assert toilets.filter_toilets(items, free_only=True) == [items[0], items[2]]
    assert toilets.filter_toilets(items, wheelchair=True) == [items[0], items[2]]
    assert toilets.filter_toilets(items, open_now=True) == [items[0], items[2]]


def test_nhap_wc_khong_ten_va_bo_wc_rieng() -> None:
    element = {"type": "node", "id": 1, "lat": 10.77, "lon": 106.69, "tags": {"amenity": "toilets", "fee": "no"}}
    poi = normalize_osm_element(element)
    assert poi is not None
    assert (poi["name"], poi["category"], poi["category_label"]) == ("Nhà vệ sinh công cộng", "toilets", "Nhà vệ sinh")
    assert poi["generated_name"] is True
    private = {**element, "tags": {"amenity": "toilets", "access": "private"}}
    assert normalize_osm_element(private) is None
    # Truy vấn Overpass đầy đủ lấy cả WC không tên; truy vấn bổ sung chỉ lấy một loại.
    bbox = (10.7, 106.6, 10.9, 106.82)
    assert "toilets" in poi_import.build_overpass_query(bbox)
    assert '"amenity"="toilets"' in poi_import.build_amenity_query(bbox, "toilets")

"""Tìm trạm xăng — nhận hãng, loại xăng, lọc, và tên đường làm địa chỉ ước lượng."""

from app import directions, fuel


def _station(code: str, open_now: bool | None = None) -> dict:
    return {"brandCode": code, "hours": {"openNow": open_now}}


def test_nhan_hang_theo_the_hoac_ten_tram() -> None:
    assert fuel.brand_of("Cây xăng", {"brand": "Petrolimex"}) == ("petrolimex", "Petrolimex")
    assert fuel.brand_of("Cửa hàng xăng dầu", {"operator": "PV Oil"}) == ("pvoil", "PVOIL")
    # Không có thẻ brand — nhận theo tên, cả khi có dấu/khoảng trắng.
    assert fuel.brand_of("Trạm xăng dầu Comeco số 4", {}) == ("comeco", "Comeco")
    assert fuel.brand_of("Xăng dầu Sài Gòn Petro", {}) == ("saigon_petro", "Saigon Petro")
    assert fuel.brand_of("Cua Hang Xang Dau So 5", {"operator": "DNTN Ngoc Long"}) == ("other", "DNTN Ngoc Long")
    assert fuel.brand_of("Cây xăng", {}) == ("other", None)


def test_loai_xang_tu_the_fuel() -> None:
    tags = {"fuel:octane_95": "yes", "fuel:octane_92": "no", "fuel:diesel": "yes", "fuel:e5": "yes"}
    assert fuel.fuels_of(tags) == ["RON 95", "E5", "Dầu DO"]
    assert fuel.fuels_of({}) == []


def test_loc_hang_va_dang_mo() -> None:
    stations = [_station("petrolimex", True), _station("pvoil", False), _station("other")]
    assert fuel.filter_stations(stations, brand="petrolimex") == [stations[0]]
    assert fuel.filter_stations(stations, brand="other") == [stations[2]]
    # "Đang mở" chỉ loại trạm chắc chắn đóng — chưa rõ giờ vẫn giữ.
    assert fuel.filter_stations(stations, open_now=True) == [stations[0], stations[2]]


def test_ten_duong_tu_osrm_nearest() -> None:
    waypoints = [
        {"name": "Nguyễn Thị Nhỏ", "distance": 20.8},
        {"name": "", "distance": 21.0},  # lối vào không tên — bỏ
        {"name": "Lê Quang Sung", "distance": 22.0},
        {"name": "Lê Quang Sung", "distance": 22.1},
    ]
    assert directions.streets_from_waypoints(waypoints) == {
        "streets": ["Nguyễn Thị Nhỏ", "Lê Quang Sung"],
        "distanceMeters": 21,
    }
    # Tên hẻm đã chứa tên đường chính — không thành "góc" của chính nó.
    hem = [{"name": "Hẻm 702 Hồng Bàng", "distance": 12.0}, {"name": "Hồng Bàng", "distance": 14.0}]
    assert directions.streets_from_waypoints(hem)["streets"] == ["Hẻm 702 Hồng Bàng"]
    # Đường quá xa thì không nhận là đường của địa điểm.
    assert directions.streets_from_waypoints([{"name": "Xa lộ Hà Nội", "distance": 300.0}]) is None
    assert directions.streets_from_waypoints([]) is None

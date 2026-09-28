"""Tìm trạm sạc — lọc theo loại xe/mạng sạc/giờ mở và gắn thời gian chạy xe."""

from app import charging


def _station(name: str, operator: str | None = None, motorbike: str = "unknown", car: str = "unknown",
             open_now: bool | None = None, distance: float = 1000.0) -> dict:
    return {
        "name": name,
        "operator": operator,
        "vehicles": {"motorbike": motorbike, "car": car, "bicycle": "unknown"},
        "hours": {"openNow": open_now},
        "distanceMeters": distance,
        "latitude": 10.77,
        "longitude": 106.70,
    }


def test_nhan_ra_vinfast_theo_operator_hoac_ten() -> None:
    assert charging.network_of(_station("Trạm sạc", operator="VinFast")) == "VinFast / V-Green"
    assert charging.network_of(_station("Trạm sạc V-GREEN Lê Lợi")) == "VinFast / V-Green"
    assert charging.network_of(_station("EV One Q7", operator="EV One")) == "EV One"
    assert charging.network_of(_station("Trạm sạc xe điện")) is None


def test_loai_xe_chua_ro_van_giu_chi_loai_khi_du_lieu_noi_khong() -> None:
    stations = [
        _station("A", car="no"),
        _station("B", car="yes"),
        _station("C"),  # chưa rõ
    ]
    assert [s["name"] for s in charging.filter_stations(stations, vehicle="car")] == ["B", "C"]
    assert len(charging.filter_stations(stations, vehicle="any")) == 3


def test_loc_mang_sac() -> None:
    stations = [_station("VF", operator="VinFast"), _station("Khác", operator="EV One"), _station("Không tên")]
    assert [s["name"] for s in charging.filter_stations(stations, network="vinfast")] == ["VF"]
    assert [s["name"] for s in charging.filter_stations(stations, network="other")] == ["Khác", "Không tên"]


def test_dang_mo_chi_loai_tram_chac_chan_dong() -> None:
    stations = [_station("Đóng", open_now=False), _station("Mở", open_now=True), _station("Chưa rõ giờ")]
    assert [s["name"] for s in charging.filter_stations(stations, open_now=True)] == ["Mở", "Chưa rõ giờ"]


def test_gan_thoi_gian_that_tu_osrm() -> None:
    stations = [_station("A"), _station("B")]
    table = {"durations": [[600.0, None]], "distances": [[4200.0, None]], "approximate": False}
    assert charging.attach_drive_times(stations, table, "motorbike") is False
    assert (stations[0]["driveMinutes"], stations[0]["driveMeters"]) == (10, 4200)
    # Cặp không nối được bằng đường bộ: không bịa số phút.
    assert stations[1]["driveMinutes"] is None


def test_osrm_tat_thi_uoc_tinh_va_danh_dau() -> None:
    stations = [_station("A", distance=3500.0)]
    assert charging.attach_drive_times(stations, None, "motorbike") is True
    assert stations[0]["driveMeters"] == round(3500 * charging.DETOUR_FACTOR)
    assert stations[0]["driveMinutes"] == round(3500 * charging.DETOUR_FACTOR / 350.0)

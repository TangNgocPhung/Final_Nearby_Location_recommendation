"""Bản đồ sương mù — phần kiểm được mà không cần database.

Ghi/đọc/xoá/gộp khi đăng nhập đã đo trên PostGIS dev khi dựng tính năng. Ở đây
khoá lại việc đổi điểm GPS thành ô và đường bao trả cho giao diện.
"""

import h3
import pytest
from pydantic import ValidationError

from app import exploration
from app.models import ExplorationRequest
from app.poi_features import h3_cells_geometry

BEN_THANH = {"latitude": 10.7721, "longitude": 106.6983}


def test_mot_diem_ra_mot_o_r9() -> None:
    cells = exploration.cells_for_points([BEN_THANH])
    assert len(cells) == 1
    assert h3.get_resolution(next(iter(cells))) == exploration.RESOLUTION


def test_hai_diem_cung_o_khong_nhan_doi() -> None:
    nearby = {"latitude": BEN_THANH["latitude"] + 0.00005, "longitude": BEN_THANH["longitude"]}
    assert len(exploration.cells_for_points([BEN_THANH, nearby])) == 1


def test_bo_diem_sai_so_lon() -> None:
    """±800 m mà vẫn tính thì mở app trong nhà cũng mở luôn ô hàng xóm."""
    noisy = {**BEN_THANH, "accuracy_meters": 800}
    assert exploration.cells_for_points([noisy]) == set()
    ok = {**BEN_THANH, "accuracy_meters": exploration.MAX_ACCURACY_METERS}
    assert len(exploration.cells_for_points([ok])) == 1


def test_bo_diem_thieu_hoac_sai_toa_do() -> None:
    assert exploration.cells_for_points([{"latitude": 10.7}, {"latitude": 95, "longitude": 106}]) == set()


def test_dien_tich_ti_le_so_o() -> None:
    assert exploration.area_km2(0) == 0
    assert 0.09 < exploration.area_km2(1) < 0.12
    assert exploration.area_km2(10) == pytest.approx(10 * h3.average_hexagon_area(9, unit="km^2"), abs=0.01)


def test_tong_quan_rong_khong_co_duong_bao() -> None:
    empty = exploration.empty_overview()
    assert empty["cellCount"] == 0 and empty["shape"] is None


def test_duong_bao_hop_nhat_o_ke_nhau_thanh_mot_vung() -> None:
    """Bảy ô liền nhau phải ra MỘT vùng — trả từng ô thì giao diện vẽ bảy lục
    giác chồng viền, sương mù có vệt kẻ giữa các ô."""
    origin = h3.latlng_to_cell(BEN_THANH["latitude"], BEN_THANH["longitude"], exploration.RESOLUTION)
    geo = h3_cells_geometry(h3.grid_disk(origin, 1))
    assert geo is not None
    polygons = [geo["coordinates"]] if geo["type"] == "Polygon" else geo["coordinates"]
    assert len(polygons) == 1
    outer = polygons[0][0]
    assert outer[0] == outer[-1], "vòng phải đóng"
    lng, lat = outer[0]
    assert 106 < lng < 107 and 10 < lat < 11, "toạ độ phải theo thứ tự GeoJSON (lng, lat)"


def test_hai_vung_tach_roi_ra_hai_polygon() -> None:
    far = h3.latlng_to_cell(10.80, 106.72, exploration.RESOLUTION)
    near = h3.latlng_to_cell(BEN_THANH["latitude"], BEN_THANH["longitude"], exploration.RESOLUTION)
    geo = h3_cells_geometry([far, near])
    assert geo is not None and geo["type"] == "MultiPolygon" and len(geo["coordinates"]) == 2


def test_tap_rong_tra_none() -> None:
    assert h3_cells_geometry([]) is None


def _poi(name: str, lat: float, lng: float) -> dict:
    return {"id": name, "latitude": lat, "longitude": lng}


# Hai chỗ ở ô Bến Thành (đã đi) và bốn chỗ cách ~3 km (chưa đi), xếp theo hạng.
_DA_DI = exploration.cells_for_points([BEN_THANH])
_CANDIDATES = [
    _poi("a-cu", BEN_THANH["latitude"], BEN_THANH["longitude"]),
    _poi("b-cu", BEN_THANH["latitude"], BEN_THANH["longitude"]),
    _poi("c-moi", 10.80, 106.72),
    _poi("d-moi", 10.81, 106.73),
    _poi("e-moi", 10.82, 106.74),
    _poi("f-moi", 10.83, 106.75),
]


def test_chua_co_o_nao_thi_khong_doi_thu_tu_va_khong_gan_moi() -> None:
    out = exploration.mix_unexplored(_CANDIDATES, set(), 4)
    assert [p["id"] for p in out] == ["a-cu", "b-cu", "c-moi", "d-moi"]
    assert not any(p["unexplored"] for p in out)


def test_danh_it_nhat_nua_cho_vung_chua_toi() -> None:
    out = exploration.mix_unexplored(_CANDIDATES, _DA_DI, 4)
    assert sum(p["unexplored"] for p in out) >= 2
    # a-cu vẫn nằm trong 4 chỗ được chọn: ưu tiên là chia chỗ, không loại hẳn chỗ quen.
    assert [p["id"] for p in out] == ["a-cu", "b-cu", "c-moi", "d-moi"]


def test_vung_moi_chen_len_khi_chung_o_sau_hang() -> None:
    cu = [_poi(f"cu{i}", BEN_THANH["latitude"], BEN_THANH["longitude"]) for i in range(5)]
    out = exploration.mix_unexplored([*cu, _poi("moi", 10.80, 106.72)], _DA_DI, 4)
    assert [p["id"] for p in out] == ["cu0", "cu1", "cu2", "moi"]


def test_khong_du_vung_moi_thi_lap_bang_cho_cu() -> None:
    out = exploration.mix_unexplored(_CANDIDATES[:3], _DA_DI, 3)
    assert [p["id"] for p in out] == ["a-cu", "b-cu", "c-moi"]


def test_request_gioi_han_so_diem() -> None:
    with pytest.raises(ValidationError):
        ExplorationRequest(points=[])
    with pytest.raises(ValidationError):
        ExplorationRequest(points=[BEN_THANH] * (exploration.MAX_POINTS_PER_REQUEST + 1))


def test_moc_dau_dat_ngay_voi_mot_o() -> None:
    """Mốc đầu 0,1 km² thấp hơn một ô r9 (~0,105 km²) — mở một ô là đạt."""
    assert not any(m["earned"] for m in exploration.milestone_progress(0))
    one = {m["id"]: m for m in exploration.milestone_progress(1)}
    assert one["first_light"]["earned"] and not one["one_km2"]["earned"]


def test_moc_mot_km2_can_du_dien_tich() -> None:
    cells_for_1km2 = 10  # 10 x ~0,105 = 1,05 km²
    assert exploration.milestone_progress(cells_for_1km2)[1]["earned"]
    assert not exploration.milestone_progress(cells_for_1km2 - 1)[1]["earned"]


def test_tien_do_moc_bi_chan_o_muc_tieu() -> None:
    huge = exploration.milestone_progress(100_000)
    assert all(m["earned"] and m["progressKm2"] == m["goalKm2"] for m in huge)


def test_moc_vua_dat_chi_gom_moc_moi_vuot_qua() -> None:
    assert [m["id"] for m in exploration.newly_unlocked(0, 1)] == ["first_light"]
    assert [m["id"] for m in exploration.newly_unlocked(1, 10)] == ["one_km2"]
    assert exploration.newly_unlocked(10, 11) == []
    assert exploration.newly_unlocked(5, 5) == []


def test_tong_quan_co_moc() -> None:
    assert len(exploration.empty_overview()["milestones"]) == len(exploration.MILESTONES)


def test_gop_theo_quan_dem_va_sap_xep() -> None:
    rows = [
        {"cell": "a", "district": "Quận 1", "distanceMeters": 100},
        {"cell": "b", "district": "Quận 1", "distanceMeters": 300},
        {"cell": "c", "district": "Quận 3", "distanceMeters": 50},
    ]
    out = exploration.group_by_district(rows)
    assert [d["district"] for d in out["districts"]] == ["Quận 1", "Quận 3"]
    assert out["districts"][0]["cellCount"] == 2
    assert out["districtCount"] == 2 and out["unassignedCells"] == 0


def test_o_xa_moi_poi_khong_gan_quan_nhung_van_duoc_dem() -> None:
    rows = [
        {"cell": "a", "district": "Quận 1", "distanceMeters": 100},
        {"cell": "b", "district": "Quận 7", "distanceMeters": exploration.DISTRICT_MAX_DISTANCE_METERS + 1},
        {"cell": "c", "district": None, "distanceMeters": None},
    ]
    out = exploration.group_by_district(rows)
    assert out["unassignedCells"] == 2
    total = sum(d["cellCount"] for d in out["districts"]) + out["unassignedCells"]
    assert total == len(rows), "tổng các quận cộng ô chưa gán phải khớp số ô"


def test_request_nhan_du_hai_tram_diem_gui_bu() -> None:
    request = ExplorationRequest(points=[BEN_THANH] * exploration.MAX_POINTS_PER_REQUEST)
    assert len(request.points) == exploration.MAX_POINTS_PER_REQUEST


def test_nhieu_diem_mot_lan_ra_dung_so_o() -> None:
    """Gửi bù: 200 điểm rải trên nhiều ô và nhiều điểm trùng ô."""
    origin = h3.latlng_to_cell(BEN_THANH["latitude"], BEN_THANH["longitude"], exploration.RESOLUTION)
    ring = list(h3.grid_disk(origin, 2))
    points = []
    for cell in ring:
        lat, lng = h3.cell_to_latlng(cell)
        points += [{"latitude": lat, "longitude": lng}] * 3
    assert len(exploration.cells_for_points(points)) == len(ring)

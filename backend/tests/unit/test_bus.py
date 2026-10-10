"""Xe buýt — phân tích thẻ OSM, ghép lộ trình, quãng đường tới trạm, tra tuyến."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app import bus

HCM = ZoneInfo("Asia/Ho_Chi_Minh")


def test_gian_cach_gia_ve_thoi_gian() -> None:
    assert bus.parse_interval("00:06-00:12") == {"minMinutes": 6, "maxMinutes": 12}
    assert bus.parse_interval("00:20") == {"minMinutes": 20, "maxMinutes": 20}
    assert bus.parse_interval("01:00") == {"minMinutes": 60, "maxMinutes": 60}
    assert bus.parse_interval("thường xuyên") is None
    assert bus.parse_charge("6000 VND") == 6000
    assert bus.parse_charge("6.000 đ") == 6000
    assert bus.parse_charge(None) is None
    assert bus.parse_minutes("00:45") == 45
    assert bus.parse_minutes("40") == 40


def test_gio_hoat_dong_dang_chay_va_het_chuyen() -> None:
    running = bus.service_status("Mo-Su 04:00-20:30", datetime(2026, 10, 10, 19, 0, tzinfo=HCM))
    assert running["firstTrip"] == "04:00" and running["lastTrip"] == "20:30"
    assert running["runningNow"] is True and running["endsInMinutes"] == 90
    stopped = bus.service_status("Mo-Su 04:00-20:30", datetime(2026, 10, 10, 22, 0, tzinfo=HCM))
    assert stopped["runningNow"] is False and stopped["startsInMinutes"] == 360
    assert bus.service_status(None)["runningNow"] is None


def test_gio_xe_qua_tram_lui_theo_thoi_gian_tu_ben_dau() -> None:
    hours = "Mo-Su 05:00-22:00"
    # Trạm cách bến đầu 14 phút: chuyến cuối xuất bến 22:00 qua trạm ~22:14.
    late = bus.stop_service(hours, 14, datetime(2026, 10, 10, 22, 5, tzinfo=HCM))
    assert late["firstTrip"] == "05:14" and late["lastTrip"] == "22:14"
    assert late["runningNow"] is True and late["endsInMinutes"] == 9
    # Sau chuyến cuối qua trạm: chờ chuyến đầu sáng mai ~05:14.
    done = bus.stop_service(hours, 14, datetime(2026, 10, 10, 22, 20, tzinfo=HCM))
    assert done["runningNow"] is False and done["startsInMinutes"] == 6 * 60 + 54
    # Sáng sớm: bến đầu đã xuất bến 05:00 nhưng xe chưa tới trạm.
    early = bus.stop_service(hours, 14, datetime(2026, 10, 10, 5, 5, tzinfo=HCM))
    assert early["runningNow"] is False and early["startsInMinutes"] == 9


def test_gio_xe_qua_tram_qua_nua_dem_va_thieu_du_lieu() -> None:
    assert bus.stop_service("Mo-Su 05:00-23:30", 45, datetime(2026, 10, 10, 12, 0, tzinfo=HCM))["lastTrip"] == "00:15"
    assert bus.stop_service("Mo-Su 05:00-22:00", None) is None
    assert bus.stop_service("Mo-Fr 07:00,17:15", 10)["runningNow"] is None
    assert bus.minutes_to_stop(40, 10_000, 2_500) == 10
    assert bus.minutes_to_stop(None, 10_000, 2_500) is None
    assert bus.minutes_to_stop(40, 10_000, None) is None


def test_thoi_gian_chuyen_uu_tien_the_duration() -> None:
    assert bus.trip_minutes("00:45", 30_000) == (45, "osm")
    assert bus.trip_minutes(None, 18_000) == (60, "estimate")
    assert bus.trip_minutes(None, None) == (None, "unknown")


# Toạ độ (vĩ, kinh) dọc một đường thẳng hướng Đông, mỗi bước ~110 m.
A, B, C, D, E = ((10.77, 106.700 + 0.001 * step) for step in range(5))


def test_ghep_lo_trinh_dao_chieu_way_ve_nguoc() -> None:
    # Way đầu và way thứ ba được vẽ ngược chiều xe chạy.
    chains = bus.assemble_path([[B, A], [B, C], [D, C], [D, E]])
    assert chains == [[A, B, C, D, E]]


def test_ghep_lo_trinh_way_lech_thu_tu() -> None:
    # Người nhập đặt C–D sau D–E: vẫn ghép liền, không hở.
    assert bus.assemble_path([[A, B], [B, C], [D, E], [C, D]]) == [[A, B, C, D, E]]


def test_noi_khuc_cham_nhau_du_liet_ke_xa() -> None:
    # Đoạn đầu lượt bị liệt kê ở cuối relation (tuyến 52 lượt về).
    assert bus._join_touching([[C, D, E], [A, B, C]], 40) == [[A, B, C, D, E]]


def test_ghep_lo_trinh_dut_that_thi_tach_khuc() -> None:
    far = [(10.80, 106.70), (10.80, 106.71)]
    chains = bus.assemble_path([[A, B], [B, C], far])
    assert chains == [[A, B, C], far]


def test_vong_xuyen_chi_di_tu_cho_vao_toi_cho_ra() -> None:
    # Vòng xuyến vuông P0→P1→P2→P3→P0; vào ở P0, ra ở P2 (way kế bắt đầu từ P2).
    p0, p1, p2, p3 = (10.770, 106.700), (10.770, 106.7003), (10.7703, 106.7003), (10.7703, 106.700)
    before = [(10.769, 106.700), p0]
    after = [p2, (10.771, 106.7003)]
    chains = bus.assemble_path([before, [p0, p1, p2, p3, p0], after])
    assert chains == [[before[0], p0, p1, p2, after[1]]]


def test_quang_duong_toi_tram_chi_tien_ve_phia_truoc() -> None:
    # Tuyến đi A→E rồi quay về A; trạm thứ hai nằm sát B nhưng ở lượt quay về.
    chains = [[A, B, C, D, E, D, C, B, A]]
    distances = bus.stop_distances(chains, [A, D, B])
    assert distances[0] == 0
    assert 300 < distances[1] < 360
    # B ở lượt về: ~770 m (A→E→B), không phải 110 m (B ở lượt đi).
    assert distances[2] > 700


def test_tram_dau_khong_bi_hut_ve_khuc_le_cuoi_tuyen() -> None:
    """Tuyến 52 lượt về (đo 2026-10-10): trạm đầu cách khúc lộ trình lẻ ở CUỐI
    tuyến 7 m, cách điểm đầu thật 62 m. Khớp tham lam vào khúc cuối thì mọi trạm
    sau dồn về cuối tuyến; khớp đúng thì giữ thứ tự."""
    first_stop = (A[0] + 0.0005, A[1])  # ~55 m phía bắc A
    tail = [(first_stop[0], A[1] - 0.0004), (first_stop[0], A[1] + 0.0004)]
    distances = bus.stop_distances([[A, B, C, D, E], tail], [first_stop, C, E])
    assert distances[0] is not None and distances[0] < 30
    assert 200 < distances[1] < 240
    assert 420 < distances[2] < 460


def test_tram_liet_ke_sai_cho_bi_bo_qua() -> None:
    distances = bus.stop_distances([[A, B, C, D, E]], [A, D, B, E])
    assert distances[0] == 0 and 300 < distances[1] < 360
    # B nằm trước D trên lộ trình nhưng liệt kê sau — bỏ, không kéo E lùi theo.
    assert distances[2] is None
    assert distances[3] > 400
    # ...nhưng vẫn là trạm thật của tuyến: chèn lại đúng vị trí trên lộ trình.
    assert [index for index, _ in bus.order_stops([[A, B, C, D, E]], [A, D, B, E])] == [0, 2, 1, 3]
    far = (10.80, 106.70)
    assert [index for index, _ in bus.order_stops([[A, B, C, D, E]], [A, far, E])] == [0, 2]


def test_khuc_lo_trinh_sap_va_quay_chieu_theo_thu_tu_tram() -> None:
    oriented = bus.orient_chains([[E, D, C], [C, B, A]], [A, B, D, E])
    assert oriented == [[A, B, C], [C, D, E]]


def test_lo_trinh_ten_duong_gop_va_bo_nut_giao() -> None:
    names = ["Lý Thái Tổ", "Lý Thái Tổ", "Ngã bảy Lý Thái Tổ", "Lý Thái Tổ", None, "Đường 3 Tháng 2"]
    assert bus.street_sequence(names) == ["Lý Thái Tổ", "Đường 3 Tháng 2"]
    # Đường thật kẹp giữa thì giữ — xe rẽ vào rồi ra thật.
    assert bus.street_sequence(["A", "Cao Thắng", "A"]) == ["A", "Cao Thắng", "A"]


def test_so_tuyen_sap_theo_so() -> None:
    refs = ["D2", "14", "60-1", "8", "01"]
    assert sorted(refs, key=bus.natural_ref_key) == ["01", "8", "14", "60-1", "D2"]


def _route(**overrides: object) -> dict:
    base = {
        "id": 1,
        "ref": "14",
        "name": "Bến xe Miền Đông - Bến xe Miền Tây",
        "origin": "Bến xe Miền Đông",
        "destination": "Bến xe Miền Tây",
        "via": None,
        "network": bus.HCMC_NETWORK,
        "operator": "FUTA",
        "streets": ["Điện Biên Phủ", "Đường 3 Tháng 2"],
    }
    return {**base, **overrides}


def test_tra_tuyen_theo_so_ten_ben_va_duong() -> None:
    line = [_route()]
    assert bus._matches("14", line) == 0
    assert bus._matches("1", [_route(ref="01")]) == 0
    assert bus._matches("1", line) == 1
    assert bus._matches("mien tay", line) == 2
    assert bus._matches("Điện Biên Phủ", line) == 2
    assert bus._matches("Thủ Đức", line) is None


def test_chuan_hoa_relation_osm() -> None:
    relation = {
        "id": 99,
        "type": "relation",
        "tags": {"type": "route", "route": "bus", "ref": "14", "name": "X - Y", "from": "X", "to": "Y",
                 "opening_hours": "Mo-Su 04:00-20:30", "interval": "00:06-00:12", "charge": "6000 VND"},
        "members": [
            {"type": "node", "ref": 1, "role": "platform_entry_only"},
            {"type": "way", "ref": 10, "role": "", "geometry": [{"lat": A[0], "lon": A[1]}, {"lat": C[0], "lon": C[1]}]},
            {"type": "way", "ref": 11, "role": "", "geometry": [{"lat": E[0], "lon": E[1]}, {"lat": C[0], "lon": C[1]}]},
            {"type": "node", "ref": 2, "role": "platform_exit_only"},
            {"type": "way", "ref": 12, "role": "platform"},
        ],
    }
    nodes = {
        1: {"id": 1, "lat": A[0], "lon": A[1], "tags": {"name": "Bến X"}},
        2: {"id": 2, "lat": E[0], "lon": E[1], "tags": {"name": "Bến Y"}},
    }
    ways = {10: {"tags": {"name": "Điện Biên Phủ"}}, 11: {"tags": {"name": "Điện Biên Phủ"}}}
    route = bus.normalize_route(relation, nodes, ways)
    assert route is not None
    assert route["chains"] == [[A, C, E]]
    assert route["streets"] == ["Điện Biên Phủ"]
    assert [stop["role"] for stop in route["stops"]] == ["platform_entry_only", "platform_exit_only"]
    assert route["stops"][0]["distanceMeters"] == 0
    assert abs(route["stops"][1]["distanceMeters"] - route["lengthMeters"]) < 1
    # Không có số tuyến thì không nhận — người dùng tra theo số.
    assert bus.normalize_route({**relation, "tags": {**relation["tags"], "ref": ""}}, nodes, ways) is None

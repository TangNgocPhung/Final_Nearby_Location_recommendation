from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app import parking
from app.opening_hours import parse_opening_hours
from app.parking_tags import facility_from_osm_tags, parse_price, parse_sockets

VN = ZoneInfo("Asia/Ho_Chi_Minh")
NOON = datetime(2026, 9, 25, 12, 0, tzinfo=VN)  # thứ Sáu


# ---------------------------------------------------------------- parse_price
# Các chuỗi dưới đây là giá trị `charge` THẬT trên OSM TP.HCM (2026-09-25).


def test_gia_theo_loai_xe():
    assert parse_price("5000 VND/bike, 20000 VND/car") == [
        {"vehicle": "motorbike", "amountVnd": 5000, "unit": "turn", "unitAssumed": True},
        {"vehicle": "car", "amountVnd": 20000, "unit": "turn", "unitAssumed": True},
    ]


def test_gia_viet_tat_k_va_dau_phan_cach():
    assert parse_price("30k VND")[0]["amountVnd"] == 30000
    assert parse_price("5.000đ/lượt xe máy")[0] == {
        "vehicle": "motorbike",
        "amountVnd": 5000,
        "unit": "turn",
        "unitAssumed": False,
    }
    assert parse_price("25,000 VND/hour car")[0]["unit"] == "hour"


def test_ve_sau_ke_thua_loai_xe_va_ban_ngay_la_theo_luot():
    prices = parse_price("Xe máy ban ngày 4.000đ, ban đêm 6.000đ")
    assert [(p["vehicle"], p["unit"], p["amountVnd"]) for p in prices] == [
        ("motorbike", "turn", 4000),
        ("motorbike", "night", 6000),
    ]


def test_chuoi_khong_phai_gia():
    assert parse_price("yes") == []
    assert parse_price("0.5 USD") == []
    assert parse_price(None) == []


# ------------------------------------------------------ facility_from_osm_tags


def test_bai_xe_may_chuyen_dung():
    facility = facility_from_osm_tags({"amenity": "motorcycle_parking", "charge": "5000 VND"})
    assert (facility["motorbike"], facility["car"], facility["fee"]) == ("yes", "no", "yes")


def test_ten_bai_noi_loai_xe():
    facility = facility_from_osm_tags({"amenity": "parking", "name": "Bãi gửi xe hai bánh"})
    assert (facility["motorbike"], facility["car"]) == ("yes", "unknown")


def test_bai_do_mac_dinh_nhan_o_to_con_xe_may_chua_ro():
    facility = facility_from_osm_tags({"amenity": "parking"})
    assert (facility["motorbike"], facility["car"], facility["fee"]) == ("unknown", "yes", "unknown")


def test_cong_sac():
    sockets = parse_sockets({"socket:type2_combo": "2", "socket:type2_combo:output": "60 kW"})
    assert sockets == [{"type": "CCS2 (DC)", "count": 2, "powerKw": 60.0}]
    assert facility_from_osm_tags({"amenity": "charging_station"})["ev_charging"] is True


# ------------------------------------------------------------- resolve_price


def _report(amount, unit="turn", vehicle="motorbike", hours=None, days_ago=1):
    return {
        "vehicle": vehicle,
        "amount_vnd": amount,
        "unit": unit if amount is not None else None,
        "opening_hours": hours,
        "created_at": NOON - timedelta(days=days_ago),
    }


def test_hai_bao_cao_cong_dong_thang_gia_osm():
    facility = {"prices": parse_price("3000 VND"), "fee": "yes"}
    price = parking.resolve_price(facility, [_report(5000), _report(6000), _report(5000)], "motorbike", NOON, 120)
    assert price["tier"] == "community"
    assert price["amountVnd"] == 5000
    assert price["reports"] == 3


def test_mot_bao_cao_don_le_xep_sau_osm():
    facility = {"prices": parse_price("3000 VND"), "fee": "yes"}
    price = parking.resolve_price(facility, [_report(9000)], "motorbike", NOON, 120)
    assert (price["tier"], price["amountVnd"]) == ("openstreetmap", 3000)


def test_gia_theo_gio_nhan_so_gio_gui():
    facility = {"prices": parse_price("20000 VND/hour car"), "fee": "yes"}
    price = parking.resolve_price(facility, [], "car", NOON, 150)
    assert price["estimatedCost"] == 60000  # 3 giờ bắt đầu tính


def test_mien_phi():
    price = parking.resolve_price({"prices": [], "fee": "no"}, [], "motorbike", NOON, 60)
    assert (price["amountVnd"], price["estimatedCost"], price.get("free")) == (0, 0, True)


def test_khong_co_gia_that_thi_dung_muc_tham_khao_da_bai_bo():
    day = parking.resolve_price({"prices": [], "fee": "unknown"}, [], "motorbike", NOON, 60)
    night = parking.resolve_price({"prices": [], "fee": "unknown"}, [], "motorbike", NOON.replace(hour=20), 60)
    assert day["tier"] == "reference"
    assert (day["amountMinVnd"], day["amountVnd"]) == (4000, 6000)
    assert (night["amountMinVnd"], night["amountVnd"]) == (6000, 9000)
    assert "bãi bỏ" in day["legalReference"]["status"]


def test_o_to_ven_duong_theo_nq01_luy_tien_va_chi_tinh_06_24():
    street = {"prices": [], "fee": "unknown", "parking_type": "street_side"}
    price = parking.resolve_price(street, [], "car", NOON, 300)  # 5 giờ
    assert price["tier"] == "regulated"
    assert (price["estimatedCostMin"], price["estimatedCost"]) == (120000, 145000)
    late = parking.resolve_price(street, [], "car", NOON.replace(hour=23), 120)  # 23h→01h: chỉ 1 giờ tính phí
    assert (late["estimatedCostMin"], late["estimatedCost"]) == (20000, 25000)


def test_o_to_trong_bai_khong_co_muc_tham_khao():
    price = parking.resolve_price({"prices": [], "fee": "unknown", "parking_type": "surface"}, [], "car", NOON, 60)
    assert price["tier"] == "unknown"


def test_tram_sac_vinfast_gia_niem_yet():
    station = {"prices": [], "fee": "unknown", "operator": "VinFast"}
    price = parking.resolve_price(station, [], "ev", NOON, 60)
    assert (price["tier"], price["amountVnd"], price["unit"]) == ("published", 3858, "kwh")
    assert parking.resolve_price({"prices": [], "fee": "unknown"}, [], "ev", NOON, 60)["tier"] == "unknown"


# ------------------------------------------------------------ open_throughout


def test_mo_suot_thoi_gian_gui():
    schedule = parse_opening_hours("06:00-22:00")
    assert parking.open_throughout(schedule, NOON, NOON + timedelta(hours=3)) is True
    assert parking.open_throughout(schedule, NOON, NOON + timedelta(hours=11)) is False
    assert parking.open_throughout(parse_opening_hours("24/7"), NOON, NOON + timedelta(days=2)) is True
    assert parking.open_throughout(None, NOON, NOON + timedelta(hours=1)) is None


def test_ca_qua_dem():
    schedule = parse_opening_hours("18:00-02:00")
    start = NOON.replace(hour=23)
    assert parking.open_throughout(schedule, start, start + timedelta(hours=2)) is True
    assert parking.open_throughout(schedule, start, start + timedelta(hours=4)) is False


# ----------------------------------------------------------------------- rank


def _result(poi_id, walk, cost, open_through=True, uncertainty=0.0):
    return {
        "id": poi_id,
        "walkMeters": walk,
        "price": {"estimatedCost": cost},
        "hours": {"openThroughout": open_through},
        "uncertainty": uncertainty,
    }


def test_loai_bai_chac_chan_dong_va_xep_theo_diem():
    ranked = parking.rank(
        [
            _result("xa-re", 900, 3000),
            _result("gan-dat", 100, 30000),
            _result("gan-re", 150, 5000),
            _result("dong-cua", 50, 2000, open_through=False),
        ],
        radius=1000,
    )
    assert [r["id"] for r in ranked] == ["gan-re", "gan-dat", "xa-re"]


def test_chua_biet_gia_khong_duoc_thuong():
    ranked = parking.rank([_result("khong-gia", 100, None, uncertainty=1.0), _result("co-gia", 100, 5000)], 1000)
    assert ranked[0]["id"] == "co-gia"


def test_bao_cao_gio_mo_cua_cua_cong_dong():
    hours = parking._hours({}, [_report(None, hours="07:00-21:00")], NOON, NOON + timedelta(hours=2))
    assert (hours["source"], hours["openThroughout"], hours["raw"]) == ("community", True, "07:00-21:00")

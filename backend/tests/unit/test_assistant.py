from datetime import date

from app import assistant


def test_su_kien_sap_toi_tinh_ca_am_lich():
    events = assistant.upcoming_events(date(2026, 9, 25))
    ids = [(event["id"], event["daysUntil"]) for event in events]
    # 25/9/2026 chính là Rằm tháng Tám.
    assert ids[0] == ("trung_thu", 0)
    assert ("phu_nu_vn", 25) in ids
    assert all(0 <= days <= assistant.EVENT_HORIZON_DAYS for _, days in ids)


def test_tet_2027_tinh_dung_ngay_duong():
    events = assistant.upcoming_events(date(2027, 1, 20), horizon_days=30)
    tet = next(event for event in events if event["id"] == "tet_nguyen_dan")
    assert tet["date"] == date(2027, 2, 6)


def test_ngoai_viet_nam_khong_co_lich():
    assert assistant.in_vietnam(10.7769, 106.7009)
    assert not assistant.in_vietnam(13.7563, 100.5018)  # Bangkok


def _stop(name, lat, lng):
    return {"name": name, "latitude": lat, "longitude": lng}


def test_tour_dung_khi_het_thoi_luong():
    # Bốn điểm thẳng hàng, mỗi điểm cách nhau ~1,1 km (~19 phút đi bộ).
    stops = [_stop(str(i), 10.77 + i * 0.01, 106.70) for i in range(4)]
    tour = assistant.order_stops(stops, budget_minutes=60)
    # 12 phút tham quan điểm đầu + (19 + 12) cho điểm hai = 43; điểm ba vượt 60.
    assert [stop["name"] for stop in tour] == ["0", "1"]


def test_tour_di_toi_diem_gan_nhat_tiep_theo():
    stops = [
        _stop("dau", 10.7700, 106.7000),
        _stop("xa", 10.7800, 106.7000),
        _stop("gan", 10.7710, 106.7000),
    ]
    tour = assistant.order_stops(stops, budget_minutes=240)
    assert [stop["name"] for stop in tour] == ["dau", "gan", "xa"]


def test_hen_nhom_chon_minimax_khong_phai_diem_giua(monkeypatch):
    participants = [
        {"label": "A", "latitude": 10.70, "longitude": 106.70},
        {"label": "B", "latitude": 10.80, "longitude": 106.70},
    ]
    candidates = [
        # Ngay điểm giữa trên bản đồ, nhưng B phải đi đường vòng: 30 phút.
        {"poiId": "giua", "name": "Quán giữa", "category": "cafe", "address": None, "rating": None,
         "latitude": 10.75, "longitude": 106.70, "centerMeters": 0.0,
         "parkingName": None, "parkingMeters": None},
        {"poiId": "cong_bang", "name": "Quán công bằng", "category": "cafe", "address": None,
         "rating": 4.5, "latitude": 10.76, "longitude": 106.71, "centerMeters": 1500.0,
         "parkingName": "Bãi xe", "parkingMeters": 60.0},
    ]
    monkeypatch.setattr(assistant, "_meetup_candidates", lambda *args: candidates)
    monkeypatch.setattr(
        assistant.directions,
        "duration_table",
        lambda sources, destinations, mode: {
            "durations": [[600, 1080], [1800, 1140]],  # giây: A→(giữa, công bằng), B→...
            "approximate": False,
        },
    )
    result = assistant.plan_meetup(participants)
    assert result["status"] == "ready"
    best = result["results"][0]
    assert best["poiId"] == "cong_bang"
    assert best["minutes"] == [18, 19]
    assert best["maxMinutes"] == 19
    assert best["parking"] == {"name": "Bãi xe", "distanceMeters": 60}
    # Đối chứng: quán gần điểm giữa bản đồ bắt B đi 30 phút.
    assert result["baseline"]["poiId"] == "giua"
    assert result["baseline"]["maxMinutes"] == 30


def test_hen_nhom_bo_quan_khong_co_duong(monkeypatch):
    participants = [
        {"label": "A", "latitude": 10.70, "longitude": 106.70},
        {"label": "B", "latitude": 10.80, "longitude": 106.70},
    ]
    candidates = [
        {"poiId": "dao", "name": "Quán trên đảo", "category": "cafe", "address": None, "rating": None,
         "latitude": 10.75, "longitude": 106.70, "centerMeters": 0.0,
         "parkingName": None, "parkingMeters": None},
    ]
    monkeypatch.setattr(assistant, "_meetup_candidates", lambda *args: candidates)
    monkeypatch.setattr(
        assistant.directions,
        "duration_table",
        lambda *args: {"durations": [[600], [None]], "approximate": False},
    )
    assert assistant.plan_meetup(participants)["status"] == "none"

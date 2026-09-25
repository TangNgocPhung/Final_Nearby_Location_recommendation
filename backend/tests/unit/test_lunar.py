from datetime import date

from app.lunar import lunar_to_solar, solar_to_lunar, year_name


def test_tet_nguyen_dan_cac_nam():
    # Mùng 1 Tết theo lịch Việt Nam đã công bố.
    assert lunar_to_solar(1, 1, 2024) == date(2024, 2, 10)
    assert lunar_to_solar(1, 1, 2025) == date(2025, 1, 29)
    assert lunar_to_solar(1, 1, 2026) == date(2026, 2, 17)
    assert lunar_to_solar(1, 1, 2027) == date(2027, 2, 6)


def test_trung_thu_ke_ca_nam_co_thang_nhuan():
    # 2025 (Ất Tỵ) nhuận tháng 6 — Trung Thu phải lùi sang 6/10.
    assert lunar_to_solar(15, 8, 2025) == date(2025, 10, 6)
    assert lunar_to_solar(15, 8, 2026) == date(2026, 9, 25)


def test_tet_1985_lich_viet_khac_lich_trung_quoc():
    # Lịch Việt (múi +7) đón Tết 1985 ngày 21/1, lịch Trung Quốc ngày 20/2.
    assert lunar_to_solar(1, 1, 1985) == date(1985, 1, 21)


def test_duong_sang_am_va_nguoc_lai_khop_nhau():
    assert solar_to_lunar(date(2026, 9, 25)) == (15, 8, 2026, False)
    assert solar_to_lunar(date(2026, 2, 17)) == (1, 1, 2026, False)
    # Ngày trong tháng 6 nhuận năm 2025.
    day, month, year, leap = solar_to_lunar(date(2025, 7, 30))
    assert (month, year, leap) == (6, 2025, True)
    assert lunar_to_solar(day, month, year, leap) == date(2025, 7, 30)


def test_thang_nhuan_khong_ton_tai_tra_none():
    assert lunar_to_solar(1, 6, 2026, leap=True) is None


def test_can_chi():
    assert year_name(2026) == "Bính Ngọ"
    assert year_name(2025) == "Ất Tỵ"
    assert year_name(2024) == "Giáp Thìn"

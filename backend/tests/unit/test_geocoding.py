from app.geocoding import normalize_text, split_subject_and_location


def test_normalize_text_preserves_vietnamese_and_collapses_whitespace() -> None:
    assert normalize_text("  Cà   PHÊ  ") == "cà phê"


def test_split_subject_and_location_understands_vietnamese_connector() -> None:
    assert split_subject_and_location("Cà phê gần Bến Thành") == (
        "cà phê",
        "bến thành",
    )


def test_split_subject_and_location_keeps_plain_query() -> None:
    assert split_subject_and_location("bảo tàng") == ("bảo tàng", None)


def test_split_subject_and_location_treats_day_as_current_location() -> None:
    # "gần đây" = "nearby" (vị trí hiện tại) — "đây" không phải tên địa danh,
    # không được đưa đi geocode (đo được thật 2026-09-20: "parking gần đây"
    # từng bị fuzzy-match nhầm ra một POI tên "TH-Anh Đây" cách 64km).
    assert split_subject_and_location("parking gần đây") == ("parking", None)


def test_split_subject_and_location_treats_cho_nay_as_current_location() -> None:
    assert split_subject_and_location("quán cà phê ở chỗ này") == (
        "quán cà phê",
        None,
    )

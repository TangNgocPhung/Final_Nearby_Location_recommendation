from app.meal_fit import filter_for_meal, meal_fit


def _poi(name, *tags):
    return {"name": name, "tags": ["restaurant", *tags]}


# Đúng bộ kết quả người dùng gặp: chip "Gợi ý cho bữa sáng" trả chè và kem.
CHE = _poi("Chè 259", "food_court")
KEM = _poi("Kem Vĩnh Sanh", "ice_cream")
XOI = _poi("Xôi Châu", "vietnamese")
PHO = _poi("Phở Hòa")
UNKNOWN = _poi("Quán Cô Ba")
LAU = _poi("Lẩu Dê 404", "hotpot")


def test_breakfast_drops_dessert_and_heavy_food():
    assert meal_fit(CHE, "breakfast") == -1
    assert meal_fit(KEM, "breakfast") == -1
    assert meal_fit(LAU, "breakfast") == -1


def test_breakfast_puts_breakfast_dishes_first_and_keeps_unknown():
    ranked = filter_for_meal([CHE, UNKNOWN, KEM, XOI, LAU, PHO], "breakfast", limit=5)
    assert [poi["name"] for poi in ranked] == ["Xôi Châu", "Phở Hòa", "Quán Cô Ba"]


def test_whole_word_match_only():
    # "kem" không được khớp nhầm vào một từ dài hơn.
    assert meal_fit(_poi("Kemmy Bistro"), "breakfast") == 0


def test_late_night_keeps_dessert():
    assert meal_fit(CHE, "late_night") == 0
    assert meal_fit(KEM, "late_night") == 0


def test_lunch_drops_dessert_but_keeps_hotpot():
    assert meal_fit(KEM, "lunch") == -1
    assert meal_fit(LAU, "lunch") == 0

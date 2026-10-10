from app.search.accents import accent_mismatch, drop_accent_mismatches, has_marks, signature


def test_tone_placement_variants_are_the_same_word():
    assert signature("Hoà") == signature("hòa")
    assert signature("Thuỷ") == signature("thủy")


def test_tone_and_shape_marks_distinguish_words():
    assert signature("chay") != signature("cháy")
    assert signature("quán") != signature("quận")
    assert signature("đá")[0] == "da" and signature("đá") != signature("dá")


def test_fire_station_does_not_match_vegetarian_query():
    name = "Phòng Cảnh sát Phòng cháy và Chữa cháy Công an Quận 6"
    assert accent_mismatch("chay", name, ("Cơ quan nhà nước",))
    assert accent_mismatch("Quán chay", name)


def test_real_vegetarian_places_are_kept():
    assert not accent_mismatch("chay", "Quán Hủ Tíu Chay", ("Ăn uống",))
    assert not accent_mismatch("Quán chay", "Cơm chay chùa Viên Minh")


def test_unaccented_names_cannot_be_judged():
    assert not accent_mismatch("chay", "Quan Com Chay Dieu Hue")


def test_category_vocabulary_rescues_a_name_with_a_stray_conflict():
    assert not accent_mismatch("bệnh viện", "Bệnh viện Quận 6")
    assert accent_mismatch("bệnh viện", "Công viên Phú Lâm")
    assert not accent_mismatch("bệnh viện", "Công viên Phú Lâm", ("bệnh viện",))


def test_drop_only_when_the_user_typed_accents():
    candidates = [
        {"name": "Phòng Cảnh sát Phòng cháy và Chữa cháy", "category": "police", "categoryLabel": "Công an"},
        {"name": "Quán Hủ Tíu Chay", "category": "restaurant", "categoryLabel": "Ăn uống"},
    ]
    kept = drop_accent_mismatches(candidates, "chay", "Quán chay gần tôi")
    assert [c["name"] for c in kept] == ["Quán Hủ Tíu Chay"]
    # Gõ không dấu: "chay" có thể là "cháy" thật — không phán.
    assert drop_accent_mismatches(candidates, "chay", "quan chay gan toi") == candidates
    assert drop_accent_mismatches(candidates, "", "Quán chay") == candidates


def test_has_marks():
    assert has_marks("Quán chay gần tôi")
    assert not has_marks("quan chay gan toi")

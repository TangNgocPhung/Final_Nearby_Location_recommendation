from app import chat


def test_extract_json_object_parses_clean_json():
    assert chat._extract_json_object('{"a": 1, "b": "x"}') == {"a": 1, "b": "x"}


def test_extract_json_object_repairs_truncated_closing_brace():
    # llama3.2:3b thỉnh thoảng dừng sinh chữ ngay sau giá trị chuỗi cuối,
    # thiếu nốt dấu "}" đóng — xem docstring `_extract_json_object`.
    truncated = '{"search_query": "", "needs_clarification": true, "clarifying_question": "Chào bạn!"'
    assert chat._extract_json_object(truncated) == {
        "search_query": "",
        "needs_clarification": True,
        "clarifying_question": "Chào bạn!",
    }


def test_extract_json_object_returns_none_for_garbage():
    assert chat._extract_json_object("không phải json gì cả") is None


def test_fix_literal_unicode_escapes_decodes_double_escaped_chars():
    # Đo được thật (2026-09-20): model trả literal "ô" (6 ký tự: một dấu
    # backslash THẬT + u00f4) thay vì ký tự "ô" trong clarifying_question.
    assert chat._fix_literal_unicode_escapes("hẹn h\\u00f4?") == "hẹn hô?"


def test_fix_literal_unicode_escapes_leaves_normal_text_unchanged():
    assert chat._fix_literal_unicode_escapes("Chào bạn, bạn tìm gì?") == "Chào bạn, bạn tìm gì?"

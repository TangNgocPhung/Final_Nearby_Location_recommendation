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


def test_quick_search_intent_nhan_cau_tim_dia_diem_ro_rang():
    intent = chat.quick_search_intent("Quán cà phê yên tĩnh gần đây")
    assert intent is not None
    assert intent["category"] == "cafe"
    assert intent["needs_clarification"] is False


def test_quick_search_intent_bo_qua_cau_hoi_mo_ho():
    assert chat.quick_search_intent("Tối nay nên làm gì?") is None


def test_rule_based_intent_tim_kiem_mo_ta_khong_hoi_lai():
    # llama3.2:3b từng đánh dấu nhầm câu này là cần hỏi lại rồi chép nguyên
    # câu người dùng làm câu hỏi lại — luật thì luôn chạy search.
    intent = chat.rule_based_intent("chỗ nào yên tĩnh để ngồi làm việc")
    assert intent["needs_clarification"] is False
    assert intent["search_query"] == "chỗ nào yên tĩnh để ngồi làm việc"
    assert intent["radius_m"] is None


def test_rule_based_intent_doc_ban_kinh():
    assert chat.rule_based_intent("quán ăn trong 1,5km")["radius_m"] == 1500
    assert chat.rule_based_intent("nhà thuốc trong vòng 500 m")["radius_m"] == 500
    assert chat.rule_based_intent("có 3 món gì ngon")["radius_m"] is None


def test_rule_based_intent_chon_category_khi_chi_khop_mot_loai():
    assert chat.rule_based_intent("muốn mua thuốc")["category"] == "pharmacy"


def test_rule_based_intent_hoi_lai_khi_chi_chao_hoi():
    intent = chat.rule_based_intent("Chào bạn!")
    assert intent["needs_clarification"] is True
    assert intent["clarifying_question"]
    assert chat.rule_based_intent("cảm ơn nhé")["needs_clarification"] is True
    # Chào kèm nội dung tìm kiếm thì vẫn search.
    assert chat.rule_based_intent("chào bạn, tìm giúp mình quán phở")["needs_clarification"] is False


def test_explain_results_stream_tra_tung_manh(monkeypatch):
    monkeypatch.setattr(chat, "fetch_knowledge_map", lambda ids: {})
    monkeypatch.setattr(chat, "_append_history", lambda *args: None)
    monkeypatch.setattr(chat, "_ollama_chat_stream", lambda messages, max_tokens: iter(["Có ", "Phở A."]))
    pieces = list(chat.explain_results_stream("s", "phở", [{"id": "1", "name": "Phở A"}]))
    assert pieces == ["Có ", "Phở A."]


def test_explain_results_stream_du_phong_khi_ollama_tat(monkeypatch):
    monkeypatch.setattr(chat, "fetch_knowledge_map", lambda ids: {})
    monkeypatch.setattr(chat, "_append_history", lambda *args: None)
    monkeypatch.setattr(chat, "_ollama_chat_stream", lambda messages, max_tokens: iter([]))
    reply = chat.explain_results("s", "phở", [{"id": "1", "name": "Phở A"}])
    assert reply == "Mình tìm được vài chỗ gần bạn: Phở A."


def test_explain_messages_bo_field_null(monkeypatch):
    monkeypatch.setattr(chat, "fetch_knowledge_map", lambda ids: {})
    messages = chat._explain_messages("phở", [{"id": "1", "name": "Phở A", "rating": None}])
    assert '"rating"' not in messages[1]["content"]
    assert "Thời tiết" not in messages[1]["content"]

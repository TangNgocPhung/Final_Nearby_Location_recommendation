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
    intent = chat.quick_search_intent("Quán cà phê gần đây")
    assert intent is not None
    assert intent["category"] == "cafe"
    assert intent["needs_clarification"] is False


def test_quick_search_intent_cau_co_them_y_thi_khong_khoa_category():
    # Có category thì api.py bỏ chữ, chỉ lọc theo loại — "yên tĩnh" sẽ mất.
    intent = chat.quick_search_intent("Quán cà phê yên tĩnh gần đây")
    assert intent is not None
    assert intent["category"] is None
    assert intent["search_query"] == "cà phê yên tĩnh"


def test_quick_search_intent_khop_theo_ranh_gioi_tu():
    # "gan toi" chứa chuỗi con "an toi" (ăn tối) — từng biến "quán chay" thành
    # "nhà hàng gần nhất" và trả chè, kem, sủi cảo.
    intent = chat.quick_search_intent("Quán chay gần tôi")
    assert intent is not None
    assert intent["category"] is None
    assert intent["search_query"] == "chay"


def test_quick_search_intent_bo_qua_cau_hoi_mo_ho():
    assert chat.quick_search_intent("Tối nay nên làm gì?") is None


def test_rule_based_intent_tim_kiem_mo_ta_khong_hoi_lai():
    # llama3.2:3b từng đánh dấu nhầm câu này là cần hỏi lại rồi chép nguyên
    # câu người dùng làm câu hỏi lại — luật thì luôn chạy search.
    intent = chat.rule_based_intent("chỗ nào yên tĩnh để ngồi làm việc")
    assert intent["needs_clarification"] is False
    assert intent["search_query"] == "yên tĩnh để ngồi làm việc"
    assert intent["semantic_query"] == "chỗ nào yên tĩnh để ngồi làm việc"
    assert intent["radius_m"] is None


def test_rule_based_intent_bo_tu_dem_cho_bm25_giu_nguyen_van_cho_vector():
    # Đo 2026-10-10: "ở/đâu/được" làm BM25 về 0 hit (minimum_should_match đòi
    # khớp 3/5 từ); còn embedding câu nguyên văn mới xếp "Bệnh viện Truyền máu
    # Huyết học" lên đầu — "Hiến máu" trơ trọi đẩy nó khỏi top 20.
    intent = chat.rule_based_intent("Hiến máu ở đâu được")
    assert intent["search_query"] == "Hiến máu"
    assert intent["semantic_query"] == "Hiến máu ở đâu được"
    assert chat.rule_based_intent("hien mau o dau")["search_query"] == "hien mau"


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


SIEU_THI = [
    {"id": "1", "name": "VinMart+", "distanceMeters": 891.2},
    {"id": "2", "name": "Siêu Thị Co.opmart", "distanceMeters": 1160.4},
    {"id": "3", "name": "SATRA MART", "distanceMeters": 917.0},
    {"id": "4", "name": "Bách Hóa Xanh", "distanceMeters": 2100.0},
]
LISTING = "Gần bạn có VinMart+ (891 m), Siêu Thị Co.opmart (1,2 km) và SATRA MART (917 m)."


def _no_llm(messages, max_tokens):
    raise AssertionError("không được gọi LLM khi không có knowledge")


def _patch(monkeypatch, knowledge=None, stream=_no_llm):
    monkeypatch.setattr(chat, "fetch_knowledge_map", lambda ids: knowledge or {})
    monkeypatch.setattr(chat, "_append_history", lambda *args: None)
    monkeypatch.setattr(chat, "_ollama_chat_stream", stream)


def test_explain_results_code_ghep_ten_va_khoang_cach_khong_goi_llm(monkeypatch):
    _patch(monkeypatch)
    assert list(chat.explain_results_stream("s", "siêu thị", SIEU_THI)) == [LISTING]


def test_explain_results_khong_co_ket_qua(monkeypatch):
    _patch(monkeypatch)
    assert chat.explain_results("s", "siêu thị", []) == chat._NO_RESULTS_REPLY


def test_explain_results_noi_thoi_tiet_va_do_dong(monkeypatch):
    _patch(monkeypatch)
    wet = {"isWet": True, "isHeavyRain": False}
    results = [
        {**SIEU_THI[0], "weather": wet, "weatherFactor": 1.0, "busyness": {"estimated": True, "level": "Khá đông"}},
        {**SIEU_THI[1], "weather": wet, "weatherFactor": 0.8, "busyness": {"estimated": False, "level": None}},
    ]
    reply = chat.explain_results("s", "siêu thị", results)
    assert "Trời đang mưa nên mình đã ưu tiên chỗ trong nhà." in reply
    assert "Theo ước tính, VinMart+ có vẻ đang khá đông." in reply
    assert "Co.opmart có vẻ" not in reply


def test_explain_results_khong_noi_mua_khi_thoi_tiet_khong_doi_thu_hang(monkeypatch):
    _patch(monkeypatch)
    results = [{**SIEU_THI[0], "weather": {"isWet": True}, "weatherFactor": 1.0}]
    assert "mưa" not in chat.explain_results("s", "siêu thị", results)


def test_explain_results_llm_chi_viet_phan_knowledge(monkeypatch):
    seen = {}

    def stream(messages, max_tokens):
        seen["content"] = messages[1]["content"]
        return iter(["Co.opmart từng là ", "chợ cũ. Thêm ", "ý nữa."])

    _patch(monkeypatch, knowledge={"2": {"intro": "chợ cũ"}}, stream=stream)
    pieces = list(chat.explain_results_stream("s", "siêu thị", SIEU_THI))
    # Phần code trả ngay, phần LLM gửi theo từng câu trọn vẹn.
    assert pieces == [LISTING, " Co.opmart từng là chợ cũ.", " Thêm ý nữa."]
    assert "Siêu Thị Co.opmart" in seen["content"]
    assert "VinMart+" not in seen["content"]


def test_explain_results_cat_phan_llm_toi_da_hai_cau(monkeypatch):
    closed = []

    def stream(messages, max_tokens):
        try:
            yield "Một. Hai. Ba. "
            yield "Bốn."
        finally:
            closed.append(True)

    _patch(monkeypatch, knowledge={"1": {"intro": "x"}}, stream=stream)
    assert chat.explain_results("s", "siêu thị", SIEU_THI) == LISTING + " Một. Hai."
    assert closed == [True]


def _truncated_stream(*texts):
    def stream(messages, max_tokens):
        yield from texts
        raise chat.ReplyTruncated

    return stream


def test_explain_results_bo_cau_do_khi_het_token(monkeypatch):
    _patch(monkeypatch, knowledge={"1": {"intro": "x"}}, stream=_truncated_stream("Câu một. ", "Câu hai (khoảng 16"))
    assert chat.explain_results("s", "siêu thị", SIEU_THI) == LISTING + " Câu một."


def test_explain_results_giu_phan_dang_do_khi_chua_tron_cau_nao(monkeypatch):
    _patch(monkeypatch, knowledge={"1": {"intro": "x"}}, stream=_truncated_stream("Câu dở và "))
    assert chat.explain_results("s", "siêu thị", SIEU_THI) == LISTING + " Câu dở và…"


def test_explain_results_ollama_tat_van_con_danh_sach(monkeypatch):
    _patch(monkeypatch, knowledge={"1": {"intro": "x"}}, stream=lambda messages, max_tokens: iter([]))
    assert chat.explain_results("s", "siêu thị", SIEU_THI) == LISTING


def test_format_distance():
    assert chat._format_distance(1160.4) == "1,2 km"
    assert chat._format_distance(822.3) == "822 m"
    assert chat._format_distance(999.7) == "1,0 km"
    assert chat._format_distance(None) is None


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value

    def delete(self, key: str) -> None:
        self.store.pop(key, None)


def test_set_history_nap_lai_vai_luot_cuoi_va_bo_luot_rong(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(chat.geo_cache, "get_client", lambda: fake)
    turns = [
        {"role": "user" if index % 2 == 0 else "assistant", "content": f"tin {index}"}
        for index in range(20)
    ]
    turns.append({"role": "assistant", "content": "   "})
    chat.set_history("s1", turns)
    history = chat.get_history("s1")
    assert len(history) == chat.HISTORY_MAX_TURNS * 2
    assert history[-1] == {"role": "assistant", "content": "tin 19"}


def test_set_history_rong_thi_xoa_ngu_canh_cu(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(chat.geo_cache, "get_client", lambda: fake)
    chat.set_history("s1", [{"role": "user", "content": "quán phở"}])
    chat.set_history("s1", [])
    assert chat.get_history("s1") == []

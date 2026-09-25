import json

from app import chat, translate


def _fake_ollama(calls, *, drop_key=None, garbage_key=None):
    def ollama(messages, **kwargs):
        payload = json.loads(messages[-1]["content"])
        calls.append(payload)
        out = {key: f"FR:{text}" for key, text in payload.items() if key != drop_key}
        if garbage_key in out:
            out[garbage_key] = "x" * 500
        return "```json\n" + json.dumps(out, ensure_ascii=False) + "\n```"

    return ollama


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(translate, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(translate, "_memory", {})


def test_dich_roi_cache_khong_goi_llm_lan_hai(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(chat, "_ollama_chat", _fake_ollama(calls))

    first = translate.translate_texts(["Bán kính", "Chỉ đường", "Bán kính"], "fr")
    second = translate.translate_texts(["Chỉ đường"], "fr")

    assert first == {"Bán kính": "FR:Bán kính", "Chỉ đường": "FR:Chỉ đường"}
    assert second == {"Chỉ đường": "FR:Chỉ đường"}
    assert len(calls) == 1
    # Ghi xuống đĩa: tiến trình mới (xoá cache bộ nhớ) vẫn đọc lại được.
    monkeypatch.setattr(translate, "_memory", {})
    assert translate.cached_translations("fr") == first


def test_khong_cache_ban_dich_thieu_hoac_rac(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(chat, "_ollama_chat", _fake_ollama(calls, drop_key="1", garbage_key="2"))

    result = translate.translate_texts(["Bán kính", "Tìm", "Lưu"], "fr")

    assert result == {"Lưu": "FR:Lưu"}
    assert translate.cached_translations("fr") == {"Lưu": "FR:Lưu"}


def test_ngon_ngu_goc_va_ngon_ngu_la_khong_dich(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(chat, "_ollama_chat", _fake_ollama(calls))

    assert translate.translate_texts(["Bán kính"], "vi") == {}
    assert translate.translate_texts(["Bán kính"], "xx") == {}
    assert calls == []


def test_chia_lo_theo_so_chuoi(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(chat, "_ollama_chat", _fake_ollama(calls))

    texts = [f"chuỗi {i}" for i in range(30)]
    result = translate.translate_texts(texts, "ja")

    assert len(result) == 30
    assert all(len(batch) <= translate._CHUNK_ITEMS for batch in calls)


def test_prompt_thuyet_minh_theo_ngon_ngu():
    assert "IN French" in chat._narration_system_prompt("fr")
    assert "{language}" not in chat._narration_system_prompt("km")
    assert chat._narration_system_prompt("vi") == chat._NARRATION_SYSTEM_PROMPTS["vi"]

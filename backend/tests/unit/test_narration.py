from app import chat, narration, tts

POI = "10000000-0000-0000-0000-000000000001"


def _fake_generate(calls, *, fallback=False):
    def generate(poi_id, language="vi"):
        calls.append((poi_id, language))
        return {
            "available": True,
            "narration": f"thuyết minh {len(calls)}",
            "verified": True,
            "language": language,
            "fallback": fallback,
        }

    return generate


def test_get_text_chi_goi_llm_mot_lan_roi_doc_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(tts, "CACHE_DIR", tmp_path)
    calls = []
    monkeypatch.setattr(chat, "generate_poi_narration", _fake_generate(calls))

    first = narration.get_text(POI, "vi")
    second = narration.get_text(POI, "vi")

    assert first["narration"] == second["narration"] == "thuyết minh 1"
    assert second["cached"] is True
    assert len(calls) == 1


def test_get_text_khong_cache_ban_ghep_tho_khi_ollama_chet(monkeypatch, tmp_path):
    monkeypatch.setattr(tts, "CACHE_DIR", tmp_path)
    calls = []
    monkeypatch.setattr(chat, "generate_poi_narration", _fake_generate(calls, fallback=True))

    narration.get_text(POI, "vi")
    narration.get_text(POI, "vi")

    assert len(calls) == 2
    assert tts.get_cached_text(POI, "vi") is None


def test_get_audio_doc_dung_chu_da_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(tts, "CACHE_DIR", tmp_path)
    calls = []
    monkeypatch.setattr(chat, "generate_poi_narration", _fake_generate(calls))
    spoken = []
    monkeypatch.setattr(tts, "synthesize", lambda text, language: spoken.append(text) or b"wav")

    shown = narration.get_text(POI, "vi")["narration"]
    status, result = narration.get_audio(POI, "vi")
    status_again, result_again = narration.get_audio(POI, "vi")

    assert status == status_again == "ok"
    assert spoken == [shown]
    assert result["narration"] == shown
    assert result_again["cache"] == "hit"
    assert len(calls) == 1


def test_get_audio_ngon_ngu_chua_co_giong(monkeypatch, tmp_path):
    monkeypatch.setattr(tts, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(chat, "generate_poi_narration", _fake_generate([]))

    assert narration.get_audio(POI, "en") == ("no_voice", None)
    assert narration.has_cached_audio(POI, "en") is False

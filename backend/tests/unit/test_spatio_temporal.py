from datetime import datetime
from zoneinfo import ZoneInfo

from app import spatio_temporal as st
from app.opening_hours import parse_opening_hours

TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def at(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=TZ)


def test_time_context_buckets_and_weekend():
    assert st.time_context(at(2026, 9, 7, 8)).get("bucket") == "morning"   # Monday
    assert st.time_context(at(2026, 9, 7, 12)).get("bucket") == "noon"
    assert st.time_context(at(2026, 9, 7, 20)).get("bucket") == "evening"
    assert st.time_context(at(2026, 9, 7, 23)).get("bucket") == "night"
    assert st.time_context(at(2026, 9, 7, 8))["isWeekend"] is False
    assert st.time_context(at(2026, 9, 6, 8))["isWeekend"] is True          # Sunday


def test_category_time_match():
    assert st.category_time_match("cafe", "morning") == 1.0
    assert st.category_time_match("cafe", "night") == 0.0
    assert st.category_time_match("bar", "night") == 1.0
    assert st.category_time_match("hospital", "morning") is None  # trung tính


def test_eta_minutes_orders_modes_by_speed():
    eta = st.eta_minutes(3000)
    assert eta["walk"] > eta["motorbike"] > eta["car"]
    assert st.eta_minutes(None) is None
    assert st.eta_minutes(50)["walk"] >= 1  # tối thiểu 1 phút


def test_context_score_open_vs_closed_vs_unknown():
    assert st._context_score(True, 120, 1.0) > st._context_score(True, 120, 0.0)
    assert st._context_score(True, 10, 1.0) < st._context_score(True, 120, 1.0)  # sắp đóng
    assert st._context_score(False, None, 1.0) < st._context_score(None, None, 1.0)  # đóng < chưa rõ


def _candidate(poi_id, category, distance, hours="Mo-Su 08:00-22:00"):
    return {
        "id": poi_id,
        "category": category,
        "categoryLabel": category,
        "distanceMeters": distance,
        "openingHours": parse_opening_hours(hours),
        "timezone": "Asia/Ho_Chi_Minh",
    }


def test_enrich_candidates_attaches_context(monkeypatch):
    monkeypatch.setattr(
        st, "windowed_popularity",
        lambda ids, database_url=None: {"a": {"w15": 4, "w1h": 6, "w24h": 10}},
    )
    candidates = [
        _candidate("a", "cafe", 500),
        _candidate("b", "cafe", 1500),
    ]
    out = st.enrich_candidates(candidates, at=at(2026, 9, 7, 9))  # Monday morning

    a, b = out[0], out[1]
    assert a["openNow"] is True and a["closesInMinutes"] == 780
    assert a["etaMinutes"]["walk"] > a["etaMinutes"]["car"]
    assert a["timeContext"]["categoryMatchesTime"] == 1.0  # cafe buổi sáng
    # recency chuẩn hóa: POI có event -> 1.0, POI không có -> 0.0
    assert a["recencyScore"] == 1.0
    assert b["recencyScore"] == 0.0
    assert 0.0 <= a["contextScore"] <= 1.0


def test_busyness_estimate_needs_minimum_data():
    thin = {"w15": 0, "w1h": 1, "w24h": 1}  # tổng 2 < ngưỡng 3
    assert st._busyness_estimate(thin, recency_score=0.9) == {
        "estimated": False,
        "level": None,
        "score": None,
    }


def test_busyness_estimate_levels_by_relative_recency():
    enough = {"w15": 2, "w1h": 2, "w24h": 2}  # tổng 6 >= ngưỡng
    assert st._busyness_estimate(enough, recency_score=0.9)["level"] == "Đông"
    assert st._busyness_estimate(enough, recency_score=0.5)["level"] == "Khá đông"
    assert st._busyness_estimate(enough, recency_score=0.1)["level"] == "Vắng"
    result = st._busyness_estimate(enough, recency_score=0.9)
    assert result["estimated"] is True
    assert result["score"] == 0.9


def test_busyness_needs_activity_in_last_hour():
    # Chỉ có tương tác của 24 giờ trước: lúc 2 giờ sáng không được nói "Đông".
    stale = {"w15": 0, "w1h": 0, "w24h": 12}
    assert st._busyness_estimate(stale, recency_score=1.0)["estimated"] is False


def test_busyness_never_busy_when_closed():
    recent = {"w15": 2, "w1h": 4, "w24h": 8}
    assert st._busyness_estimate(recent, recency_score=1.0, open_now=False)["estimated"] is False
    assert st._busyness_estimate(recent, recency_score=1.0, open_now=None)["level"] == "Đông"


def test_enrich_candidates_attaches_busyness(monkeypatch):
    monkeypatch.setattr(
        st, "windowed_popularity",
        lambda ids, database_url=None: {"a": {"w15": 4, "w1h": 6, "w24h": 10}},
    )
    out = st.enrich_candidates(
        [_candidate("a", "cafe", 500), _candidate("b", "cafe", 1500)],
        at=at(2026, 9, 7, 9),
    )
    a, b = out[0], out[1]
    assert a["busyness"] == {"estimated": True, "level": "Đông", "score": 1.0}
    # "b" không có sự kiện nào -> thiếu dữ liệu, KHÔNG được gắn nhãn "Vắng"
    assert b["busyness"] == {"estimated": False, "level": None, "score": None}


def test_enrich_survives_db_error(monkeypatch):
    import psycopg

    def boom(ids, database_url=None):
        raise psycopg.OperationalError("no db")

    monkeypatch.setattr(st, "windowed_popularity", boom)
    out = st.enrich_candidates([_candidate("a", "cafe", 500)], at=at(2026, 9, 7, 9))

    assert out[0]["recencyScore"] == 0.0  # không có popularity nhưng vẫn enrich được
    assert out[0]["contextScore"] > 0
    assert out[0]["busyness"]["estimated"] is False  # DB lỗi -> không giả vờ có số liệu

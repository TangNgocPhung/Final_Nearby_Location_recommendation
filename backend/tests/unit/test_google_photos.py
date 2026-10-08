"""Check identity matching and transient failures without paid API requests."""

from app import google_photos


CONTEXT = {"name": "Hoang Minh", "latitude": 10.77, "longitude": 106.70}


def candidate(name="Hoang Minh", latitude=10.77):
    return {
        "id": "test", "displayName": {"text": name},
        "location": {"latitude": latitude, "longitude": 106.70},
        "photos": [{"name": "places/test/photos/photo"}],
        "googleMapsUri": "https://maps.google.com/?cid=123",
    }


def test_matching_place_returns_photo_and_author(monkeypatch):
    place = candidate()
    place["photos"][0]["authorAttributions"] = [{"displayName": "Photographer", "uri": "https://maps.google.com/profile"}]
    monkeypatch.setattr(google_photos, "_request", lambda path, body=None: {"places": [place]} if body else {"photoUri": "https://lh3.googleusercontent.com/photo"})
    result = google_photos.place_photos("poi", CONTEXT, 8)
    assert result["status"] == "ready"
    assert result["photos"][0]["source"] == "google"
    assert result["photos"][0]["confidence"] == "place"
    assert result["photos"][0]["authorAttributions"][0]["displayName"] == "Photographer"
    assert "key=" not in result["photos"][0]["url"]


def test_nearby_different_business_is_rejected(monkeypatch):
    monkeypatch.setattr(google_photos, "_request", lambda *args: {"places": [candidate("Other Business")]})
    assert google_photos.place_photos("poi", CONTEXT, 8)["status"] == "empty"


def test_same_name_far_away_is_rejected(monkeypatch):
    monkeypatch.setattr(google_photos, "_request", lambda *args: {"places": [candidate(latitude=10.78)]})
    assert google_photos.place_photos("poi", CONTEXT, 8)["status"] == "empty"


def test_ambiguous_branches_are_rejected(monkeypatch):
    monkeypatch.setattr(google_photos, "_request", lambda *args: {"places": [candidate(), candidate()]})
    assert google_photos.place_photos("poi", CONTEXT, 8)["status"] == "empty"


def test_search_failure_is_not_empty(monkeypatch):
    monkeypatch.setattr(google_photos, "_request", lambda *args: None)
    assert google_photos.place_photos("poi", CONTEXT, 8)["status"] == "unavailable"


def test_successful_empty_search(monkeypatch):
    monkeypatch.setattr(google_photos, "_request", lambda *args: {})
    assert google_photos.place_photos("poi", CONTEXT, 8)["status"] == "empty"


def test_media_failure_is_not_empty(monkeypatch):
    monkeypatch.setattr(google_photos, "_request", lambda path, body=None: {"places": [candidate()]} if body else None)
    assert google_photos.place_photos("poi", CONTEXT, 8)["status"] == "unavailable"

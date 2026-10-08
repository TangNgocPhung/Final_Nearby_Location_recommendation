from scripts import probe_foursquare_photos as fsq

POI = {"id": "poi", "name": "Hoang Minh", "latitude": 10.77, "longitude": 106.70}


def candidate(name="Hoang Minh", latitude=10.77):
    return {"fsq_place_id": "place", "name": name, "latitude": latitude, "longitude": 106.70}


def test_accepts_same_name_at_location():
    assert fsq.choose_match(POI, [candidate()])["fsq_place_id"] == "place"


def test_rejects_nearby_different_business():
    assert fsq.choose_match(POI, [candidate("Other Store")]) is None


def test_rejects_same_name_far_away():
    assert fsq.choose_match(POI, [candidate(latitude=10.78)]) is None


def test_rejects_ambiguous_branches():
    assert fsq.choose_match(POI, [candidate(), candidate()]) is None


def test_rejects_missing_coordinates():
    assert fsq.choose_match(POI, [{"fsq_place_id": "place", "name": "Hoang Minh"}]) is None


def test_only_requests_photos_for_matched_place(monkeypatch):
    calls = []

    def request(path, params, key):
        calls.append(path)
        return {"results": [candidate("Other Store")]}

    monkeypatch.setattr(fsq, "request", request)
    assert fsq.probe(POI, "test-key")["status"] == "unmatched"
    assert calls == ["search"]


def test_counts_matched_place_photos(monkeypatch):
    monkeypatch.setattr(fsq, "request", lambda path, params, key: {"results": [candidate()]} if path == "search" else [{"id": "photo"}])
    result = fsq.probe(POI, "test-key")
    assert result["status"] == "photos"
    assert result["photoCount"] == 1

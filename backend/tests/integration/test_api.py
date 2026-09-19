import os

import httpx
import pytest


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_INTEGRATION") != "1",
        reason="set RUN_INTEGRATION=1 and start the Docker Compose stack",
    ),
]

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")


def test_health_and_categories_use_migrated_database() -> None:
    with httpx.Client(base_url=API_BASE_URL, timeout=10) as client:
        health = client.get("/health")
        categories = client.get("/api/v1/categories")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert categories.status_code == 200
    assert any(item["category"] == "cafe" for item in categories.json())


def test_contextual_search_parses_location_and_returns_ranked_pois() -> None:
    response = httpx.post(
        f"{API_BASE_URL}/api/v1/search",
        timeout=10,
        headers={"X-Session-ID": "11111111-1111-4111-8111-111111111111"},
        json={
            "query": "cà phê gần Bến Thành",
            "latitude": 10.7757,
            "longitude": 106.7009,
            "radius": 5000,
            "limit": 10,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["parsedLocation"]["matched"] is True
    assert payload["parsedLocation"]["locationText"] == "bến thành"
    assert payload["results"]
    assert all("score" in poi and "distanceMeters" in poi for poi in payload["results"])
    assert all("h3Cells" in poi and "embeddingModel" in poi for poi in payload["results"])
    assert all("openingHours" in poi and "openNow" in poi for poi in payload["results"])
    # Backend truy xuất phải lộ ra để biết số liệu đo được là của kiến trúc đa
    # kênh hay của đường dự phòng PostGIS. CI dựng chỉ mục trước khi chạy test,
    # nên ở đây phải là "opensearch" — nếu thành "postgis" nghĩa là bước dựng
    # chỉ mục hỏng và relevance gate đang đo nhầm hệ thống.
    assert payload["retrievalBackend"] == "opensearch"
    # rank phải khớp ĐÚNG thứ tự trả về và bắt đầu từ 0. Các assert kiểu "có
    # chứa key" ở trên không bắt được việc quên trả rank, nên đây là chỗ duy
    # nhất kiểm chứng. 0-based là bắt buộc: UI hiển thị rank+1, lấy nhầm gốc
    # thì mọi phân tích CTR theo vị trí lệch đúng một bậc mà không ai thấy.
    assert [poi["rank"] for poi in payload["results"]] == list(range(len(payload["results"])))


def test_data_status_reports_enrichment_coverage() -> None:
    response = httpx.get(f"{API_BASE_URL}/api/v1/data/status", timeout=10)
    assert response.status_code == 200
    pois = response.json()["pois"]
    assert pois["total"] >= 28
    assert pois["with_h3"] == pois["total"]
    assert pois["with_embedding"] == pois["total"]


def test_suggest_returns_matching_poi_names_for_autocomplete() -> None:
    """"Cà phê Bến Nghé" (seed 0002) phải khớp cả khi gõ một phần tên — đây là
    gợi ý gõ-tới-đâu cho ô tìm kiếm, không phải tìm kiếm đầy đủ, nên response
    phải nhẹ (không kèm rating/popularity/context) và rất nhanh."""
    response = httpx.get(
        f"{API_BASE_URL}/api/v1/pois/suggest",
        timeout=10,
        params={"q": "Bến Nghé", "lat": 10.7757, "lng": 106.7009, "limit": 5},
    )

    assert response.status_code == 200
    results = response.json()
    assert results
    assert any(item["name"] == "Cà phê Bến Nghé" for item in results)
    first = results[0]
    assert first.keys() == {
        "id",
        "name",
        "categoryLabel",
        "address",
        "latitude",
        "longitude",
        "distanceMeters",
    }
    assert isinstance(first["distanceMeters"], float)


def test_suggest_without_location_omits_distance() -> None:
    response = httpx.get(
        f"{API_BASE_URL}/api/v1/pois/suggest",
        timeout=10,
        params={"q": "Bến Nghé"},
    )

    assert response.status_code == 200
    results = response.json()
    assert results
    assert all(item["distanceMeters"] is None for item in results)


def test_suggest_rejects_empty_query() -> None:
    response = httpx.get(
        f"{API_BASE_URL}/api/v1/pois/suggest",
        timeout=10,
        params={"q": ""},
    )

    assert response.status_code == 422

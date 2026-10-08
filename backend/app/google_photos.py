"""Google place photos fetched on demand; Google content is not stored."""

from __future__ import annotations

import json
import logging
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from .config import settings
from .poi_ratings import haversine_meters, name_similarity

logger = logging.getLogger("nearby-google-photos")
_slots = threading.BoundedSemaphore(2)
_PHOTO_NAME = re.compile(r"places/[A-Za-z0-9_-]+/photos/[A-Za-z0-9_-]+")


def _request(path: str, body: dict[str, Any] | None = None) -> dict[str, Any] | None:
    headers = {"X-Goog-Api-Key": settings.google_maps_api_key}
    if body is not None:
        headers.update({
            "Content-Type": "application/json",
            "X-Goog-FieldMask": "places.id,places.displayName,places.location,places.photos,places.googleMapsUri",
        })
    request = urllib.request.Request(
        "https://places.googleapis.com/v1/" + path,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=6) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        # Do not log URLs or request headers containing credentials.
        logger.warning("Google Places HTTP %s", error.code)
    except (urllib.error.URLError, OSError, ValueError):
        logger.warning("Google Places request unavailable")
    return None


def _photo(photo: dict[str, Any], place: dict[str, Any]) -> dict[str, Any] | None:
    name = photo.get("name", "")
    if not _PHOTO_NAME.fullmatch(name):
        return None
    media = _request(name + "/media?maxWidthPx=1000&skipHttpRedirect=true") or {}
    url = media.get("photoUri")
    if not isinstance(url, str) or not url.startswith("https://"):
        return None
    return {
        "id": name, "url": url, "thumbUrl": url,
        "width": photo.get("widthPx"), "height": photo.get("heightPx"),
        "title": (place.get("displayName") or {}).get("text", "Google Maps"),
        "confidence": "place", "distanceMeters": None,
        "source": "google", "sourceUrl": photo.get("googleMapsUri") or place.get("googleMapsUri"),
        "license": None,
        "attribution": ", ".join(author.get("displayName", "") for author in photo.get("authorAttributions", [])),
        "authorAttributions": photo.get("authorAttributions", []),
    }


def place_photos(poi_id: str, context: dict[str, Any], limit: int) -> dict[str, Any]:
    result: dict[str, Any] = {"poiId": poi_id, "status": "unavailable", "fetchedAt": None, "photos": []}
    if not context.get("name") or not _slots.acquire(timeout=0.1):
        return result
    try:
        payload = _request("places:searchText", {
            "textQuery": context["name"], "languageCode": "vi", "regionCode": "VN",
            "pageSize": 5,
            "locationBias": {"circle": {
                "center": {"latitude": context["latitude"], "longitude": context["longitude"]},
                "radius": 200.0,
            }},
        })
        if payload is None:
            return result
        matches = []
        for place in payload.get("places", []):
            location = place.get("location") or {}
            if location.get("latitude") is None or location.get("longitude") is None:
                continue
            distance = haversine_meters(context["latitude"], context["longitude"], location["latitude"], location["longitude"])
            similarity = name_similarity(context["name"], (place.get("displayName") or {}).get("text"))
            if distance <= 100 and similarity >= 0.7:
                matches.append((similarity, distance, place))
        matches.sort(key=lambda match: (-match[0], match[1]))
        # Ambiguous branches should remain without a photo rather than pick one.
        if not matches or (len(matches) > 1 and matches[0][0] == matches[1][0] and abs(matches[0][1] - matches[1][1]) < 20):
            result["status"] = "empty"
            return result
        place = matches[0][2]
        candidates = place.get("photos", [])[:limit]
        with ThreadPoolExecutor(max_workers=4) as pool:
            result["photos"] = [photo for photo in pool.map(lambda candidate: _photo(candidate, place), candidates) if photo]
        result["status"] = "ready" if result["photos"] else ("unavailable" if candidates else "empty")
        result["fetchedAt"] = datetime.now(timezone.utc).isoformat()
        return result
    finally:
        _slots.release()

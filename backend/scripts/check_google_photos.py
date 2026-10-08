"""Run one Google Places probe without printing credentials or photo URLs."""

import json
import urllib.error
import urllib.request

from dotenv import load_dotenv

load_dotenv(".env")

from app.config import settings
from app.google_photos import _photo


def main() -> int:
    request = urllib.request.Request(
        "https://places.googleapis.com/v1/places:searchText",
        data=json.dumps({"textQuery": "Dai Nuong Soup 771 Nguyen Trai Ho Chi Minh", "pageSize": 1}).encode(),
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": settings.google_maps_api_key,
            "X-Goog-FieldMask": "places.id,places.displayName,places.location,places.photos,places.googleMapsUri",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        details = json.load(error).get("error", {})
        message = details.get("message", "")
        if settings.google_maps_api_key:
            message = message.replace(settings.google_maps_api_key, "[redacted]")
        reasons = [detail.get("reason") for detail in details.get("details", []) if detail.get("reason")]
        print(json.dumps({"status": error.code, "message": message, "reasons": reasons}))
        return 1
    except (urllib.error.URLError, OSError):
        print("Google Places network unavailable")
        return 1
    places = payload.get("places", [])
    photo = None
    if places and places[0].get("photos"):
        photo = _photo(places[0]["photos"][0], places[0])
    print(json.dumps({"status": 200, "places": len(places), "photoLoaded": photo is not None}))
    return 0 if photo else 1


if __name__ == "__main__":
    raise SystemExit(main())

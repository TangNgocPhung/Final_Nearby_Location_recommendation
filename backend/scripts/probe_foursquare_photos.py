"""Read-only trial of Foursquare photo coverage for a small local POI sample.

Run from the repository root: python backend/scripts/probe_foursquare_photos.py
Set FOURSQUARE_API_KEY and DATABASE_URL in the environment or local .env.
No provider data or changes are written to the database.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
load_dotenv(BACKEND_ROOT.parent / ".env")

import psycopg
from psycopg.rows import dict_row

from app.config import settings
from app.poi_ratings import haversine_meters, name_similarity

API_ROOT = "https://places-api.foursquare.com/places/"


def request(path: str, params: dict[str, Any], key: str) -> Any:
    url = API_ROOT + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + key,
        "X-Places-Api-Version": "2025-06-17",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.load(response)


def choose_match(poi: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    matches = []
    for candidate in candidates:
        lat, lng = candidate.get("latitude"), candidate.get("longitude")
        if lat is None or lng is None or not candidate.get("fsq_place_id"):
            continue
        distance = haversine_meters(poi["latitude"], poi["longitude"], lat, lng)
        similarity = name_similarity(poi["name"], candidate.get("name"))
        if distance <= 100 and similarity >= 0.7:
            matches.append((similarity, distance, candidate))
    matches.sort(key=lambda item: (-item[0], item[1]))
    if not matches:
        return None
    if len(matches) > 1 and matches[0][0] == matches[1][0] and abs(matches[0][1] - matches[1][1]) < 20:
        return None
    return {**matches[0][2], "matchDistanceMeters": round(matches[0][1]), "nameSimilarity": matches[0][0]}


def probe(poi: dict[str, Any], key: str) -> dict[str, Any]:
    search = request("search", {
        "query": poi["name"], "ll": f'{poi["latitude"]},{poi["longitude"]}',
        "radius": 300, "limit": 5,
        "fields": "fsq_place_id,name,latitude,longitude",
    }, key)
    match = choose_match(poi, search.get("results", []))
    result = {"poiId": poi["id"], "name": poi["name"], "status": "unmatched", "photoCount": 0}
    if match is None:
        return result
    fsq_id = urllib.parse.quote(match["fsq_place_id"], safe="")
    photos = request(fsq_id + "/photos", {"limit": 3}, key)
    result.update({
        "status": "photos" if photos else "matched_without_photos",
        "photoCount": len(photos), "foursquareId": match["fsq_place_id"],
        "matchedName": match["name"], "distanceMeters": match["matchDistanceMeters"],
        "nameSimilarity": match["nameSimilarity"],
    })
    return result


def sample(limit: int) -> list[dict[str, Any]]:
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        return list(conn.execute("""
            SELECT id::text AS id, name,
                   ST_Y(location::geometry) AS latitude,
                   ST_X(location::geometry) AS longitude
            FROM pois WHERE name IS NOT NULL AND name <> ''
              AND ST_Y(location::geometry) BETWEEN 10.70 AND 10.90
              AND ST_X(location::geometry) BETWEEN 106.60 AND 106.82
            ORDER BY md5(id::text) LIMIT %s
        """, (limit,)).fetchall())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=10, choices=range(1, 11))
    parser.add_argument("--check-access", action="store_true", help="Check API access without a database connection")
    args = parser.parse_args()
    key = os.getenv("FOURSQUARE_API_KEY", "").strip()
    if not key:
        print("Missing FOURSQUARE_API_KEY. Add it to the repository .env before running the trial.", file=sys.stderr)
        return 2
    if args.check_access:
        try:
            data = request("search", {
                "query": "coffee", "ll": "10.7757,106.7009", "radius": 1000,
                "limit": 1, "fields": "fsq_place_id,name,latitude,longitude",
            }, key)
            candidates = data.get("results", [])
            photos = []
            if candidates:
                place_id = urllib.parse.quote(candidates[0]["fsq_place_id"], safe="")
                photos = request(place_id + "/photos", {"limit": 1}, key)
        except urllib.error.HTTPError as error:
            try:
                detail = json.load(error)
            except ValueError:
                detail = {}
            message = str(detail.get("message", "API access denied")).replace(key, "[redacted]")
            print(json.dumps({"httpStatus": error.code, "message": message}))
            return 1
        except (urllib.error.URLError, OSError, ValueError):
            print("Foursquare network unavailable", file=sys.stderr)
            return 1
        print(json.dumps({"httpStatus": 200, "candidates": len(candidates), "photoCount": len(photos)}))
        return 0
    try:
        pois = sample(args.limit)
    except psycopg.Error:
        print("Database unavailable. Set DATABASE_URL to the running local database.", file=sys.stderr)
        return 2
    results = []
    for poi in pois:
        try:
            result = probe(poi, key)
        except urllib.error.HTTPError as error:
            result = {"poiId": poi["id"], "name": poi["name"], "status": "unavailable", "httpStatus": error.code}
            results.append(result)
            if error.code in (401, 402, 403, 429):
                break
            continue
        except (urllib.error.URLError, OSError, ValueError):
            result = {"poiId": poi["id"], "name": poi["name"], "status": "unavailable"}
        results.append(result)
        time.sleep(0.25)
    print(json.dumps({
        "sampleSize": len(pois), "attempted": len(results),
        "withPhotos": sum(row["status"] == "photos" for row in results),
        "unmatched": sum(row["status"] == "unmatched" for row in results),
        "matchedWithoutPhotos": sum(row["status"] == "matched_without_photos" for row in results),
        "unavailable": sum(row["status"] == "unavailable" for row in results),
        "note": "Automatic name/location matches require visual review of the photos before use.",
        "results": results,
    }, ensure_ascii=False, indent=2))
    return 1 if any(row["status"] == "unavailable" for row in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())

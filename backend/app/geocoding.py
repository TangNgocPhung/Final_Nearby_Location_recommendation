import re
import unicodedata
from typing import Any

import psycopg
from psycopg.rows import dict_row


LOCATION_PATTERN = re.compile(
    r"^(?P<subject>.*?)\s+(?:gần|quanh|ở|tại|near)\s+(?P<location>.+)$",
    flags=re.IGNORECASE,
)

# Các cụm chỉ vị trí hiện tại (đại từ chỉ định "đây"/"này", không phải tên địa
# danh thật) — đo được thật (2026-09-20): "parking gần đây" tách subject=
# "parking", location="đây", rồi "đây" bị fuzzy-match nhầm thành tên POI
# "TH-Anh Đây" cách xa 64km, khiến toàn bộ kết quả tìm kiếm bị lệch tâm sang
# vị trí sai thay vì dùng device location. Các cụm này KHÔNG được đưa vào
# geocode — coi như không có locationText, giữ nguyên tâm tìm kiếm gốc.
DEICTIC_LOCATION_TERMS = {
    "đây",
    "đây gần",
    "chỗ này",
    "khu này",
    "khu vực này",
    "vị trí này",
    "vị trí hiện tại",
    "đây gần đó",
}


def normalize_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).strip().lower().split())


def split_subject_and_location(text: str) -> tuple[str, str | None]:
    normalized = normalize_text(text)
    match = LOCATION_PATTERN.match(normalized)
    if not match:
        return normalized, None
    subject = match.group("subject").strip()
    location = match.group("location").strip()
    if location in DEICTIC_LOCATION_TERMS:
        # "gần đây" = "nearby" (vị trí hiện tại), không phải tên địa danh cần
        # geocode — giữ subject đã tách ("parking"), bỏ phần "gần đây" vì nó
        # không mang nghĩa tìm kiếm gì thêm cho BM25.
        return subject, None
    return subject, location


def parse_location(
    database_url: str,
    text: str,
    latitude: float | None = None,
    longitude: float | None = None,
) -> dict[str, Any]:
    subject, location_text = split_subject_and_location(text)
    if not location_text:
        return {
            "subject": subject,
            "locationText": None,
            "matched": False,
            "candidates": [],
        }

    distance_expression = "NULL::float8"
    params: dict[str, Any] = {"location_text": location_text}
    if latitude is not None and longitude is not None:
        distance_expression = """
            ST_Distance(
                location,
                ST_SetSRID(ST_Point(%(longitude)s, %(latitude)s), 4326)::geography
            )
        """
        params.update(latitude=latitude, longitude=longitude)

    query = f"""
        WITH candidates AS (
            SELECT
                canonical_name,
                address,
                ST_Y(location::geometry) AS latitude,
                ST_X(location::geometry) AS longitude,
                similarity(alias, %(location_text)s) AS lexical_score,
                priority,
                {distance_expression} AS distance_meters,
                'gazetteer'::text AS source
            FROM geo_aliases
            WHERE alias %% %(location_text)s
               OR alias ILIKE '%%' || %(location_text)s || '%%'
               OR %(location_text)s ILIKE '%%' || alias || '%%'
            UNION ALL
            SELECT
                name AS canonical_name,
                address,
                ST_Y(location::geometry) AS latitude,
                ST_X(location::geometry) AS longitude,
                GREATEST(similarity(name, %(location_text)s), similarity(address, %(location_text)s)),
                70 AS priority,
                {distance_expression} AS distance_meters,
                'poi'::text AS source
            FROM pois
            WHERE name %% %(location_text)s
               OR address %% %(location_text)s
               OR name ILIKE '%%' || %(location_text)s || '%%'
        )
        SELECT
            canonical_name AS "canonicalName",
            address,
            latitude,
            longitude,
            source,
            distance_meters AS "distanceMeters",
            LEAST(0.99, 0.35 + lexical_score * 0.5 + priority / 1000.0) AS confidence
        FROM candidates
        ORDER BY confidence DESC, distance_meters ASC NULLS LAST
        LIMIT 5
    """
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            candidates = list(cursor.fetchall())

    best = candidates[0] if candidates else None
    return {
        "subject": subject,
        "locationText": location_text,
        "matched": best is not None,
        "bestMatch": best,
        "candidates": candidates,
    }


def reverse_geocode(database_url: str, latitude: float, longitude: float) -> dict[str, Any]:
    query = """
        WITH candidates AS (
            SELECT name, address, location, 'poi'::text AS source FROM pois
            UNION ALL
            SELECT canonical_name, address, location, 'gazetteer'::text FROM geo_aliases
        )
        SELECT
            name,
            address,
            source,
            ST_Distance(
                location,
                ST_SetSRID(ST_Point(%(longitude)s, %(latitude)s), 4326)::geography
            ) AS "distanceMeters"
        FROM candidates
        ORDER BY location <-> ST_SetSRID(ST_Point(%(longitude)s, %(latitude)s), 4326)::geography
        LIMIT 1
    """
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, {"latitude": latitude, "longitude": longitude})
            match = cursor.fetchone()
    return {
        "latitude": latitude,
        "longitude": longitude,
        "match": match,
    }

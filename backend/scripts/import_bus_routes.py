"""Nhập tuyến + trạm xe buýt từ OpenStreetMap (relation route=bus) — xem app/bus.py.

    python -m scripts.import_bus_routes                      # tải từ Overpass
    python -m scripts.import_bus_routes --save-raw results/bus_osm.json
    python -m scripts.import_bus_routes --input results/bus_osm.json

Mỗi lần chạy THAY TOÀN BỘ dữ liệu xe buýt. Overpass hay quá tải (504) với truy
vấn ~28 MB này — lưu ảnh chụp bằng --save-raw để nhập lại không cần mạng.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app import bus
from app.config import settings
from app.poi_import import fetch_overpass_elements, parse_bbox


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bbox", default=settings.osm_bbox, help="south,west,north,east")
    parser.add_argument("--input", type=Path, help="đọc ảnh chụp Overpass JSON thay vì tải")
    parser.add_argument("--save-raw", type=Path, help="lưu ảnh chụp Overpass JSON vừa tải")
    args = parser.parse_args()

    if args.input:
        elements = json.loads(args.input.read_text(encoding="utf-8")).get("elements", [])
    else:
        bbox = parse_bbox(args.bbox)
        elements = fetch_overpass_elements(
            settings.overpass_url, bbox, timeout_seconds=330, query=bus.build_overpass_query(bbox)
        )
        if args.save_raw:
            args.save_raw.parent.mkdir(parents=True, exist_ok=True)
            args.save_raw.write_text(json.dumps({"elements": elements}, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(bus.import_bus_elements(settings.database_url, elements), ensure_ascii=False))


if __name__ == "__main__":
    main()

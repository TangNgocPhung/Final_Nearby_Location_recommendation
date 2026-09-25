"""Dữ liệu gửi xe: dựng lại bảng `parking_facilities` và/hoặc nhập trạm sạc
từ Open Charge Map.

    python -m scripts.import_parking --refresh
    OPENCHARGEMAP_API_KEY=... python -m scripts.import_parking --openchargemap
"""

from __future__ import annotations

import argparse
import json
import os

from app.charging_import import fetch, import_items
from app.config import settings
from app.parking import refresh_facilities
from app.poi_import import parse_bbox


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="dựng lại parking_facilities từ thẻ gốc")
    parser.add_argument("--openchargemap", action="store_true", help="nhập trạm sạc từ Open Charge Map")
    parser.add_argument("--bbox", default=settings.osm_bbox, help="south,west,north,east")
    args = parser.parse_args()

    result: dict[str, object] = {}
    if args.openchargemap:
        api_key = os.environ.get("OPENCHARGEMAP_API_KEY")
        if not api_key:
            raise SystemExit("Thiếu OPENCHARGEMAP_API_KEY (đăng ký miễn phí tại openchargemap.org)")
        items = fetch(api_key, parse_bbox(args.bbox))
        result["openchargemap"] = import_items(settings.database_url, items)
    if args.refresh or not args.openchargemap:
        result["facilities"] = refresh_facilities(settings.database_url)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

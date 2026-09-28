"""Xác minh POI bằng biển hiệu trong ảnh đường phố — chạy nền theo lô.

Chạy (trong container backend, Ollama chạy trên máy host):
    # Thử 3 POI, KHÔNG ghi database
    python -m scripts.verify_storefronts --limit 3 --dry-run

    # Tập mẫu cho luận văn: ~150 POI khách sạn/quán ăn/cà phê/cửa hàng ở Q1-Q3-Q5
    python -m scripts.verify_storefronts --limit 150

    # Đo độ chính xác sau khi đã gán nhãn tay cột `label` trong CSV
    python -m scripts.verify_storefronts --report results/storefront_verification.csv

Cần migration `0026_poi_verifications`. Xem `app/storefront.py` về cách đọc
biển hiệu và luật kết luận.

**Chậm là bình thường.** Máy dev không có GPU: model thị giác đọc một ảnh mất
3-50 giây, mỗi POI đọc tối đa 5 ảnh (dừng sớm khi đã khớp). 150 POI ≈ 1-2 giờ.
Script ghi DB sau MỖI POI và bỏ qua POI đã xác minh (trừ khi `--force`), nên
dừng giữa chừng rồi chạy lại là chạy tiếp, không làm lại từ đầu.

**Chọn mẫu tất định.** Thứ tự lấy mẫu là `md5(poi_id || seed)`, nên cùng
`--seed` luôn ra cùng tập POI — người khác chạy lại được đúng thí nghiệm.

**Gán nhãn để đo độ chính xác.** CSV xuất ra có cột `label` để trống. Mở ảnh
bằng chứng (cột `evidence_url`) và điền:
- `dung` — kết luận của hệ thống đúng (biển đúng là quán này / đúng là đã đổi).
- `sai`  — kết luận sai.
Để trống = chưa xem, không tính. `--report` in precision theo từng trạng thái.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from app import storefront
from app.config import settings

# Q1, Q3, Q5, Q10 — nơi Mapillary phủ dày (đo 2026-09-25) và nhiều biển hiệu.
DEFAULT_BBOX = "10.750,106.650,10.800,106.710"  # south,west,north,east
# Hạn mức theo loại: loại có biển hiệu rõ, tên riêng dễ đọc.
DEFAULT_QUOTAS = {
    "hotel": 40,
    "restaurant": 45,
    "cafe": 40,
    "clothes": 8,
    "electronics": 8,
    "pharmacy": 5,
    "bakery": 4,
}
DEFAULT_OUTPUT = Path("results/storefront_verification.csv")


def sample_pois(limit: int, seed: str, bbox: str, force: bool) -> list[dict]:
    south, west, north, east = (float(v) for v in bbox.split(","))
    total = sum(DEFAULT_QUOTAS.values())
    quotas = {cat: max(1, round(n * limit / total)) for cat, n in DEFAULT_QUOTAS.items()}
    with psycopg.connect(settings.database_url, row_factory=dict_row) as connection:
        rows = connection.execute(
            """
            WITH ranked AS (
                SELECT p.id::text AS "poiId", p.name, p.category,
                       ST_Y(p.location::geometry) AS latitude,
                       ST_X(p.location::geometry) AS longitude,
                       v.poi_id IS NOT NULL AS done,
                       ROW_NUMBER() OVER (
                           PARTITION BY p.category ORDER BY md5(p.id::text || %(seed)s)
                       ) AS rn
                FROM pois p
                LEFT JOIN poi_verifications v ON v.poi_id = p.id
                WHERE p.category = ANY(%(cats)s)
                  AND length(regexp_replace(coalesce(p.name, ''), '\\s', '', 'g')) >= 4
                  AND p.location && ST_MakeEnvelope(%(west)s, %(south)s, %(east)s, %(north)s, 4326)::geography
            )
            -- Lọc POI đã xác minh SAU khi xếp hạng: lọc trước thì chạy lại sẽ
            -- lấy thêm POI mới bù hạn mức, tập mẫu không còn tất định theo seed.
            SELECT * FROM ranked WHERE %(force)s OR NOT done
            """,
            {
                "seed": seed,
                "cats": list(quotas),
                "west": west, "south": south, "east": east, "north": north,
                "force": force,
            },
        ).fetchall()
    picked = [row for row in rows if row["rn"] <= quotas[row["category"]]]
    picked.sort(key=lambda row: (row["category"], row["rn"]))
    return picked[:limit]


def export_csv(path: Path) -> None:
    """Xuất TOÀN BỘ bảng poi_verifications — kể cả POI xác minh ở lượt chạy trước,
    vì chạy tiếp sau khi dừng giữa chừng thì lượt sau chỉ còn POI chưa làm."""
    with psycopg.connect(settings.database_url, row_factory=dict_row) as connection:
        rows = connection.execute(
            """
            SELECT p.id::text AS poi_id, p.name, p.category, v.status, v.score,
                   v.matched_text, v.evidence_image_id, v.evidence_captured_at, v.evidence
            FROM poi_verifications v JOIN pois p ON p.id = v.poi_id
            ORDER BY v.status, p.category, p.name
            """
        ).fetchall()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["poi_id", "name", "category", "status", "score", "matched_text",
             "evidence_url", "evidence_captured_at", "images_read", "all_texts", "label"]
        )
        for row in rows:
            texts = [" | ".join(r.get("texts") or []) for r in row["evidence"] or []]
            writer.writerow(
                [
                    row["poi_id"], row["name"], row["category"], row["status"],
                    row["score"], row["matched_text"] or "",
                    f"https://www.mapillary.com/app/?pKey={row['evidence_image_id']}"
                    if row["evidence_image_id"] else "",
                    row["evidence_captured_at"].date().isoformat() if row["evidence_captured_at"] else "",
                    len(row["evidence"] or []),
                    " || ".join(texts)[:500],
                    "",
                ]
            )


def report(path: Path) -> None:
    with path.open(encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    by_status = Counter(row["status"] for row in rows)
    print(f"{len(rows)} POI trong {path}")
    for status, count in by_status.most_common():
        print(f"  {status:<11} {count:>4}  ({count / len(rows):.0%})")
    print()
    for status in ("verified", "mismatch"):
        labeled = [r for r in rows if r["status"] == status and r["label"].strip()]
        correct = sum(1 for r in labeled if r["label"].strip().lower() in ("dung", "đúng", "1", "y"))
        if labeled:
            print(f"Precision '{status}': {correct}/{len(labeled)} = {correct / len(labeled):.1%}")
        else:
            print(f"Precision '{status}': chưa có nhãn")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=150)
    parser.add_argument("--seed", default="nearby-2026")
    parser.add_argument("--bbox", default=DEFAULT_BBOX)
    parser.add_argument("--force", action="store_true", help="xác minh lại cả POI đã có kết quả")
    parser.add_argument("--dry-run", action="store_true", help="không ghi database")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, help="chỉ tính độ chính xác từ CSV đã gán nhãn")
    args = parser.parse_args()

    if args.report:
        report(args.report)
        return 0

    pois = sample_pois(args.limit, args.seed, args.bbox, args.force)
    print(f"Mẫu: {len(pois)} POI — {dict(Counter(p['category'] for p in pois))}", flush=True)
    counts: Counter[str] = Counter()
    done: list[str] = []
    started = time.monotonic()
    for index, poi in enumerate(pois, 1):
        t0 = time.monotonic()
        result = storefront.verify(poi)
        if result is None:
            counts["loi"] += 1
            print(f"[{index}/{len(pois)}] {poi['name']}: KHÔNG chạy được (Mapillary/model) — bỏ qua", flush=True)
            continue
        counts[result["status"]] += 1
        if not args.dry_run:
            storefront.store(poi["poiId"], result)
            done.append(poi["poiId"])
        print(
            f"[{index}/{len(pois)}] {poi['category']:<11} {poi['name'][:40]:<40} → "
            f"{result['status']:<10} score={result.get('score')} "
            f"ảnh={len(result.get('readings') or [])} {time.monotonic() - t0:.0f}s "
            f"| {json.dumps(result.get('matchedText'), ensure_ascii=False)}",
            flush=True,
        )
    minutes = (time.monotonic() - started) / 60
    print(f"\nXong {len(pois)} POI trong {minutes:.1f} phút: {dict(counts)}")
    if done:
        export_csv(args.output)
        print(f"CSV để gán nhãn: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

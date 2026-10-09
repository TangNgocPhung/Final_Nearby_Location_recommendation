"""Bản ghi đè dữ liệu OSM sai (danh mục — 0031, tên — 0034) phải được áp lại
sau MỖI lượt import: DB dựng mới thì `_insert_poi` chèn lại đúng giá trị sai."""

import importlib.util
from pathlib import Path

from app import poi_import
from app.poi_features import normalize_text

MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "versions" / "0034_poi_name_overrides.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_0034", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ten_ghi_de_sua_hien_mua_thanh_hien_mau() -> None:
    """Đo 2026-10-10: OSM ghi "Trung Tâm Hiến Múa Nhân Đạo" nên BM25 không bao
    giờ khớp được chữ "máu"."""
    overrides = {(source, source_id): name for source, source_id, name, _, _ in _load_migration().OVERRIDES}

    assert overrides[("openstreetmap", "node/4981926121")] == "Trung Tâm Hiến Máu Nhân Đạo"


def test_normalized_name_trong_migration_khop_normalize_text() -> None:
    """Migration lưu sẵn ``normalized_name`` (không tính bằng SQL) — phải đúng
    bằng cách app chuẩn hoá, không thì so khớp tên/dedupe lệch với POI khác."""
    for _source, _source_id, name, normalized_name, _reason in _load_migration().OVERRIDES:
        assert normalized_name == normalize_text(name)


class _FakeCursor:
    def __init__(self, executed: list[str]) -> None:
        self.executed = executed
        self.rowcount = 1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.executed.append(sql)

    def fetchone(self):
        return {"id": "run-1"}


class _FakeConnection:
    def __init__(self, executed: list[str]) -> None:
        self.executed = executed

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return _FakeCursor(self.executed)


def test_import_ap_lai_ghi_de_ten_sau_ghi_de_danh_muc(monkeypatch) -> None:
    executed: list[str] = []
    monkeypatch.setattr(poi_import.psycopg, "connect", lambda *args, **kwargs: _FakeConnection(executed))

    stats = poi_import.import_osm_elements("postgresql://test", [], (10.7, 106.6, 10.8, 106.7), 10)

    assert poi_import._APPLY_CATEGORY_OVERRIDES in executed
    assert poi_import._APPLY_NAME_OVERRIDES in executed
    assert executed.index(poi_import._APPLY_NAME_OVERRIDES) > executed.index(poi_import._APPLY_CATEGORY_OVERRIDES)
    assert stats["nameOverrides"] == 1
    # `updated_at` mới làm `reindex --missing-only` thấy POI đã cũ và index lại tên.
    assert "updated_at = NOW()" in poi_import._APPLY_NAME_OVERRIDES

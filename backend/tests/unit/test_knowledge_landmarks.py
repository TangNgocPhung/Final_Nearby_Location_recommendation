"""Nội dung `poi_knowledge` của các migration 0028, 0040 và 0041 — khoá quy ước "có nguồn mới được vào".

Dữ liệu là literal trong file migration, nên kiểm được không cần database:
mỗi claim phải có URL nguồn và `verified`, loại nội dung phải là loại Săn địa
danh nhận, và không có hai dòng trỏ cùng một địa danh.
"""

import importlib.util
import re
from pathlib import Path

import pytest

from app import explore

_VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "versions"
_URL = re.compile(r"^https?://\S+$")


def _load(filename: str, label: str):
    spec = importlib.util.spec_from_file_location(label, _VERSIONS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# (module, số dòng tối thiểu)
_MODULES = {
    "0028": (_load("0028_poi_knowledge_landmarks.py", "migration_0028"), 30),
    "0040": (_load("0040_poi_knowledge_more_sg.py", "migration_0040"), 15),
    "0041": (_load("0041_poi_knowledge_more_sg_2.py", "migration_0041"), 8),
}
_ALL_ROWS = [(key, row) for key, (module, _) in _MODULES.items() for row in module.ROWS]


@pytest.mark.parametrize("key", _MODULES)
def test_revision_id_fits_alembic_version_column(key):
    # alembic_version.version_num là varchar(32): vượt thì migration chết ở bước ghi phiên bản.
    assert len(_MODULES[key][0].revision) <= 32


@pytest.mark.parametrize("key", _MODULES)
def test_rows_are_unique_and_nonempty(key):
    module, minimum = _MODULES[key]
    names = [row[0] for row in module.ROWS]
    assert len(module.ROWS) >= minimum
    assert len(set(names)) == len(names)


def test_migrations_do_not_overlap():
    # Hai migration không được gắn bài cho cùng một địa danh (tên + chỗ gần nhau).
    seen = [(row[0], row[2], row[3]) for _, row in _ALL_ROWS]
    assert len({name for name, _, _ in seen}) == len(seen)


@pytest.mark.parametrize("key,row", _ALL_ROWS, ids=[f"{key}:{row[0]}" for key, row in _ALL_ROWS])
def test_every_row_is_sourced(key, row):
    name, categories, lat, lon, content_type, intro, intro_source, _spec_, context, context_source, events, facts = row
    assert content_type in explore.HUNTABLE_CONTENT_TYPES
    assert categories and 10.3 <= lat <= 11.3 and 106.3 <= lon <= 107.1
    assert intro.strip()
    assert _URL.match(intro_source)
    # Có ngữ cảnh lịch sử thì phải có nguồn của chính nó.
    if context:
        assert context_source and _URL.match(context_source)
    for item in [*events, *facts]:
        assert item["description"].strip()
        assert item["verified"] is True
        assert _URL.match(item["source"]), f"{name}: nguồn không phải một URL: {item['source']!r}"

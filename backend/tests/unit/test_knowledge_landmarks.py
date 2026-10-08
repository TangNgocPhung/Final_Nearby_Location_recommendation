"""Nội dung `poi_knowledge` của migration 0028 — khoá quy ước "có nguồn mới được vào".

Dữ liệu là literal trong file migration, nên kiểm được không cần database:
mỗi claim phải có URL nguồn và `verified`, loại nội dung phải là loại Săn địa
danh nhận, và không có hai dòng trỏ cùng một địa danh.
"""

import importlib.util
import re
from pathlib import Path

import pytest

from app import explore

_PATH = Path(__file__).resolve().parents[2] / "migrations" / "versions" / "0028_poi_knowledge_landmarks.py"
_spec = importlib.util.spec_from_file_location("migration_0028", _PATH)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
ROWS = _module.ROWS

_URL = re.compile(r"^https?://\S+$")


def test_revision_id_fits_alembic_version_column():
    # alembic_version.version_num là varchar(32): vượt thì migration chết ở bước ghi phiên bản.
    assert len(_module.revision) <= 32


def test_rows_are_unique_and_nonempty():
    names = [row[0] for row in ROWS]
    assert len(ROWS) >= 30
    assert len(set(names)) == len(names)


@pytest.mark.parametrize("row", ROWS, ids=[row[0] for row in ROWS])
def test_every_row_is_sourced(row):
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

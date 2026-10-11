"""Săn địa danh đi theo TÀI KHOẢN: đăng nhập rồi thì đọc/ghi theo ``user:<id>``,
chưa đăng nhập thì theo phiên ẩn danh, và đăng nhập thì tiến độ của phiên được
chuyển sang. Phần SQL chuyển dữ liệu (`explore.transfer_owner`) cần PostGIS nên
không kiểm ở đây; test này khoá việc nối dây giữa endpoint và chủ sở hữu.
"""

from types import SimpleNamespace
from typing import Any

import pytest

from app import api, explore
from app.auth import AuthUser

SESSION = "11111111-1111-4111-8111-111111111111"
POI = "22222222-2222-4222-8222-222222222222"
USER = AuthUser(id="7", username="u", display_name=None, role="user", is_active=True)


def _request() -> Any:
    return SimpleNamespace(state=SimpleNamespace(session_id=SESSION))


def _sign_in(monkeypatch: pytest.MonkeyPatch, user: AuthUser | None) -> None:
    monkeypatch.setattr(api.auth, "optional_user", lambda _request: user)


def test_da_dang_nhap_thi_tien_do_doc_theo_tai_khoan(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str | None] = []
    monkeypatch.setattr(explore, "overview", lambda owner, lat, lng: seen.append(owner) or {})
    monkeypatch.setattr(explore, "story", lambda owner, poi: seen.append(owner) or {"locked": True})
    _sign_in(monkeypatch, USER)
    api.get_explore(_request(), 10.77, 106.7)
    api.get_explore_story(POI, _request())
    assert seen == [USER.owner_id, USER.owner_id]


def test_chua_dang_nhap_thi_van_theo_phien(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str | None] = []
    monkeypatch.setattr(explore, "overview", lambda owner, lat, lng: seen.append(owner) or {})
    _sign_in(monkeypatch, None)
    api.get_explore(_request(), 10.77, 106.7)
    assert seen == [SESSION]


def test_dang_nhap_chuyen_tien_do_phien_sang_tai_khoan(monkeypatch: pytest.MonkeyPatch) -> None:
    moved: list[tuple[str, str]] = []
    for module in (api.saved_places, api.reviews, api.checkins, api.exploration):
        monkeypatch.setattr(module, "transfer_owner", lambda *_args: 0)
    monkeypatch.setattr(explore, "transfer_owner", lambda old, new: moved.append((old, new)) or 0)
    api._adopt_session_data(_request(), USER, None)
    assert moved == [(SESSION, USER.owner_id)]

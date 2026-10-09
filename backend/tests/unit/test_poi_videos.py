"""Video YouTube của địa điểm — chuẩn hoá link và phân quyền route admin.

Đường đi qua database được giả lập bằng monkeypatch, giống `test_auth.py`:
điều cần khoá lại ở đây là link nào được nhận, link nào bị từ chối, và chỉ
admin mới gắn/gỡ được video.
"""

import pytest
from fastapi.testclient import TestClient

from app import auth, poi_videos
from app.api import app
from app.auth import AuthUser
from app.poi_videos import VideoError, parse_start, parse_youtube_url

VIDEO = "dQw4w9WgXcQ"
POI = "44444444-4444-4444-4444-444444444444"
ADMIN = AuthUser(id="11111111-1111-1111-1111-111111111111", username="boss",
                 display_name="Sếp", role="admin", is_active=True)
MEMBER = AuthUser(id="22222222-2222-2222-2222-222222222222", username="member",
                  display_name=None, role="user", is_active=True)


@pytest.mark.parametrize(
    ("url", "start"),
    [
        (VIDEO, 0),
        (f"https://www.youtube.com/watch?v={VIDEO}", 0),
        (f"https://youtube.com/watch?v={VIDEO}&si=abc&feature=share", 0),
        (f"https://m.youtube.com/watch?v={VIDEO}&t=90", 90),
        (f"https://music.youtube.com/watch?v={VIDEO}", 0),
        (f"youtube.com/watch?v={VIDEO}", 0),
        (f"https://youtu.be/{VIDEO}?t=1m30s", 90),
        (f"https://youtu.be/{VIDEO}?si=xyz", 0),
        (f"https://www.youtube.com/shorts/{VIDEO}", 0),
        (f"https://www.youtube.com/embed/{VIDEO}?start=42", 42),
        (f"https://www.youtube-nocookie.com/embed/{VIDEO}", 0),
        (f"https://www.youtube.com/live/{VIDEO}?feature=shared", 0),
        (f"https://www.youtube.com/watch?v={VIDEO}#t=2m", 120),
        (f"  https://youtu.be/{VIDEO}  ", 0),
    ],
)
def test_nhan_moi_dang_link_cua_mot_video(url: str, start: int) -> None:
    assert parse_youtube_url(url) == (VIDEO, start)


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "https://vimeo.com/123456",
        f"https://notyoutube.com/watch?v={VIDEO}",
        f"https://youtube.com.evil.example/watch?v={VIDEO}",
        "https://www.youtube.com/@HoChiMinhCity",
        "https://www.youtube.com/channel/UC1234567890",
        "https://www.youtube.com/playlist?list=PL1234567890",
        "https://www.youtube.com/watch?v=short",
        "https://youtu.be/",
        "dQw4w9WgXc",  # 10 ký tự — không phải id
    ],
)
def test_tu_choi_link_khong_phai_mot_video(url: str) -> None:
    with pytest.raises(VideoError):
        parse_youtube_url(url)


@pytest.mark.parametrize(
    ("raw", "seconds"),
    [(None, 0), ("", 0), ("90", 90), ("90s", 90), ("1m30s", 90), ("1h2m3s", 3723), ("2m", 120), ("rac", 0)],
)
def test_doc_moc_thoi_gian(raw: str | None, seconds: int) -> None:
    assert parse_start(raw) == seconds


def test_moc_thoi_gian_bi_chan_tren() -> None:
    assert parse_start("999h") == poi_videos.MAX_START_SECONDS


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    users = {user.id: user for user in (ADMIN, MEMBER)}
    monkeypatch.setattr(auth, "get_user", lambda user_id, database_url=None: users.get(user_id))
    return TestClient(app)


def _bearer(user: AuthUser) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth.issue_token(user.id)}"}


def test_chua_dang_nhap_hoac_user_thuong_khong_gan_duoc_video(client: TestClient) -> None:
    body = {"url": f"https://youtu.be/{VIDEO}"}
    assert client.post(f"/api/v1/admin/pois/{POI}/videos", json=body).status_code == 401
    response = client.post(f"/api/v1/admin/pois/{POI}/videos", json=body, headers=_bearer(MEMBER))
    assert response.status_code == 403
    assert client.delete(f"/api/v1/admin/videos/{POI}", headers=_bearer(MEMBER)).status_code == 403


def test_admin_gan_video(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_add(actor, poi_id, url, title=None, **_):
        calls.append((actor.id, poi_id, url, title))
        return {"id": "v1", "youtubeId": VIDEO, "title": title, "startSeconds": 0}

    monkeypatch.setattr(poi_videos, "add_video", fake_add)
    response = client.post(
        f"/api/v1/admin/pois/{POI}/videos",
        json={"url": f"https://youtu.be/{VIDEO}", "title": "Giới thiệu"},
        headers=_bearer(ADMIN),
    )
    assert response.status_code == 201
    assert response.json()["video"]["youtubeId"] == VIDEO
    assert calls == [(ADMIN.id, POI, f"https://youtu.be/{VIDEO}", "Giới thiệu")]


def test_link_hong_thi_400_khong_cham_database(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "_connect", lambda *a, **k: pytest.fail("không được mở kết nối"))
    response = client.post(
        f"/api/v1/admin/pois/{POI}/videos",
        json={"url": "https://vimeo.com/1"},
        headers=_bearer(ADMIN),
    )
    assert response.status_code == 400
    assert "YouTube" in response.json()["detail"]


def test_video_trung_thi_409(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_add(*_, **__):
        raise poi_videos.DuplicateVideoError("Địa điểm này đã có video đó rồi")

    monkeypatch.setattr(poi_videos, "add_video", fake_add)
    response = client.post(
        f"/api/v1/admin/pois/{POI}/videos", json={"url": VIDEO}, headers=_bearer(ADMIN)
    )
    assert response.status_code == 409


def test_khong_co_poi_thi_404(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(poi_videos, "add_video", lambda *_, **__: None)
    response = client.post(
        f"/api/v1/admin/pois/{POI}/videos", json={"url": VIDEO}, headers=_bearer(ADMIN)
    )
    assert response.status_code == 404


def test_id_khong_phai_uuid_thi_400(client: TestClient) -> None:
    headers = _bearer(ADMIN)
    assert client.post("/api/v1/admin/pois/abc/videos", json={"url": VIDEO}, headers=headers).status_code == 400
    assert client.delete("/api/v1/admin/videos/abc", headers=headers).status_code == 400


def test_xoa_video(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(poi_videos, "delete_video", lambda video_id, database_url=None: video_id == POI)
    headers = _bearer(ADMIN)
    assert client.delete(f"/api/v1/admin/videos/{POI}", headers=headers).json() == {"deleted": True}
    other = "55555555-5555-5555-5555-555555555555"
    assert client.delete(f"/api/v1/admin/videos/{other}", headers=headers).status_code == 404

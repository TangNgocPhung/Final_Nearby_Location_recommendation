"""Video YouTube gắn vào địa điểm — admin dán link, trang chi tiết nhúng player.

Không dùng YouTube Data API: tự tìm video theo tên địa điểm ra kết quả lạc đề
thường xuyên (một "Hội quán Hà Chương" khớp cả chục vlog ăn uống quanh đó), và
một video sai gắn vào trang địa điểm tệ hơn không có video. Người chọn video là
admin; file này chỉ lo hai việc:

**Chuẩn hoá link.** Cùng một video có rất nhiều dạng link — ``watch?v=``,
``youtu.be/``, ``shorts/``, ``embed/``, ``live/``, bản ``m.`` trên điện thoại,
kèm ``si=``/``feature=``... ``parse_youtube_url`` rút về đúng id 11 ký tự cộng
mốc thời gian ``t=``. Link không nhận ra thì TỪ CHỐI chứ không đoán: link kênh
hay playlist mà lưu thành "video" thì player hiện màn hình lỗi.

**Kiểm tra video nhúng được.** Gọi oEmbed công khai của YouTube (không cần
khoá) để lấy tiêu đề và loại sớm video đã xoá/riêng tư/tắt nhúng — những video
đó lưu vào thì trang chi tiết chỉ hiện khung đen. Mạng lỗi thì vẫn cho lưu: đó
là lỗi của ta, không phải của video.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import psycopg

from . import auth
from .auth import AuthUser

logger = logging.getLogger(__name__)

YOUTUBE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")
# Mốc thời gian: "90", "90s", "1m30s", "1h2m3s".
_TIME_PATTERN = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s?)?$")
_HOSTS = {"youtube.com", "youtu.be", "youtube-nocookie.com"}
# Các tiền tố đường dẫn mà phần ngay sau là id video.
_PATH_PREFIXES = ("shorts", "embed", "live", "v", "e")
MAX_START_SECONDS = 24 * 3600
OEMBED_TIMEOUT_SECONDS = 4.0


class VideoError(ValueError):
    """Lỗi nghiệp vụ có thông báo hiển thị được cho admin."""


class DuplicateVideoError(VideoError):
    pass


def parse_start(value: str | None) -> int:
    """``t=90`` / ``t=1m30s`` → số giây. Không đọc được thì 0 (phát từ đầu)
    — mốc thời gian hỏng không phải lý do để từ chối cả link."""
    if not value:
        return 0
    match = _TIME_PATTERN.match(value.strip().lower())
    if not match or not any(match.groups()):
        return 0
    hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return min(hours * 3600 + minutes * 60 + seconds, MAX_START_SECONDS)


def parse_youtube_url(url: str) -> tuple[str, int]:
    """Link YouTube (hoặc id trần) → ``(youtube_id, start_seconds)``."""
    text = (url or "").strip()
    if YOUTUBE_ID_PATTERN.match(text):
        return text, 0
    if not text:
        raise VideoError("Chưa dán link YouTube")
    if "://" not in text:
        text = f"https://{text}"
    try:
        parsed = urllib.parse.urlsplit(text)
    except ValueError as error:
        raise VideoError("Link không hợp lệ") from error

    host = (parsed.hostname or "").lower()
    for prefix in ("www.", "m.", "music."):
        if host.startswith(prefix):
            host = host[len(prefix):]
            break
    if host not in _HOSTS:
        raise VideoError("Chỉ nhận link YouTube (youtube.com hoặc youtu.be)")

    query = urllib.parse.parse_qs(parsed.query)
    fragment = urllib.parse.parse_qs(parsed.fragment)
    segments = [segment for segment in parsed.path.split("/") if segment]

    video_id: str | None = None
    if host == "youtu.be":
        video_id = segments[0] if segments else None
    elif segments[:1] == ["watch"]:
        video_id = (query.get("v") or [None])[0]
    elif len(segments) >= 2 and segments[0] in _PATH_PREFIXES:
        video_id = segments[1]

    if not video_id or not YOUTUBE_ID_PATTERN.match(video_id):
        raise VideoError("Không nhận ra video trong link — cần link của MỘT video, không phải kênh hay playlist")

    start_raw = (query.get("t") or query.get("start") or fragment.get("t") or [None])[0]
    return video_id, parse_start(start_raw)


def fetch_oembed(youtube_id: str) -> dict[str, Any] | None:
    """Tiêu đề + tên kênh từ oEmbed. Trả ``None`` khi KHÔNG kiểm được (mạng
    lỗi, YouTube trả lỗi lạ); ném ``VideoError`` khi YouTube nói rõ video
    không tồn tại hoặc không cho nhúng."""
    watch_url = f"https://www.youtube.com/watch?v={youtube_id}"
    endpoint = "https://www.youtube.com/oembed?" + urllib.parse.urlencode(
        {"url": watch_url, "format": "json"}
    )
    try:
        with urllib.request.urlopen(endpoint, timeout=OEMBED_TIMEOUT_SECONDS) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code in (400, 404):
            raise VideoError("Video không tồn tại hoặc đã bị xoá") from error
        if error.code in (401, 403):
            raise VideoError("Video riêng tư hoặc chủ kênh đã tắt nhúng — không phát được trong app") from error
        logger.warning("oEmbed YouTube trả %s cho %s", error.code, youtube_id)
        return None
    except (OSError, ValueError) as error:
        logger.warning("Không gọi được oEmbed YouTube cho %s: %s", youtube_id, error)
        return None
    return {"title": data.get("title"), "author": data.get("author_name")}


VIDEOS_QUERY = """
    SELECT id::text AS id, youtube_id, title, start_seconds
    FROM poi_videos
    WHERE poi_id = %(poi_id)s
    ORDER BY sort_order, created_at
"""


def video_json(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "youtubeId": row["youtube_id"],
        "title": row["title"],
        "startSeconds": row["start_seconds"],
    }


def add_video(
    actor: AuthUser,
    poi_id: str,
    url: str,
    title: str | None = None,
    *,
    check_online: bool = True,
    database_url: str | None = None,
) -> dict[str, Any] | None:
    """Gắn một video vào POI. ``None`` khi không có POI đó; ``VideoError`` khi
    link hỏng; ``DuplicateVideoError`` khi POI đã có đúng video này."""
    youtube_id, start_seconds = parse_youtube_url(url)
    clean_title = (title or "").strip()[:160] or None
    if check_online:
        info = fetch_oembed(youtube_id)
        if clean_title is None and info:
            clean_title = (info.get("title") or "").strip()[:160] or None

    with auth._connect(database_url) as connection:
        exists = connection.execute(
            "SELECT 1 FROM pois WHERE id = %(poi_id)s::uuid", {"poi_id": poi_id}
        ).fetchone()
        if exists is None:
            return None
        try:
            row = connection.execute(
                """
                INSERT INTO poi_videos (poi_id, youtube_id, title, start_seconds, sort_order, created_by)
                VALUES (
                    %(poi_id)s::uuid, %(youtube_id)s, %(title)s, %(start)s,
                    (SELECT COALESCE(MAX(sort_order) + 1, 0) FROM poi_videos WHERE poi_id = %(poi_id)s::uuid),
                    %(created_by)s
                )
                RETURNING id::text AS id, youtube_id, title, start_seconds
                """,
                {
                    "poi_id": poi_id,
                    "youtube_id": youtube_id,
                    "title": clean_title,
                    "start": start_seconds,
                    "created_by": actor.owner_id,
                },
            ).fetchone()
        except psycopg.errors.UniqueViolation as error:
            raise DuplicateVideoError("Địa điểm này đã có video đó rồi") from error
    return video_json(row)


def delete_video(video_id: str, database_url: str | None = None) -> bool:
    with auth._connect(database_url) as connection:
        row = connection.execute(
            "DELETE FROM poi_videos WHERE id = %(id)s::uuid RETURNING id", {"id": video_id}
        ).fetchone()
    return row is not None


def list_recent(limit: int = 50, offset: int = 0, database_url: str | None = None) -> dict[str, Any]:
    """Mọi video đã gắn, mới nhất trước — cho tab "Video" của trang quản trị."""
    with auth._connect(database_url) as connection:
        rows = connection.execute(
            """
            SELECT v.id::text AS id, v.youtube_id, v.title, v.start_seconds,
                   v.poi_id::text AS poi_id, p.name AS poi_name, v.created_at,
                   u.username, COUNT(*) OVER ()::int AS total
            FROM poi_videos v
            JOIN pois p ON p.id = v.poi_id
            LEFT JOIN app_users u ON v.created_by = 'user:' || u.id::text
            ORDER BY v.created_at DESC
            LIMIT %(limit)s OFFSET %(offset)s
            """,
            {"limit": limit, "offset": offset},
        ).fetchall()
    return {
        "videos": [
            {
                **video_json(row),
                "poiId": row["poi_id"],
                "poiName": row["poi_name"],
                "username": row["username"],
                "createdAt": row["created_at"].isoformat(),
            }
            for row in rows
        ],
        "total": rows[0]["total"] if rows else 0,
    }

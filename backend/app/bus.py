"""Xe buýt — tra tuyến (bấm "14" ra giờ chạy, giãn cách, giá vé, quãng đường,
lộ trình và các trạm theo thứ tự) và tìm trạm gần, như ứng dụng xe buýt
MultiGo/BusMap.

Nguồn: relation ``route=bus`` của OSM (PTv2), nhập bằng
``scripts/import_bus_routes.py``. Đo 2026-10-10 trong ``OSM_BBOX``: 369 lượt /
197 tuyến (TP.HCM 317 lượt, còn lại Đồng Nai, Bình Dương, Bến Tre), 6.726 trạm.
Gần như mọi lượt ghi giờ chạy (``opening_hours``), giãn cách (``interval``) và
giá vé (``charge``); chỉ 4 lượt ghi ``duration``.

Trung thực về dữ liệu:

- KHÔNG có vị trí xe theo thời gian thực. Chỉ biết giãn cách giữa hai chuyến
  ("6–12 phút/chuyến") — không bịa "xe tới trạm sau 3 phút".
- Thời gian một chuyến: thẻ ``duration`` nếu có, còn lại ƯỚC TÍNH từ độ dài lộ
  trình với vận tốc trung bình ``AVERAGE_SPEED_KMH`` — luôn trả kèm nguồn.
- Lộ trình ghép từ các đoạn đường theo thứ tự trong relation; relation đứt
  đoạn thì lộ trình thành nhiều khúc, không nối thẳng qua nhà dân.
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import psycopg
from psycopg.rows import dict_row

from . import charging
from .config import settings
from .fuel import _fold
from .geo_quality import haversine_meters
from .opening_hours import opening_status, parse_opening_hours
from .spatio_temporal import DEFAULT_TIMEZONE

# Vận tốc khai thác trung bình của xe buýt nội đô TP.HCM, tính cả dừng đón trả
# khách và đèn đỏ (thường 15–20 km/h). Chỉ dùng khi relation không ghi
# `duration` — kết quả luôn gắn nhãn "ước tính".
AVERAGE_SPEED_KMH = 18.0
# Hai đoạn đường liên tiếp trong relation cách nhau hơn mức này là relation bị
# đứt — tách khúc mới thay vì kẻ đường thẳng.
MAX_GAP_METERS = 40.0
# Way kế tiếp không chạm thì tìm trong chừng này way sau đó — xem assemble_path.
LOOKAHEAD_WAYS = 12
MIN_CHAIN_METERS = 60.0
# Khớp trạm vào lộ trình — xem stop_distances. Trạm cách lộ trình quá
# MATCH_RADIUS không khớp; bỏ một trạm tốn SKIP_PENALTY (lớn hơn mọi khoảng
# cách khớp hợp lệ); trạm sau được phép chiếu lùi tối đa PROJECTION_SLACK.
MATCH_RADIUS_METERS = 150.0
SKIP_PENALTY_METERS = 400.0
PROJECTION_SLACK_METERS = 25.0
CANDIDATE_SPACING_METERS = 50.0
# Trạm cách một khúc lộ trình trong chừng này mới được dùng để đoán chiều và
# thứ tự của khúc đó — xem orient_chains.
ORIENT_RADIUS_METERS = 120.0
DEFAULT_STOP_RADIUS_METERS = 800
MAX_ROUTED = 20
HCMC_NETWORK = "Xe buýt Thành phố Hồ Chí Minh"

Coord = tuple[float, float]  # (vĩ độ, kinh độ)

_JUNCTION_PREFIXES = ("nga ", "vong xoay", "bung binh", "cong truong", "nut giao", "giao lo")


# ---------------------------------------------------------------------------
# Phân tích thẻ OSM
# ---------------------------------------------------------------------------


def parse_minutes(raw: str | None) -> int | None:
    """``"00:45"`` → 45, ``"01:00"`` → 60, ``"40"`` → 40 (OSM cho phép cả hai)."""
    if not raw:
        return None
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", raw)
    if match:
        return int(match.group(1)) * 60 + int(match.group(2))
    match = re.fullmatch(r"\s*(\d+)\s*", raw)
    return int(match.group(1)) if match else None


def parse_interval(raw: str | None) -> dict[str, int] | None:
    """Giãn cách chuyến: ``"00:06-00:12"`` → 6–12 phút, ``"00:20"`` → 20 phút."""
    if not raw:
        return None
    parts = [parse_minutes(part) for part in raw.split("-")]
    values = [value for value in parts if value]
    if not values or len(values) != len(parts):
        return None
    return {"minMinutes": min(values), "maxMinutes": max(values)}


def parse_charge(raw: str | None) -> int | None:
    """Giá vé (đồng): ``"6000 VND"`` → 6000, ``"6.000 đ"`` → 6000."""
    if not raw:
        return None
    match = re.search(r"\d[\d.,]*", raw)
    if not match:
        return None
    digits = re.sub(r"[.,]", "", match.group(0))
    return int(digits) if digits else None


def service_status(raw: str | None, at: datetime | None = None) -> dict[str, Any]:
    """Giờ hoạt động của tuyến (chuyến đầu – chuyến cuối) và tuyến có đang
    chạy lúc ``at`` không. ``runningNow`` là ``None`` khi chuỗi giờ không phân
    tích được."""
    schedule = parse_opening_hours(raw)
    status = opening_status(schedule, DEFAULT_TIMEZONE, at)
    first_trip = last_trip = None
    periods = schedule.get("periods") or []
    if periods:
        weekday = (at or datetime.now(ZoneInfo(DEFAULT_TIMEZONE))).astimezone(ZoneInfo(DEFAULT_TIMEZONE)).weekday()
        today = [period for period in periods if weekday in period["days"]] or periods
        first_trip = min(period["opens"] for period in today)
        last_trip = max(period["closes"] for period in today)
    return {
        "raw": raw,
        "firstTrip": first_trip,
        "lastTrip": last_trip,
        "runningNow": status["openNow"],
        "endsInMinutes": status["closesInMinutes"],
        "startsInMinutes": status["opensInMinutes"],
    }


def _shift_clock(value: str | None, minutes: int) -> str | None:
    """``"20:00"`` + 14 phút → ``"20:14"``, qua nửa đêm thì quay về ``"00:…"``."""
    if value is None:
        return None
    total = (int(value[:2]) * 60 + int(value[3:5]) + minutes) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def stop_service(raw: str | None, minutes_from_start: int | None, at: datetime | None = None) -> dict[str, Any] | None:
    """Giờ xe qua MỘT trạm theo biểu đồ giờ — KHÔNG phải vị trí xe thật.

    ``opening_hours`` của tuyến là giờ xuất bến chuyến đầu – chuyến cuối ở bến
    đầu (khớp biểu đồ giờ của Trung tâm QLGTCC: "05:00 - 22:00" thì chuyến cuối
    xuất bến 22:00). Xe tới trạm muộn hơn ``minutes_from_start`` phút, nên
    chuyến qua trạm lúc t là chuyến xuất bến lúc t − offset: trạng thái tại
    trạm chính là trạng thái tuyến ở bến đầu lùi offset phút. ``None`` khi
    không biết trạm cách bến đầu bao xa."""
    if minutes_from_start is None:
        return None
    now = at or datetime.now(ZoneInfo(DEFAULT_TIMEZONE))
    status = service_status(raw, now - timedelta(minutes=minutes_from_start))
    return {
        **status,
        "firstTrip": _shift_clock(status["firstTrip"], minutes_from_start),
        "lastTrip": _shift_clock(status["lastTrip"], minutes_from_start),
    }


def trip_minutes(duration_raw: str | None, length_meters: float | None) -> tuple[int | None, str]:
    """``(số phút một chuyến, nguồn)`` — nguồn ``osm`` (thẻ ``duration``),
    ``estimate`` (độ dài / vận tốc trung bình) hoặc ``unknown``."""
    declared = parse_minutes(duration_raw)
    if declared:
        return declared, "osm"
    if length_meters:
        return round(length_meters / 1000 / AVERAGE_SPEED_KMH * 60), "estimate"
    return None, "unknown"


def minutes_to_stop(trip: int | None, length_meters: float | None, distance_meters: float | None) -> int | None:
    """Phút từ bến đầu tới trạm — chia đều thời gian chuyến theo quãng đường."""
    if not trip or not length_meters or distance_meters is None:
        return None
    return round(trip * distance_meters / length_meters)


def street_sequence(names: list[str | None]) -> list[str]:
    """Tên đường theo thứ tự đi qua, gộp các đoạn liên tiếp cùng tên. Nút giao
    kẹp giữa hai đoạn cùng một đường ("Lý Thái Tổ → Ngã bảy Lý Thái Tổ → Lý
    Thái Tổ") bị bỏ — xe vẫn đi thẳng trên Lý Thái Tổ."""
    result: list[str] = []
    for raw in names:
        name = (raw or "").strip()
        if not name or (result and result[-1] == name):
            continue
        if len(result) >= 2 and result[-2] == name and _is_junction(result[-1]):
            result.pop()
            continue
        result.append(name)
    return result


def _is_junction(name: str) -> bool:
    folded = " ".join(_fold(word) for word in name.split())
    return folded.startswith(_JUNCTION_PREFIXES)


def natural_ref_key(ref: str) -> tuple[int, str]:
    """"8" < "14" < "60-1" < "D2": số tuyến sắp theo số, không theo chữ."""
    match = re.match(r"\d+", ref)
    return (int(match.group(0)) if match else 10_000, ref)


# ---------------------------------------------------------------------------
# Hình học lộ trình
# ---------------------------------------------------------------------------


def _gap(a: Coord, b: Coord) -> float:
    return haversine_meters(a[0], a[1], b[0], b[1])


def _loop_piece(loop: list[Coord], entry: Coord, following: list[Coord] | None) -> list[Coord] | None:
    """Phần vòng xuyến (way khép kín) xe thật sự đi: từ điểm vào tới điểm ra
    (đầu mút của đoạn kế tiếp), theo chiều vẽ của way — vòng xuyến OSM là một
    chiều theo chiều vẽ."""
    ring = loop[:-1]
    entry_index = min(range(len(ring)), key=lambda index: _gap(ring[index], entry))
    if _gap(ring[entry_index], entry) > MAX_GAP_METERS or not following:
        return None
    ends = (following[0], following[-1])
    exit_index = min(range(len(ring)), key=lambda index: min(_gap(ring[index], end) for end in ends))
    steps = (exit_index - entry_index) % len(ring)
    return [ring[(entry_index + step) % len(ring)] for step in range(steps + 1)]


def _connect(
    current: list[Coord],
    segment: list[Coord],
    fresh: bool,
    following: list[Coord] | None,
    max_gap_meters: float,
) -> tuple[bool, list[Coord]] | None:
    """Cách nối ``segment`` vào cuối ``current``: ``(đảo current?, các điểm nối
    thêm theo chiều xe chạy)``, hoặc ``None`` nếu không chạm nhau."""
    ends = [(False, current[-1])] + ([(True, current[0])] if fresh else [])
    if segment[0] == segment[-1] and len(segment) > 3:
        for reverse, end in ends:
            piece = _loop_piece(segment, end, following)
            if piece is not None:
                return reverse, piece
    options = [
        (_gap(end, point), reverse, segment if point == segment[0] else segment[::-1])
        for reverse, end in ends
        for point in (segment[0], segment[-1])
    ]
    gap, reverse, piece = min(options, key=lambda option: option[0])
    return (reverse, piece) if gap <= max_gap_meters else None


def _join_touching(chains: list[list[Coord]], max_gap_meters: float) -> list[list[Coord]]:
    """Nối khúc có ĐIỂM CUỐI chạm ĐIỂM ĐẦU của khúc khác, bất kể thứ tự liệt kê.
    Tuyến 52 lượt về (đo 2026-10-10): vòng trong khuôn viên ĐHQG — đoạn ĐẦU của
    lượt — bị liệt kê ở cuối relation, quá tầm ``LOOKAHEAD_WAYS``. Chỉ nối cuối
    → đầu để giữ nguyên chiều của cả hai khúc."""
    chains = [list(chain) for chain in chains]
    joined = True
    while joined:
        joined = False
        for i, head in enumerate(chains):
            for j, tail in enumerate(chains):
                if i != j and _gap(head[-1], tail[0]) <= max_gap_meters:
                    head.extend(tail[1:] if tail[0] == head[-1] else tail)
                    del chains[j]
                    joined = True
                    break
            if joined:
                break
    return chains


def assemble_path(
    segments: list[list[Coord]],
    max_gap_meters: float = MAX_GAP_METERS,
    lookahead: int = LOOKAHEAD_WAYS,
) -> list[list[Coord]]:
    """Ghép các way của relation thành các khúc liền mạch theo chiều xe chạy.

    Thứ tự way trong relation là thứ tự xe đi, nhưng mỗi way có thể vẽ ngược
    chiều, và người nhập OSM hay đặt lệch vài way (tuyến 14 lượt đi: một đoạn
    Võ Văn Tần nằm sau Cao Thắng — nối cứng theo thứ tự thì hở 1 km). Nên khi
    way kế tiếp không chạm, lấy way GẦN NHẤT trong ``lookahead`` way sau đó mà
    chạm được; không có mới tách khúc mới. Trả nhiều khúc khi relation đứt thật.
    """
    pending = [list(segment) for segment in segments if len(segment) >= 2]
    chains: list[list[Coord]] = []
    current: list[Coord] = []
    # Khúc mới chỉ có một way thì chưa biết chiều — way nối vào quyết định.
    fresh = False
    while pending:
        if not current:
            current, fresh = pending.pop(0), True
            continue
        for offset, segment in enumerate(pending[:lookahead]):
            following = pending[offset + 1] if offset + 1 < len(pending) else None
            joined = _connect(current, segment, fresh, following, max_gap_meters)
            if joined is not None:
                reverse, piece = joined
                if reverse:
                    current.reverse()
                current.extend(piece[1:] if piece[0] == current[-1] else piece)
                fresh = False
                del pending[offset]
                break
        else:
            chains.append(current)
            current = []
    if current:
        chains.append(current)
    chains = _join_touching(chains, max_gap_meters)
    # Mẩu way lạc (vài mét, thường là way nối bị liệt kê thừa) không phải một
    # khúc lộ trình — bỏ, trừ khi cả tuyến chỉ có chừng đó.
    return [chain for chain in chains if path_length([chain]) >= MIN_CHAIN_METERS] or chains


def path_length(chains: list[list[Coord]]) -> float:
    """Độ dài lộ trình (mét) — chỉ cộng trong từng khúc, không cộng chỗ đứt."""
    return sum(_gap(a, b) for chain in chains for a, b in zip(chain, chain[1:]))


class _Track:
    """Lộ trình (một hay nhiều khúc) trên mặt phẳng địa phương tính bằng mét,
    để chiếu trạm lên. Quãng đường dọc tuyến không tính chỗ đứt giữa hai khúc."""

    def __init__(self, chains: list[list[Coord]]) -> None:
        starts, ends, lengths = [], [], []
        for chain in chains:
            for a, b in zip(chain, chain[1:]):
                starts.append(a)
                ends.append(b)
                lengths.append(_gap(a, b))
        self.size = len(starts)
        lat0 = math.radians(chains[0][0][0]) if self.size else 0.0
        self.scale = np.array([111_320 * math.cos(lat0), 110_540])  # mét / độ (kinh, vĩ)
        if not self.size:
            return
        # Toạ độ (x = kinh, y = vĩ) theo mét.
        self.a = np.array(starts)[:, ::-1] * self.scale
        self.d = np.array(ends)[:, ::-1] * self.scale - self.a
        self.length2 = np.maximum((self.d**2).sum(axis=1), 1e-9)
        self.lengths = np.array(lengths)
        self.offsets = np.concatenate(([0.0], np.cumsum(self.lengths)[:-1]))
        self.total = float(self.lengths.sum())

    def project(self, point: Coord) -> tuple[np.ndarray, np.ndarray]:
        """Khoảng cách từ ``point`` tới TỪNG đoạn, và quãng đường từ đầu tuyến
        tới hình chiếu của nó trên đoạn đó."""
        p = np.array(point[::-1]) * self.scale
        t = np.clip(((p - self.a) * self.d).sum(axis=1) / self.length2, 0.0, 1.0)
        nearest = self.a + self.d * t[:, None]
        return np.hypot(*(p - nearest).T), self.offsets + t * self.lengths


def orient_chains(chains: list[list[Coord]], stops: list[Coord]) -> list[list[Coord]]:
    """Sắp và quay chiều các khúc theo THỨ TỰ TRẠM — tín hiệu đáng tin hơn thứ
    tự way. Đo 2026-10-10: tuyến 52 lượt về có way liệt kê từ Bến Thành ngược
    lên Đại học Quốc gia trong khi trạm đi chiều ngược lại; chiếu trạm "chỉ tiến
    về phía trước" lên lộ trình ngược chiều thì mọi trạm dồn về cuối tuyến."""
    if not stops:
        return chains
    keyed = []
    previous_key = -1.0
    for order, chain in enumerate(chains):
        track = _Track([chain])
        # (thứ tự trạm, vị trí trên khúc) của những trạm nằm sát khúc này.
        pairs = []
        for sequence, stop in enumerate(stops):
            if not track.size:
                break
            distances, alongs = track.project(stop)
            nearest = int(distances.argmin())
            if distances[nearest] <= ORIENT_RADIUS_METERS:
                pairs.append((sequence, float(alongs[nearest])))
        steps = list(zip(pairs, pairs[1:]))
        forward = sum(1 for (_, a), (_, b) in steps if b > a)
        backward = sum(1 for (_, a), (_, b) in steps if b < a)
        if backward > forward:
            chain = chain[::-1]
        # Khúc không có trạm nào giữ chỗ ngay sau khúc đứng trước nó.
        key = sum(sequence for sequence, _ in pairs) / len(pairs) if pairs else previous_key + 0.001
        previous_key = key
        keyed.append((key, order, chain))
    return [chain for _, _, chain in sorted(keyed)]


def _stop_candidates(track: _Track, stop: Coord) -> list[tuple[float, float]]:
    """Mỗi lần lộ trình đi ngang trạm cho một ứng viên ``(khoảng cách, quãng
    đường)``: cực tiểu địa phương của khoảng cách dọc tuyến, trong
    ``MATCH_RADIUS_METERS``. Không gộp theo "dải đoạn nằm trong bán kính" — đi
    rồi quay đầu trên cùng một đường thì cả hai lượt đều trong bán kính."""
    distances, alongs = track.project(stop)
    left = np.concatenate(([np.inf], distances[:-1]))
    right = np.concatenate((distances[1:], [np.inf]))
    minima = np.nonzero((distances <= MATCH_RADIUS_METERS) & (distances <= left) & (distances <= right))[0]
    candidates: list[tuple[float, float]] = []
    for index in minima:
        distance, along = float(distances[index]), float(alongs[index])
        # Đường vẽ zíc zắc cho vài cực tiểu sát nhau — cùng một lần đi ngang.
        if candidates and along - candidates[-1][1] < CANDIDATE_SPACING_METERS:
            if distance < candidates[-1][0]:
                candidates[-1] = (distance, along)
            continue
        candidates.append((distance, along))
    return candidates


def stop_distances(chains: list[list[Coord]], stops: list[Coord]) -> list[float | None]:
    """Quãng đường (mét) từ đầu tuyến tới hình chiếu của từng trạm lên lộ trình.

    Trạm đặt ven đường và lộ trình có thể đi ngang một chỗ nhiều lần (lượt đi,
    quay đầu, vòng trong khuôn viên bến), nên mỗi trạm có vài vị trí ứng viên.
    Chọn bằng quy hoạch động bộ vị trí KHÔNG GIẢM theo thứ tự trạm mà tổng
    khoảng cách nhỏ nhất; trạm không xếp vào được (OSM liệt kê sai chỗ, hoặc
    nằm xa lộ trình) bị bỏ với phạt ``SKIP_PENALTY_METERS`` và trả ``None`` —
    thay vì kéo cả dãy trạm sau nó dồn về cuối tuyến.
    """
    return _match_stops(_Track(chains), stops)[0]


def order_stops(chains: list[list[Coord]], stops: list[Coord]) -> list[tuple[int, float]]:
    """``(chỉ số trạm trong relation, quãng đường từ đầu tuyến)`` theo thứ tự
    xe THẬT SỰ đi qua.

    Trạm khớp đúng thứ tự (``stop_distances``) làm xương sống; trạm liệt kê
    sai chỗ được chèn vào đúng vị trí của nó trên lộ trình. Đo 2026-10-10:
    tuyến 60-3 lượt về liệt kê 30 trạm đúng thứ tự rồi NỐI THÊM 29 trạm dọc
    đường ở cuối danh sách; tuyến 01 có trạm Hàm Nghi nằm sau cả bến cuối. Bỏ
    chúng là mất trạm thật. Chỉ bỏ trạm cách lộ trình quá ``MATCH_RADIUS_METERS``.
    """
    distances, options = _match_stops(_Track(chains), stops)
    placed = []
    for index, distance in enumerate(distances):
        if distance is None and options[index]:
            distance = min(options[index])[1]
        if distance is not None:
            placed.append((distance, index))
    return [(index, distance) for distance, index in sorted(placed)]


def _match_stops(
    track: _Track, stops: list[Coord]
) -> tuple[list[float | None], list[list[tuple[float, float]]]]:
    if not track.size or not stops:
        return [None] * len(stops), [[] for _ in stops]
    options = [_stop_candidates(track, stop) for stop in stops]
    # cost[i][c]: chi phí nhỏ nhất của các trạm 0..i khi trạm i khớp ứng viên c.
    cost: list[list[float]] = []
    back: list[list[tuple[int, int] | None]] = []
    for i, candidates in enumerate(options):
        cost.append([])
        back.append([])
        for distance, along in candidates:
            best, link = SKIP_PENALTY_METERS * i, None  # bỏ mọi trạm trước nó
            for j in range(i):
                for c, (_, previous_along) in enumerate(options[j]):
                    if previous_along <= along + PROJECTION_SLACK_METERS:
                        value = cost[j][c] + SKIP_PENALTY_METERS * (i - j - 1)
                        if value < best:
                            best, link = value, (j, c)
            cost[i].append(best + distance)
            back[i].append(link)
    best_total, cursor = SKIP_PENALTY_METERS * len(stops), None
    for i, row in enumerate(cost):
        for c, value in enumerate(row):
            total = value + SKIP_PENALTY_METERS * (len(stops) - 1 - i)
            if total < best_total:
                best_total, cursor = total, (i, c)

    result: list[float | None] = [None] * len(stops)
    while cursor is not None:
        i, c = cursor
        result[i] = options[i][c][1]
        cursor = back[i][c]
    # Hai trạm sát nhau có thể chiếu lùi vài mét — xe không chạy lùi.
    previous = 0.0
    for i, value in enumerate(result):
        if value is not None:
            previous = result[i] = max(value, previous)
    return result, options


# ---------------------------------------------------------------------------
# Nhập từ Overpass
# ---------------------------------------------------------------------------

STOP_ROLES = ("platform", "platform_entry_only", "platform_exit_only", "stop", "stop_entry_only", "stop_exit_only")


def build_overpass_query(bbox: tuple[float, float, float, float]) -> str:
    """Lượt tuyến kèm hình học các way (``out geom``), rồi thẻ của trạm và tên
    của từng way. ~28 MB cho TP.HCM."""
    bounds = ",".join(str(value) for value in bbox)
    return (
        f'[out:json][timeout:300];relation["route"="bus"]({bounds})->.r;'
        ".r out geom;node(r.r);out body;way(r.r);out tags;"
    )


def _is_stop_member(member: dict[str, Any], node: dict[str, Any] | None) -> bool:
    role = (member.get("role") or "").strip()
    if role in STOP_ROLES:
        return True
    tags = (node or {}).get("tags") or {}
    return role == "" and (tags.get("highway") == "bus_stop" or tags.get("public_transport") == "platform")


def normalize_route(
    relation: dict[str, Any],
    nodes: dict[int, dict[str, Any]],
    ways: dict[int, dict[str, Any]],
) -> dict[str, Any] | None:
    tags = relation.get("tags") or {}
    ref = (tags.get("ref") or "").strip()
    if tags.get("route") != "bus" or not ref:
        return None
    members = relation.get("members") or []
    way_members = [
        member
        for member in members
        if member.get("type") == "way" and (member.get("role") or "") in ("", "forward", "backward")
    ]
    segments = [
        [(point["lat"], point["lon"]) for point in member.get("geometry") or [] if point]
        for member in way_members
    ]
    stops = []
    for member in members:
        if member.get("type") != "node":
            continue
        node = nodes.get(member["ref"])
        if node is None or "lat" not in node or not _is_stop_member(member, node):
            continue
        stops.append({"id": node["id"], "role": (member.get("role") or "platform").strip() or "platform",
                      "latitude": node["lat"], "longitude": node["lon"]})
    stop_points = [(stop["latitude"], stop["longitude"]) for stop in stops]
    chains = orient_chains(assemble_path(segments), stop_points)
    if chains:
        ordered = []
        for index, distance in order_stops(chains, stop_points):
            # Cùng một trạm liệt kê hai lần thì sau khi xếp lại nằm kề nhau.
            if ordered and ordered[-1]["id"] == stops[index]["id"]:
                continue
            ordered.append({**stops[index], "distanceMeters": round(distance, 1)})
        stops = ordered
    else:
        stops = [{**stop, "distanceMeters": None} for stop in stops]
    return {
        "id": relation["id"],
        "ref": ref,
        "name": (tags.get("name") or f"Tuyến {ref}").strip(),
        "origin": tags.get("from"),
        "destination": tags.get("to"),
        "via": tags.get("via"),
        "network": tags.get("network"),
        "operator": tags.get("operator"),
        "openingHours": tags.get("opening_hours"),
        "interval": tags.get("interval"),
        "charge": tags.get("charge"),
        "duration": tags.get("duration"),
        "colour": tags.get("colour"),
        "roundtrip": tags.get("roundtrip") == "yes",
        "chains": chains,
        "lengthMeters": round(path_length(chains), 1) if chains else None,
        "streets": street_sequence(
            [((ways.get(member["ref"]) or {}).get("tags") or {}).get("name") for member in way_members]
        ),
        "stops": stops,
    }


def _yes_no(value: Any) -> bool | None:
    if value == "yes":
        return True
    if value == "no":
        return False
    return None


def normalize_stop(node: dict[str, Any]) -> dict[str, Any]:
    tags = node.get("tags") or {}
    return {
        "id": node["id"],
        "name": (tags.get("name") or "Trạm không tên").strip(),
        "latitude": node["lat"],
        "longitude": node["lon"],
        "shelter": _yes_no(tags.get("shelter")),
        "bench": _yes_no(tags.get("bench")),
        "tags": tags,
    }


def _multilinestring_wkt(chains: list[list[Coord]]) -> str | None:
    parts = [chain for chain in chains if len(chain) >= 2]
    if not parts:
        return None
    body = ",".join("(" + ",".join(f"{lon} {lat}" for lat, lon in chain) + ")" for chain in parts)
    return f"MULTILINESTRING({body})"


def import_bus_elements(database_url: str, elements: list[dict[str, Any]]) -> dict[str, Any]:
    """Thay TOÀN BỘ dữ liệu xe buýt bằng ảnh chụp Overpass mới — tuyến bị bỏ
    hay đổi lộ trình thì dữ liệu cũ không được sót lại."""
    nodes = {element["id"]: element for element in elements if element.get("type") == "node"}
    ways = {element["id"]: element for element in elements if element.get("type") == "way"}
    routes = [
        route
        for route in (
            normalize_route(element, nodes, ways) for element in elements if element.get("type") == "relation"
        )
        if route is not None
    ]
    used_stop_ids = {stop["id"] for route in routes for stop in route["stops"]}
    stops = [normalize_stop(nodes[stop_id]) for stop_id in used_stop_ids]

    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM bus_route_stops")
            cursor.execute("DELETE FROM bus_routes")
            cursor.execute("DELETE FROM bus_stops")
            cursor.executemany(
                """
                INSERT INTO bus_stops (id, name, location, shelter, bench, tags)
                VALUES (%s, %s, ST_SetSRID(ST_Point(%s, %s), 4326)::geography, %s, %s, %s::jsonb)
                """,
                [
                    (stop["id"], stop["name"], stop["longitude"], stop["latitude"], stop["shelter"],
                     stop["bench"], json.dumps(stop["tags"], ensure_ascii=False))
                    for stop in stops
                ],
            )
            cursor.executemany(
                """
                INSERT INTO bus_routes (id, ref, name, origin, destination, via, network, operator,
                    opening_hours, interval, charge, duration, colour, roundtrip, path, length_meters, streets)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    ST_GeogFromText(%s), %s, %s::jsonb)
                """,
                [
                    (route["id"], route["ref"], route["name"], route["origin"], route["destination"], route["via"],
                     route["network"], route["operator"], route["openingHours"], route["interval"], route["charge"],
                     route["duration"], route["colour"], route["roundtrip"], _multilinestring_wkt(route["chains"]),
                     route["lengthMeters"], json.dumps(route["streets"], ensure_ascii=False))
                    for route in routes
                ],
            )
            cursor.executemany(
                """
                INSERT INTO bus_route_stops (route_id, seq, stop_id, role, distance_meters)
                VALUES (%s, %s, %s, %s, %s)
                """,
                [
                    (route["id"], seq, stop["id"], stop["role"], stop["distanceMeters"])
                    for route in routes
                    for seq, stop in enumerate(route["stops"])
                ],
            )
        connection.commit()
    return {
        "routes": len(routes),
        "lines": len({(route["network"], route["ref"]) for route in routes}),
        "stops": len(stops),
        "brokenRoutes": sum(1 for route in routes if len(route["chains"]) > 1),
        "routesWithoutPath": sum(1 for route in routes if not route["chains"]),
    }


# ---------------------------------------------------------------------------
# Đọc
# ---------------------------------------------------------------------------


def _line_label(route: dict[str, Any]) -> str:
    if route.get("origin") and route.get("destination"):
        return f"{route['origin']} – {route['destination']}"
    return route["name"]


def build_line(directions: list[dict[str, Any]], at: datetime | None = None) -> dict[str, Any]:
    """Gộp các lượt cùng ``network`` + ``ref`` thành MỘT tuyến để liệt kê."""
    directions = sorted(directions, key=lambda route: route["id"])
    main = directions[0]
    return {
        "key": f"{main['network'] or ''}|{main['ref']}",
        "ref": main["ref"],
        "name": _line_label(main),
        "network": main["network"],
        "operator": main["operator"],
        "colour": main["colour"],
        "charge": parse_charge(main["charge"]),
        "interval": parse_interval(main["interval"]),
        "hours": service_status(main["opening_hours"], at),
        "roundtrip": main["roundtrip"],
        "directions": [
            {"id": str(route["id"]), "origin": route["origin"], "destination": route["destination"]}
            for route in directions
        ],
    }


def _matches(query: str, line_routes: list[dict[str, Any]]) -> int | None:
    """Hạng khớp (nhỏ = tốt) hoặc ``None``: 0 đúng số tuyến ("1" khớp "01"),
    1 số tuyến bắt đầu bằng câu gõ, 2 khớp tên / bến / đường đi qua."""
    folded = _fold(query)
    if not folded:
        return 3
    ref = _fold(line_routes[0]["ref"])
    if ref == folded or ref.lstrip("0") == folded.lstrip("0"):
        return 0
    if ref.startswith(folded):
        return 1
    words = [_fold(word) for word in query.split() if _fold(word)]
    for route in line_routes:
        haystack = _fold(
            " ".join(
                str(route.get(key) or "") for key in ("name", "origin", "destination", "via", "operator")
            )
            + " "
            + " ".join(route.get("streets") or [])
        )
        if all(word in haystack for word in words):
            return 2
    return None


_LINES_QUERY = """
SELECT id, ref, name, origin, destination, via, network, operator, opening_hours, interval,
       charge, colour, roundtrip, streets
FROM bus_routes
"""


def search_lines(query: str = "", limit: int = 60) -> dict[str, Any]:
    with psycopg.connect(settings.database_url, row_factory=dict_row) as connection:
        rows = connection.execute(_LINES_QUERY).fetchall()
    grouped: dict[tuple[str | None, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["network"], row["ref"])].append(row)
    ranked = []
    for (network, ref), line_routes in grouped.items():
        rank = _matches(query.strip(), line_routes)
        if rank is not None:
            ranked.append(((rank, network != HCMC_NETWORK, natural_ref_key(ref), network or ""), line_routes))
    ranked.sort(key=lambda item: item[0])
    return {
        "query": query,
        "total": len(ranked),
        "lines": [build_line(line_routes) for _, line_routes in ranked[:limit]],
    }


_ROUTE_QUERY = """
SELECT id, ref, name, origin, destination, via, network, operator, opening_hours, interval, charge,
       duration, colour, roundtrip, length_meters, streets,
       ST_AsGeoJSON(path::geometry, 6)::jsonb AS path
FROM bus_routes
WHERE ref = (SELECT ref FROM bus_routes WHERE id = %(id)s)
  AND network IS NOT DISTINCT FROM (SELECT network FROM bus_routes WHERE id = %(id)s)
ORDER BY id
"""

_ROUTE_STOPS_QUERY = """
SELECT rs.route_id, rs.seq, rs.role, rs.distance_meters, s.id::text AS id, s.name, s.shelter,
       ST_Y(s.location::geometry) AS latitude, ST_X(s.location::geometry) AS longitude
FROM bus_route_stops rs JOIN bus_stops s ON s.id = rs.stop_id
WHERE rs.route_id = ANY(%(ids)s)
ORDER BY rs.route_id, rs.seq
"""


def _route_stop(route: dict[str, Any], stop: dict[str, Any], trip: int | None, at: datetime | None) -> dict[str, Any]:
    minutes = minutes_to_stop(trip, route["length_meters"], stop["distance_meters"])
    return {
        "id": stop["id"],
        "name": stop["name"],
        "latitude": stop["latitude"],
        "longitude": stop["longitude"],
        "shelter": stop["shelter"],
        # Bến đầu chỉ lên / bến cuối chỉ xuống.
        "boardingOnly": stop["role"].endswith("entry_only"),
        "alightingOnly": stop["role"].endswith("exit_only"),
        "distanceMeters": None if stop["distance_meters"] is None else round(stop["distance_meters"]),
        "minutesFromStart": minutes,
        "service": stop_service(route["opening_hours"], minutes, at),
    }


def build_direction(route: dict[str, Any], stops: list[dict[str, Any]], at: datetime | None = None) -> dict[str, Any]:
    minutes, source = trip_minutes(route["duration"], route["length_meters"])
    length = route["length_meters"]
    return {
        "id": str(route["id"]),
        "name": route["name"],
        "origin": route["origin"],
        "destination": route["destination"],
        "via": route["via"],
        "lengthMeters": round(length) if length else None,
        "tripMinutes": minutes,
        "tripMinutesSource": source,
        "streets": route["streets"] or [],
        "path": route["path"],
        "stops": [_route_stop(route, stop, minutes, at) for stop in stops],
    }


def route_detail(route_id: int, at: datetime | None = None) -> dict[str, Any] | None:
    """Chi tiết MỘT tuyến (mọi lượt cùng số tuyến + mạng) từ id một lượt bất kỳ."""
    with psycopg.connect(settings.database_url, row_factory=dict_row) as connection:
        routes = connection.execute(_ROUTE_QUERY, {"id": route_id}).fetchall()
        if not routes:
            return None
        stop_rows = connection.execute(_ROUTE_STOPS_QUERY, {"ids": [route["id"] for route in routes]}).fetchall()
    stops_by_route: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in stop_rows:
        stops_by_route[row["route_id"]].append(row)
    line = build_line(routes, at)
    selected = next(route for route in routes if route["id"] == route_id)
    minutes, _ = trip_minutes(selected["duration"], selected["length_meters"])
    return {
        **line,
        "operator": selected["operator"],
        "selectedId": str(route_id),
        "averageSpeedKmh": AVERAGE_SPEED_KMH,
        "directions": [build_direction(route, stops_by_route[route["id"]], at) for route in routes],
        "tripMinutes": minutes,
    }


_NEARBY_STOPS_QUERY = """
SELECT s.id::text AS id, s.name, s.shelter, s.bench,
       ST_Y(s.location::geometry) AS latitude, ST_X(s.location::geometry) AS longitude,
       ST_Distance(s.location, ST_SetSRID(ST_Point(%(lng)s, %(lat)s), 4326)::geography) AS "distanceMeters"
FROM bus_stops s
WHERE ST_DWithin(s.location, ST_SetSRID(ST_Point(%(lng)s, %(lat)s), 4326)::geography, %(radius)s)
ORDER BY "distanceMeters"
LIMIT 80
"""

_NAMED_STOPS_QUERY = """
SELECT s.id::text AS id, s.name, s.shelter, s.bench,
       ST_Y(s.location::geometry) AS latitude, ST_X(s.location::geometry) AS longitude,
       ST_Distance(s.location, ST_SetSRID(ST_Point(%(lng)s, %(lat)s), 4326)::geography) AS "distanceMeters"
FROM bus_stops s
ORDER BY "distanceMeters"
"""

# Tuyến vòng đi qua một trạm hai lần — lấy lần đầu (``seq`` nhỏ nhất).
_STOP_ROUTES_QUERY = """
SELECT DISTINCT ON (rs.stop_id, r.id)
       rs.stop_id::text AS stop_id, r.id::text AS "routeId", r.ref, r.destination, r.colour, r.network,
       r.opening_hours, r.interval, r.duration, r.length_meters, rs.distance_meters
FROM bus_route_stops rs JOIN bus_routes r ON r.id = rs.route_id
WHERE rs.stop_id = ANY(%(ids)s)
ORDER BY rs.stop_id, r.id, rs.seq
"""


def _stop_route(route: dict[str, Any], at: datetime | None) -> dict[str, Any]:
    trip, _ = trip_minutes(route["duration"], route["length_meters"])
    minutes = minutes_to_stop(trip, route["length_meters"], route["distance_meters"])
    return {
        **{key: route[key] for key in ("routeId", "ref", "destination", "colour")},
        "interval": parse_interval(route["interval"]),
        "service": stop_service(route["opening_hours"], minutes, at),
    }


def build_stop(row: dict[str, Any], routes: list[dict[str, Any]], at: datetime | None = None) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        # Trạm đã có tên riêng — để `rank_by_travel_time` tra tên đường sát
        # trạm làm địa chỉ ("Thảo Cầm Viên · Nguyễn Thị Minh Khai").
        "address": None,
        "streetAddress": None,
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "distanceMeters": round(row["distanceMeters"]),
        "shelter": row["shelter"],
        "bench": row["bench"],
        "routes": sorted(
            (_stop_route(route, at) for route in routes),
            key=lambda route: (natural_ref_key(route["ref"]), route["destination"] or ""),
        ),
    }


def search_stops(
    *,
    latitude: float,
    longitude: float,
    query: str = "",
    radius: int = DEFAULT_STOP_RADIUS_METERS,
    limit: int = 15,
) -> dict[str, Any]:
    """Trạm gần (xếp theo thời gian ĐI BỘ thật), hoặc tìm trạm theo tên khắp
    thành phố (xếp theo khoảng cách) khi có ``query``."""
    words = [_fold(word) for word in query.split() if _fold(word)]
    with psycopg.connect(settings.database_url, row_factory=dict_row) as connection:
        if words:
            rows = [
                row
                for row in connection.execute(_NAMED_STOPS_QUERY, {"lat": latitude, "lng": longitude}).fetchall()
                if all(word in _fold(row["name"]) for word in words)
            ][:limit]
        else:
            rows = connection.execute(
                _NEARBY_STOPS_QUERY, {"lat": latitude, "lng": longitude, "radius": radius}
            ).fetchall()
        route_rows = connection.execute(_STOP_ROUTES_QUERY, {"ids": [int(row["id"]) for row in rows]}).fetchall()
    routes_by_stop: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for route in route_rows:
        routes_by_stop[route["stop_id"]].append(route)
    stops = [build_stop(row, routes_by_stop[row["id"]]) for row in rows]

    if words:
        for stop in stops:
            stop["driveMinutes"] = stop["driveMeters"] = None
        return {"query": query, "radius": None, "approximate": False, "results": stops}
    results, approximate = charging.rank_by_travel_time(latitude, longitude, stops, "foot", limit, MAX_ROUTED)
    return {"query": "", "radius": radius, "approximate": approximate, "results": results}

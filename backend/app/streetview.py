"""Ảnh đường phố (xoay được 360°) cho trang chi tiết — nguồn là Mapillary.

Vì sao cần: Wikimedia Commons (`app/photos.py`) chỉ có ảnh CỦA địa điểm cho
khoảng 0,8% POI; phần còn lại là ảnh "khu vực" do geosearch trả về — chùa bên
cạnh, con đường, ảnh panoramio cũ. Mapillary thì khác: ảnh chụp từ xe chạy dọc
đường, phủ gần kín nội thành TP.HCM. Đo thật quanh khách sạn Trung Mai (785
Nguyễn Trãi, 2026-09-25): 193 ảnh trong bán kính ~60 m, 21 tấm 360°, tấm 360°
gần nhất cách 15 m.

Hai loại ảnh, chọn theo hai tiêu chí KHÁC NHAU:

- ``pano`` — ảnh 360°. Hướng máy quay không quan trọng vì xoay được, chỉ cần
  GẦN. Giao diện mở viewer quay sẵn về phía địa điểm (``bearingToPoi``).
- ``facing`` — ảnh thường mà máy quay NHÌN VỀ PHÍA địa điểm (lệch ≤
  ``FACING_TOLERANCE_DEG``). Xe Mapillary ở TP.HCM có camera gắn hông
  (``sg_left``/``sg_right``) nên loại này thường là ảnh chụp thẳng mặt tiền.
  Ảnh thường gần nhất mà quay lưng lại quán thì vô dụng, nên KHÔNG chọn theo
  khoảng cách thuần.

Trung thực: đây vẫn là ảnh ĐƯỜNG PHỐ, không phải ảnh do quán cung cấp — có
thể đã vài năm tuổi, mặt tiền có thể bị xe che. Hợp đồng trả kèm
``capturedAt`` và ``distanceMeters`` để giao diện ghi rõ "chụp tháng X/Y ·
cách N m", cùng nguyên tắc với nhãn "Ảnh khu vực" của Commons.

Vì sao đọc VECTOR TILE thay vì ``/images?bbox=``: search API của Mapillary trả
kết quả KHÔNG ỔN ĐỊNH. Đo thật (2026-09-25), cùng một bbox 120 m × 120 m gọi
liên tiếp trả 0, 113 rồi 193 ảnh; chia bbox làm bốn thì tổng lên tới 596 —
tức một lần gọi thường chỉ thấy một phần ba số ảnh, có lúc không thấy gì. Tile
phủ ảnh (z14, lớp ``image``) thì đầy đủ và tất định: một tile Q.5 nặng ~10 MB,
chứa ~166 nghìn điểm ảnh, parse 0,4 giây. Tile được cache lên đĩa; sau đó chỉ
hỏi chi tiết cho vài chục ảnh ứng viên bằng ``image_ids`` — truy vấn theo id thì
ổn định.

Token: ``MAPILLARY_CLIENT_TOKEN`` là *client token* — Mapillary thiết kế nó để
nằm ở trình duyệt (MapillaryJS bắt buộc phải có), chỉ đọc được ảnh công khai.
Vì vậy endpoint trả luôn token cho giao diện thay vì bắt frontend build lại với
biến môi trường riêng. KHÔNG dùng cơ chế này cho bất kỳ secret thật nào.
"""

from __future__ import annotations

import json
import logging
import math
import os
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import settings

logger = logging.getLogger("nearby-streetview")

MAPILLARY_IMAGES_URL = "https://graph.mapillary.com/images"
MAPILLARY_TILE_URL = "https://tiles.mapillary.com/maps/vtp/mly1_public/2/{z}/{x}/{y}"
# z14 là mức DUY NHẤT mà lớp `image` (từng điểm ảnh) có mặt trong tile phủ.
TILE_ZOOM = 14
# Tile Q.5 ~10 MB, tải mất ~5 giây — rộng tay hơn timeout của lời gọi API thường.
TILE_TIMEOUT_SECONDS = 30.0
# Xe Mapillary chạy lại một khu vài tháng một lần; một tuần là đủ tươi.
TILE_CACHE_SECONDS = 7 * 24 * 3600
# Tile đã parse giữ trong RAM (~2× kích thước file). Hai tile đủ cho một POI
# nằm sát mép tile, không giữ nhiều hơn.
TILE_MEMORY_SLOTS = 2
# Số ứng viên mỗi loại gửi sang bước hỏi chi tiết. Hướng máy quay trong tile là
# hướng GỐC từ thiết bị, có thể lệch hàng chục độ so với hướng đã hiệu chỉnh
# (đo thật: camera hông xe ghi 169°, Mapillary hiệu chỉnh thành 134°) — nên lọc
# thô rộng tay ở đây, lọc chặt sau khi có `computed_compass_angle`.
MAX_PANO_CANDIDATES = 8
MAX_FACING_CANDIDATES = 24
COARSE_FACING_TOLERANCE_DEG = 70.0

# Bán kính tìm ảnh. 60 m: ở TP.HCM mặt tiền thường nằm sát lề đường nên ảnh
# tốt luôn trong vài chục mét; xa hơn thì đã là khúc đường khác, ảnh "gần
# nhất" có thể là nhà cách ba căn.
SEARCH_RADIUS_METERS = 60
# Ảnh thường được coi là "nhìn về phía quán" khi hướng máy quay lệch hướng tới
# quán không quá bấy nhiêu độ — xấp xỉ nửa góc nhìn của camera hành trình.
FACING_TOLERANCE_DEG = 35.0
# Ảnh chụp ngay trên nóc toạ độ thì hướng tới quán không xác định được (và
# thường là toạ độ POI nằm giữa đường) — bỏ.
FACING_MIN_DISTANCE_METERS = 3.0
FACING_MAX_DISTANCE_METERS = 40.0
# Mỗi năm tuổi của ảnh tính như xa thêm bấy nhiêu mét. Mặt tiền ở TP.HCM đổi
# nhanh (biển hiệu, chủ mới): đo thật ở Trung Mai, xếp thuần theo khoảng cách
# thì chọn ảnh 2014 cách 23 m thay vì ảnh 2025 cách 31 m. 2 m/năm → ảnh 2014
# "cách" ~47 m, ảnh 2025 ~33 m.
AGE_PENALTY_METERS_PER_YEAR = 2.0
_MS_PER_YEAR = 365.25 * 24 * 3600 * 1000
# `quality_score` (0..1) Mapillary tự chấm, có trong tile. Dưới ngưỡng này là ảnh
# nhoè/tối — đo thật ở Trung Mai: ảnh đêm 21:42 nhoè được 0,06, ảnh chiều 17:07
# rõ biển hiệu được 0,65. Ảnh kém xếp SAU mọi ảnh đạt, bất kể gần hơn — vẫn
# dùng được khi quanh đó không còn ảnh nào khác.
MIN_GOOD_QUALITY = 0.3

FIELDS = ",".join(
    (
        "id",
        "is_pano",
        "captured_at",
        "compass_angle",
        "computed_compass_angle",
        "geometry",
        "computed_geometry",
        "creator",
        "thumb_1024_url",
    )
)

# Cache trong tiến trình: kết quả Mapillary đổi chậm (xe chạy lại vài tháng một
# lần), và một POI được mở lại nhiều lần trong một phiên demo.
CACHE_TTL_SECONDS = 24 * 3600
CACHE_MAX_ENTRIES = 2_000
_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_cache_lock = threading.Lock()

# Cùng lý do với `photos.MAX_CONCURRENT_FETCHES`: endpoint là `def`, chạy trong
# threadpool DÙNG CHUNG của FastAPI. Chặn số luồng cùng chờ Mapillary để một
# lúc mạng chậm không làm kẹt cả API.
MAX_CONCURRENT_FETCHES = 4
_fetch_slots = threading.BoundedSemaphore(MAX_CONCURRENT_FETCHES)


# --- Hình học -------------------------------------------------------------------


def distance_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Khoảng cách haversine (m)."""
    radius = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def bearing_degrees(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Hướng (0° = Bắc, theo chiều kim đồng hồ) từ điểm 1 tới điểm 2."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lng2 - lng1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def angle_difference(a: float, b: float) -> float:
    """Độ lệch nhỏ nhất giữa hai hướng, trong [0, 180]."""
    diff = abs(a - b) % 360.0
    return 360.0 - diff if diff > 180.0 else diff


def bbox_around(lat: float, lng: float, radius_m: float) -> str:
    """bbox ``minLng,minLat,maxLng,maxLat`` bao quanh một điểm."""
    dlat = radius_m / 111_320.0
    dlng = radius_m / (111_320.0 * max(0.01, math.cos(math.radians(lat))))
    return f"{lng - dlng:.6f},{lat - dlat:.6f},{lng + dlng:.6f},{lat + dlat:.6f}"


# --- Chọn ảnh -------------------------------------------------------------------


def _view(item: dict[str, Any], poi_lat: float, poi_lng: float) -> dict[str, Any] | None:
    """Chuẩn hoá một ảnh Mapillary về hợp đồng API. ``None`` nếu thiếu dữ liệu."""
    geometry = item.get("computed_geometry") or item.get("geometry") or {}
    coordinates = geometry.get("coordinates") or []
    if len(coordinates) < 2 or not item.get("id"):
        return None
    lng, lat = float(coordinates[0]), float(coordinates[1])
    compass = item.get("computed_compass_angle")
    if compass is None:
        compass = item.get("compass_angle")
    captured_at = item.get("captured_at")
    return {
        "imageId": str(item["id"]),
        "isPano": bool(item.get("is_pano")),
        "capturedAt": (
            datetime.fromtimestamp(captured_at / 1000, tz=timezone.utc).isoformat()
            if isinstance(captured_at, (int, float))
            else None
        ),
        "distanceMeters": round(distance_meters(lat, lng, poi_lat, poi_lng), 1),
        "bearingToPoi": round(bearing_degrees(lat, lng, poi_lat, poi_lng), 1),
        "compassAngle": round(float(compass), 1) if compass is not None else None,
        "creator": (item.get("creator") or {}).get("username"),
        "thumbUrl": item.get("thumb_1024_url"),
        "sourceUrl": f"https://www.mapillary.com/app/?pKey={item['id']}",
        "_capturedMs": captured_at if isinstance(captured_at, (int, float)) else 0,
        "_quality": item.get("quality_score"),
    }


def _rank(view: dict[str, Any]) -> tuple[int, float]:
    """Ảnh đạt chất lượng trước; trong cùng nhóm, điểm = khoảng cách + phạt
    theo tuổi ảnh, thấp hơn là tốt hơn. Không có điểm chất lượng thì coi như
    đạt; không có ngày chụp thì phạt như ảnh 10 năm tuổi."""
    quality = view.get("_quality")
    poor = int(isinstance(quality, (int, float)) and quality < MIN_GOOD_QUALITY)
    captured = view["_capturedMs"]
    age_years = (time.time() * 1000 - captured) / _MS_PER_YEAR if captured else 10.0
    return (poor, view["distanceMeters"] + AGE_PENALTY_METERS_PER_YEAR * max(0.0, age_years))


def _classify(
    items: list[dict[str, Any]],
    poi_lat: float,
    poi_lng: float,
    facing_tolerance_deg: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Tách ảnh 360° và ảnh thường nhìn về phía địa điểm, đã xếp hạng."""
    panos: list[dict[str, Any]] = []
    facing: list[dict[str, Any]] = []
    for item in items:
        view = _view(item, poi_lat, poi_lng)
        if view is None or view["distanceMeters"] > SEARCH_RADIUS_METERS:
            continue
        if view["isPano"]:
            panos.append(view)
            continue
        if view["compassAngle"] is None:
            continue
        if not (
            FACING_MIN_DISTANCE_METERS
            <= view["distanceMeters"]
            <= FACING_MAX_DISTANCE_METERS
        ):
            continue
        if angle_difference(view["compassAngle"], view["bearingToPoi"]) <= facing_tolerance_deg:
            facing.append(view)
    panos.sort(key=_rank)
    facing.sort(key=_rank)
    return panos, facing


def choose_views(
    items: list[dict[str, Any]], poi_lat: float, poi_lng: float
) -> dict[str, dict[str, Any] | None]:
    """Chọn ảnh 360° tốt nhất và ảnh thường nhìn thẳng về địa điểm tốt nhất.

    ``items`` nên mang ``computed_*`` (hướng/vị trí đã hiệu chỉnh) — lọc hướng
    ở đây là lọc CHẶT.
    """
    panos, facing = _classify(items, poi_lat, poi_lng, FACING_TOLERANCE_DEG)

    def best(views: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not views:
            return None
        chosen = dict(views[0])
        chosen.pop("_capturedMs", None)
        chosen.pop("_quality", None)
        return chosen

    return {"pano": best(panos), "facing": best(facing)}


def candidate_ids(items: list[dict[str, Any]], poi_lat: float, poi_lng: float) -> list[str]:
    """Lọc THÔ trên dữ liệu tile (hướng gốc chưa hiệu chỉnh) để chọn ra vài
    chục ảnh đáng hỏi chi tiết."""
    panos, facing = _classify(items, poi_lat, poi_lng, COARSE_FACING_TOLERANCE_DEG)
    return [view["imageId"] for view in panos[:MAX_PANO_CANDIDATES]] + [
        view["imageId"] for view in facing[:MAX_FACING_CANDIDATES]
    ]


# --- Vector tile phủ ảnh --------------------------------------------------------

_tile_class: Any = None


def _vector_tile_class() -> Any:
    """Lớp protobuf cho định dạng Mapbox Vector Tile, dựng từ descriptor.

    Dựng tại chỗ thay vì sinh file ``_pb2`` hay thêm gói giải mã MVT: chỉ cần bốn
    message của spec vector-tile 2.1, và parser C của protobuf nhanh hơn giải
    mã tay bằng Python cả chục lần trên tile 10 MB.
    """
    global _tile_class
    if _tile_class is not None:
        return _tile_class
    from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

    field = descriptor_pb2.FieldDescriptorProto
    optional, repeated = field.LABEL_OPTIONAL, field.LABEL_REPEATED
    file_proto = descriptor_pb2.FileDescriptorProto(
        name="nearby_vector_tile.proto", package="nearby_vt", syntax="proto2"
    )
    tile = file_proto.message_type.add(name="Tile")
    tile.field.add(
        name="layers",
        number=3,
        type=field.TYPE_MESSAGE,
        label=repeated,
        type_name=".nearby_vt.Tile.Layer",
    )
    value = tile.nested_type.add(name="Value")
    for name, number, kind in _value_field_specs(field):
        value.field.add(name=name, number=number, type=kind, label=optional)
    feature = tile.nested_type.add(name="Feature")
    feature.field.add(name="id", number=1, type=field.TYPE_UINT64, label=optional)
    for name, number in (("tags", 2), ("geometry", 4)):
        packed = feature.field.add(
            name=name, number=number, type=field.TYPE_UINT32, label=repeated
        )
        packed.options.packed = True
    feature.field.add(name="type", number=3, type=field.TYPE_UINT32, label=optional)
    layer = tile.nested_type.add(name="Layer")
    layer.field.add(name="version", number=15, type=field.TYPE_UINT32, label=optional)
    layer.field.add(name="name", number=1, type=field.TYPE_STRING, label=optional)
    layer.field.add(
        name="features",
        number=2,
        type=field.TYPE_MESSAGE,
        label=repeated,
        type_name=".nearby_vt.Tile.Feature",
    )
    layer.field.add(name="keys", number=3, type=field.TYPE_STRING, label=repeated)
    layer.field.add(
        name="values",
        number=4,
        type=field.TYPE_MESSAGE,
        label=repeated,
        type_name=".nearby_vt.Tile.Value",
    )
    layer.field.add(name="extent", number=5, type=field.TYPE_UINT32, label=optional)

    pool = descriptor_pool.DescriptorPool()
    pool.Add(file_proto)
    _tile_class = message_factory.GetMessageClass(
        pool.FindMessageTypeByName("nearby_vt.Tile")
    )
    return _tile_class


# Tên trường của message Value, theo thứ tự trong spec vector-tile.
_VALUE_FIELDS = (
    "string_value",
    "float_value",
    "double_value",
    "int_value",
    "uint_value",
    "sint_value",
    "bool_value",
)


def _value_field_specs(field: Any) -> list[tuple[str, int, int]]:
    kinds = (
        field.TYPE_STRING,
        field.TYPE_FLOAT,
        field.TYPE_DOUBLE,
        field.TYPE_INT64,
        field.TYPE_UINT64,
        field.TYPE_SINT64,
        field.TYPE_BOOL,
    )
    return [(name, number, kind) for number, (name, kind) in enumerate(zip(_VALUE_FIELDS, kinds), 1)]


def _value(value: Any) -> Any:
    for name in _VALUE_FIELDS:
        if value.HasField(name):
            return getattr(value, name)
    return None


def tile_xy(lat: float, lng: float, zoom: int = TILE_ZOOM) -> tuple[float, float]:
    """Toạ độ tile (số thực — phần lẻ là vị trí bên trong tile), Web Mercator."""
    n = 2**zoom
    x = (lng + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    return x, y


def tile_to_lat_lng(x: float, y: float, zoom: int = TILE_ZOOM) -> tuple[float, float]:
    n = 2**zoom
    lng = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n))))
    return lat, lng


def _zigzag(n: int) -> int:
    return (n >> 1) ^ -(n & 1)


def points_in_tile(
    tile: Any, tx: int, ty: int, south: float, west: float, north: float, east: float
) -> list[dict[str, Any]]:
    """Điểm ảnh của lớp ``image`` nằm trong bbox, ở dạng giống API ``/images``.

    Lọc theo toạ độ pixel TRƯỚC rồi mới giải mã thuộc tính: tile có ~166 nghìn
    điểm, chỉ vài trăm nằm trong bbox.
    """
    layer = next((item for item in tile.layers if item.name == "image"), None)
    if layer is None:
        return []
    extent = layer.extent or 4096
    x0, y0 = tile_xy(north, west)
    x1, y1 = tile_xy(south, east)
    px_min, px_max = (x0 - tx) * extent, (x1 - tx) * extent
    py_min, py_max = (y0 - ty) * extent, (y1 - ty) * extent
    keys = list(layer.keys)
    values = layer.values

    points: list[dict[str, Any]] = []
    for feature in layer.features:
        geometry = feature.geometry
        # Điểm đơn: [MoveTo × 1 (= 9), zigzag(x), zigzag(y)].
        if len(geometry) < 3 or geometry[0] != 9:
            continue
        px, py = _zigzag(geometry[1]), _zigzag(geometry[2])
        if not (px_min <= px <= px_max and py_min <= py <= py_max):
            continue
        tags = feature.tags
        props = {
            keys[tags[i]]: _value(values[tags[i + 1]]) for i in range(0, len(tags) - 1, 2)
        }
        lat, lng = tile_to_lat_lng(tx + px / extent, ty + py / extent)
        props["geometry"] = {"type": "Point", "coordinates": [lng, lat]}
        if props.get("id") is None:
            props["id"] = feature.id
        points.append(props)
    return points


_tile_memory: OrderedDict[tuple[int, int], tuple[float, Any]] = OrderedDict()
_tile_lock = threading.Lock()


def _tile_path(tx: int, ty: int) -> Path:
    root = settings.mapillary_tile_dir or os.path.join(tempfile.gettempdir(), "nearby-mapillary")
    return Path(root) / f"{TILE_ZOOM}-{tx}-{ty}.mvt"


def _load_tile(tx: int, ty: int) -> Any | None:
    """Tile đã parse. Thứ tự: RAM → đĩa (còn hạn) → tải về. ``None`` khi lỗi.

    Giữ khoá suốt lúc tải: hai request cùng tile mà cùng tải là 20 MB phí.
    """
    with _tile_lock:
        cached = _tile_memory.get((tx, ty))
        if cached is not None and time.time() - cached[0] < TILE_CACHE_SECONDS:
            _tile_memory.move_to_end((tx, ty))
            return cached[1]

        path = _tile_path(tx, ty)
        if path.exists() and time.time() - path.stat().st_mtime < TILE_CACHE_SECONDS:
            data = path.read_bytes()
        else:
            url = MAPILLARY_TILE_URL.format(z=TILE_ZOOM, x=tx, y=ty)
            query = urllib.parse.urlencode({"access_token": settings.mapillary_client_token})
            try:
                with urllib.request.urlopen(
                    f"{url}?{query}", timeout=TILE_TIMEOUT_SECONDS
                ) as response:
                    data = response.read()
            except urllib.error.HTTPError as error:
                # KHÔNG log URL: nó chứa token.
                logger.warning("Tile Mapillary trả HTTP %s", error.code)
                return None
            except (urllib.error.URLError, OSError) as error:
                logger.debug("Không tải được tile Mapillary: %s", error)
                return None
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                partial = path.with_suffix(".part")
                partial.write_bytes(data)
                os.replace(partial, path)
            except OSError as error:
                logger.debug("Không ghi được cache tile: %s", error)

        tile = _vector_tile_class()()
        try:
            tile.ParseFromString(data)
        except Exception as error:  # DecodeError: file hỏng thì xoá để lần sau tải lại
            logger.warning("Tile Mapillary hỏng: %s", error)
            path.unlink(missing_ok=True)
            return None
        _tile_memory[(tx, ty)] = (time.time(), tile)
        while len(_tile_memory) > TILE_MEMORY_SLOTS:
            _tile_memory.popitem(last=False)
        return tile


def _nearby_points(lat: float, lng: float) -> list[dict[str, Any]] | None:
    """Mọi điểm ảnh trong bbox bán kính ``SEARCH_RADIUS_METERS``, qua 1-4 tile."""
    west, south, east, north = (
        float(v) for v in bbox_around(lat, lng, SEARCH_RADIUS_METERS).split(",")
    )
    x0, y0 = tile_xy(north, west)
    x1, y1 = tile_xy(south, east)
    points: list[dict[str, Any]] = []
    for tx in range(int(x0), int(x1) + 1):
        for ty in range(int(y0), int(y1) + 1):
            tile = _load_tile(tx, ty)
            if tile is None:
                return None
            points.extend(points_in_tile(tile, tx, ty, south, west, north, east))
    return points


# --- Chi tiết ảnh ---------------------------------------------------------------


def _image_details(image_ids: list[str]) -> list[dict[str, Any]] | None:
    """Vị trí/hướng ĐÃ HIỆU CHỈNH + thumbnail cho các ảnh ứng viên.

    Hỏi theo ``image_ids`` — khác hẳn hỏi theo bbox, cách này trả đủ và ổn định.
    ``None`` = không hỏi được (khác với danh sách rỗng).
    """
    if not image_ids:
        return []
    query = urllib.parse.urlencode(
        {
            "access_token": settings.mapillary_client_token,
            "image_ids": ",".join(image_ids),
            "fields": FIELDS,
        }
    )
    request = urllib.request.Request(
        f"{MAPILLARY_IMAGES_URL}?{query}", headers={"Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(
            request, timeout=settings.mapillary_timeout_seconds
        ) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        # KHÔNG log URL: nó chứa token.
        logger.warning("Mapillary trả HTTP %s", error.code)
        return None
    except (urllib.error.URLError, OSError, ValueError) as error:
        logger.debug("Không gọi được Mapillary: %s", error)
        return None
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, list) else None


def _search_images(lat: float, lng: float) -> list[dict[str, Any]] | None:
    """Ảnh quanh một điểm, đã có chi tiết hiệu chỉnh. ``None`` = không hỏi được."""
    points = _nearby_points(lat, lng)
    if points is None:
        return None
    details = _image_details(candidate_ids(points, lat, lng))
    if details is None:
        return None
    # `quality_score` chỉ có trong tile, API chi tiết không trả — ghép theo id.
    quality = {str(point.get("id")): point.get("quality_score") for point in points}
    for item in details:
        item.setdefault("quality_score", quality.get(str(item.get("id"))))
    return details


def _unavailable(poi_id: str) -> dict[str, Any]:
    return {"poiId": poi_id, "status": "unavailable", "pano": None, "facing": None}


def street_views(poi_id: str, lat: float, lng: float) -> dict[str, Any]:
    """Ảnh đường phố cho một POI.

    Ba trạng thái, cùng ý nghĩa với endpoint ảnh:
      ``ready``       — có ít nhất một ảnh dùng được.
      ``empty``       — ĐÃ hỏi Mapillary, quanh đây không có ảnh phù hợp.
      ``unavailable`` — chưa hỏi được (không có token, mất mạng, API lỗi).
    Chỉ ``ready``/``empty`` được cache.
    """
    token = settings.mapillary_client_token
    if not token:
        return _unavailable(poi_id)

    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(poi_id)
        if hit is not None and now - hit[0] < CACHE_TTL_SECONDS:
            return hit[1]

    if not _fetch_slots.acquire(timeout=0.5):
        return _unavailable(poi_id)
    try:
        items = _search_images(lat, lng)
    finally:
        _fetch_slots.release()
    if items is None:
        return _unavailable(poi_id)

    views = choose_views(items, lat, lng)
    result = {
        "poiId": poi_id,
        "status": "ready" if views["pano"] or views["facing"] else "empty",
        "accessToken": token,
        "license": "CC BY-SA 4.0",
        **views,
    }
    with _cache_lock:
        if len(_cache) >= CACHE_MAX_ENTRIES:
            _cache.pop(next(iter(_cache)))
        _cache[poi_id] = (now, result)
    return result

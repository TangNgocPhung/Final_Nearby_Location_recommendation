"""Deterministic enrichment helpers used by migrations and POI ingestion."""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable

import h3

from .opening_hours import is_open_now, parse_opening_hours


EMBEDDING_DIMENSION = 64
# v2: sửa lỗi hai slot băm trùng nhau làm vector triệt tiêu về 0 (xem
# text_embedding). Đổi tên model là bắt buộc: vector v1 đã lưu trong
# pois.embedding không so sánh được với vector v2 sinh lúc truy vấn, nên
# migration 0005 tính lại toàn bộ hàng còn mang model cũ.
EMBEDDING_MODEL = "hashing-v2-64"
DEFAULT_TIMEZONE = "Asia/Ho_Chi_Minh"

DISTRICT_ALIASES = {
    "tan binh": "Quận Tân Bình",
    "phu nhuan": "Quận Phú Nhuận",
    "binh thanh": "Quận Bình Thạnh",
    "binh tan": "Quận Bình Tân",
    "go vap": "Quận Gò Vấp",
    "tan phu": "Quận Tân Phú",
    "thu duc": "TP. Thủ Đức",
    "hoc mon": "Huyện Hóc Môn",
    "binh chanh": "Huyện Bình Chánh",
    "nha be": "Huyện Nhà Bè",
    "cu chi": "Huyện Củ Chi",
    "can gio": "Huyện Cần Giờ",
}

CATEGORY_MAP: dict[tuple[str, str], tuple[str, str]] = {
    ("amenity", "cafe"): ("cafe", "Cà phê"),
    ("amenity", "restaurant"): ("restaurant", "Ăn uống"),
    ("amenity", "fast_food"): ("restaurant", "Ăn uống"),
    ("amenity", "bar"): ("bar", "Giải trí"),
    ("amenity", "pub"): ("bar", "Giải trí"),
    ("amenity", "hospital"): ("hospital", "Y tế"),
    ("amenity", "clinic"): ("hospital", "Y tế"),
    ("amenity", "pharmacy"): ("pharmacy", "Y tế"),
    ("amenity", "school"): ("school", "Giáo dục"),
    ("amenity", "university"): ("university", "Giáo dục"),
    ("amenity", "bank"): ("bank", "Dịch vụ"),
    ("amenity", "atm"): ("atm", "Dịch vụ"),
    ("amenity", "marketplace"): ("market", "Chợ"),
    ("amenity", "cinema"): ("cinema", "Xem phim"),
    ("amenity", "theatre"): ("theatre", "Văn hóa"),
    ("amenity", "library"): ("library", "Văn hóa"),
    ("tourism", "museum"): ("museum", "Văn hóa"),
    ("tourism", "attraction"): ("landmark", "Địa danh"),
    ("tourism", "viewpoint"): ("landmark", "Địa danh"),
    ("tourism", "hotel"): ("hotel", "Lưu trú"),
    ("tourism", "gallery"): ("gallery", "Văn hóa"),
    ("leisure", "park"): ("park", "Công viên"),
    ("leisure", "garden"): ("park", "Công viên"),
    ("leisure", "fitness_centre"): ("gym", "Thể thao"),
    ("leisure", "sports_centre"): ("gym", "Thể thao"),
    ("leisure", "playground"): ("playground", "Giải trí"),
    ("shop", "supermarket"): ("supermarket", "Mua sắm"),
    ("shop", "mall"): ("shopping_mall", "Mua sắm"),
    ("shop", "convenience"): ("convenience", "Mua sắm"),
    ("shop", "books"): ("bookstore", "Mua sắm"),
    ("shop", "bakery"): ("bakery", "Ăn uống"),
    ("shop", "clothes"): ("clothes", "Mua sắm"),
    ("shop", "electronics"): ("electronics", "Mua sắm"),
    ("aeroway", "aerodrome"): ("airport", "Sân bay"),
    ("leisure", "spa"): ("spa", "Spa"),
}

# Từ khoá tiếng Việt gắn theo LOẠI địa điểm, dùng riêng cho truy xuất (không
# hiển thị, không ghi vào cột `tags` của POI).
#
# Vì sao cần: tên rạp chiếu phim ở TP.HCM gần như không bao giờ chứa chữ
# "phim" (CGV, Lotte Cinema, BHD Star, Galaxy, Mega GS, Cinestar), còn thẻ OSM
# chỉ để lại token tiếng Anh "cinema". Truy vấn "xem phim" vì thế không khớp
# BM25 ở BẤT KỲ trường nào. Mà `search.retrieval._gate_by_text_relevance` chỉ
# giữ candidate khớp chữ khi BM25 có kết quả, còn khi BM25 rỗng thì nhường cho
# RRF — nên "xem phim" rơi vào đúng nhánh xấu nhất: trả về POI gần nhất bất kể
# loại gì (đo được 19/09/2026: bảo tàng và quán phở đứng đầu).
#
# Gắn theo loại chứ không theo từng POI: một rạp mới nhập từ OSM ngày mai được
# hưởng nguyên bộ từ khoá mà không phải sửa dữ liệu. Cũng không dùng synonym
# filter của analyzer: filter đó áp lên MỌI trường (kể cả tên riêng) nên dễ tạo
# khớp nhầm, và mỗi lần thêm một từ là một lần phải dựng lại chỉ mục.
#
# Nguyên tắc chọn từ khoá: chỉ nhận cụm mà người Việt GÕ KHI TÌM loại đó, và
# tránh âm tiết đơn vốn là một phần của tên riêng. "trường" bị loại vì "Công
# trường Lam Sơn", "Công trường Quốc Tế" là địa danh thật; "trường học" thì an
# toàn. Đây đúng là loại lỗi mà fuzzy "AUTO" từng gây ra cho "bệnh viện".
CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    # Ăn uống
    "restaurant": ("nhà hàng", "quán ăn", "ăn uống", "quán cơm", "chỗ ăn", "đồ ăn"),
    "bakery": ("tiệm bánh", "lò bánh", "bánh ngọt"),
    "cafe": ("quán cà phê", "cà phê", "cafe", "coffee", "quán nước"),
    "bar": ("quán bar", "quán nhậu", "pub", "bia hơi"),
    # Mua sắm
    "supermarket": ("siêu thị", "đi siêu thị"),
    "shopping_mall": ("trung tâm thương mại", "trung tâm mua sắm", "mua sắm"),
    "convenience": ("cửa hàng tiện lợi", "tạp hóa", "tiện lợi"),
    "bookstore": ("nhà sách", "hiệu sách", "mua sách"),
    "clothes": ("quần áo", "thời trang", "shop quần áo"),
    "electronics": ("điện máy", "điện tử", "đồ điện"),
    "market": ("chợ", "đi chợ", "chợ truyền thống"),
    # Y tế
    "hospital": ("bệnh viện", "phòng khám", "khám bệnh", "cấp cứu"),
    "pharmacy": ("nhà thuốc", "hiệu thuốc", "tiệm thuốc", "thuốc tây", "mua thuốc"),
    # Giáo dục
    "school": ("trường học", "trường tiểu học", "trường cấp hai", "trường cấp ba"),
    "university": ("đại học", "trường đại học", "cao đẳng"),
    # Dịch vụ
    "bank": ("ngân hàng", "chi nhánh ngân hàng"),
    "atm": ("atm", "cây atm", "rút tiền", "máy rút tiền"),
    # Lưu trú
    "hotel": ("khách sạn", "nhà nghỉ", "chỗ ở", "lưu trú", "homestay"),
    # Văn hóa
    "museum": ("bảo tàng",),
    "theatre": ("nhà hát", "sân khấu", "xem kịch"),
    "library": ("thư viện",),
    "gallery": ("phòng tranh", "triển lãm"),
    # Giải trí
    "cinema": (
        "rạp chiếu phim",
        "rạp phim",
        "xem phim",
        "coi phim",
        "chiếu phim",
        "suất chiếu",
        "phim",
    ),
    "playground": ("khu vui chơi", "sân chơi", "chỗ cho trẻ chơi"),
    # Ngoài trời / thể thao
    "park": ("công viên", "vườn hoa", "chỗ đi dạo"),
    "gym": ("phòng gym", "phòng tập", "gym", "thể hình", "tập thể dục"),
    # Địa danh
    "landmark": ("điểm tham quan", "địa danh", "danh lam", "chỗ tham quan"),
    # Giao thông
    "airport": ("sân bay", "phi trường", "sân bay quốc tế", "đi máy bay"),
    # Chăm sóc sức khoẻ / làm đẹp
    "spa": ("spa", "đi spa", "mát xa", "massage", "chăm sóc da", "thư giãn"),
}


def normalize_text(value: str | None) -> str:
    text = (value or "").replace("Đ", "D").replace("đ", "d")
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", ascii_text.lower()).strip()


def normalize_district(value: str | None) -> str | None:
    normalized = normalize_text(value)
    if not normalized:
        return None
    number_match = re.fullmatch(r"(?:(?:quan|district)\s*)?(\d{1,2})", normalized)
    if number_match:
        number = int(number_match.group(1))
        return f"Quận {number}" if 1 <= number <= 12 else None
    without_prefix = re.sub(r"^(?:quan|district|huyen)\s+", "", normalized)
    return DISTRICT_ALIASES.get(without_prefix)


def text_embedding(parts: Iterable[str | None], dimension: int = EMBEDDING_DIMENSION) -> list[float]:
    """Hashing trick: mỗi token cộng dấu vào hai slot của vector.

    Hai slot bắt buộc phải khác nhau. Ở phiên bản v1 cả hai slot lấy modulo cùng
    `dimension` nên có xác suất trùng; khi trùng mà hai dấu ngược nhau thì token
    tự triệt tiêu. Với truy vấn chỉ một từ, vector kết quả toàn 0 — OpenSearch
    từ chối k-NN trên vector 0, nên kênh Vector ANN chết âm thầm. Đo thực tế:
    0,78% từ đơn dính lỗi này, trong đó có đúng từ "phở".

    v2 lấy slot thứ hai theo modulo (dimension - 1) rồi dịch khỏi slot thứ nhất
    ít nhất một bậc, nên hai slot không bao giờ trùng.
    """
    tokens = normalize_text(" ".join(part or "" for part in parts)).split()
    vector = [0.0] * dimension
    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=16).digest()
        first = int.from_bytes(digest[0:4], "big") % dimension
        second = (int.from_bytes(digest[4:8], "big") % (dimension - 1) + first + 1) % dimension
        for offset, index in ((0, first), (4, second)):
            sign = 1.0 if digest[offset + 8] & 1 else -1.0
            vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    return [round(value / norm, 8) for value in vector] if norm else vector


def h3_cells(latitude: float, longitude: float) -> dict[str, str]:
    return {
        "r7": h3.latlng_to_cell(latitude, longitude, 7),
        "r8": h3.latlng_to_cell(latitude, longitude, 8),
        "r9": h3.latlng_to_cell(latitude, longitude, 9),
    }


# --- Vành hexagon H3 cho kênh truy xuất không gian (lộ trình B3) ---------------
#
# Độ phân giải xét từ mịn tới thô. Càng mịn thì vành càng bám sát hình tròn (ít
# POI dư), nhưng số ô trong truy vấn ``terms`` tăng theo bình phương k.
H3_RING_RESOLUTIONS = (9, 8, 7)

# Trần số ô cho một truy vấn ``terms``. Vượt trần này thì vành hexagon hết rẻ
# hơn geo_distance, nên ``h3_ring_ids`` trả None để gọi bên lọc theo khoảng cách.
H3_RING_MAX_CELLS = 512

# Khoảng cách giữa tâm hai ô kề nhau = cạnh * sqrt(3) (hình lục giác đều).
_H3_CENTER_SPACING = math.sqrt(3.0)


@dataclass(frozen=True)
class H3Ring:
    """Vành hexagon phủ một hình tròn tìm kiếm."""

    resolution: int
    k: int
    origin: str
    cells: tuple[str, ...]

    @property
    def field(self) -> str:
        """Tên trường trong chỉ mục OpenSearch, ví dụ ``h3_r8``."""
        return f"h3_r{self.resolution}"


def h3_ring_size(radius_m: float, resolution: int) -> int:
    """Số vành k nhỏ nhất **chắc chắn** phủ hết hình tròn bán kính ``radius_m``.

    Chứng minh cận: gọi O là tâm tìm kiếm, P một điểm cách O đúng ``radius_m``.
    Tâm ô chứa O cách O tối đa một cạnh; tâm ô chứa P cũng vậy. Nên hai tâm ô
    cách nhau tối đa ``radius_m + 2 * cạnh``. Chia cho khoảng cách tâm-tâm của
    hai ô kề nhau rồi làm tròn lên là được số bước lưới cần thiết.
    """
    edge_m = h3.average_hexagon_edge_length(resolution, unit="m")
    spacing = _H3_CENTER_SPACING * edge_m
    return max(1, math.ceil((max(radius_m, 0.0) + 2.0 * edge_m) / spacing))


def h3_ring_cell_count(k: int) -> int:
    """Số ô trong ``grid_disk`` bán kính k: 3k² + 3k + 1 (dãy số tâm lục giác)."""
    return 3 * k * k + 3 * k + 1


def h3_ring_ids(
    latitude: float,
    longitude: float,
    radius_m: float,
    max_cells: int = H3_RING_MAX_CELLS,
) -> H3Ring | None:
    """Quy một bán kính tìm kiếm thành tập mã hexagon phủ trùm nó.

    Đây là phần còn thiếu của "Channel 2: Geo-Fence Filtering (H3 Ring)" trong
    sơ đồ kiến trúc: ba cột ``h3_r7/r8/r9`` đã sinh và đã index từ đầu, nhưng
    chưa có đường dây nào biến chúng thành điều kiện lọc.

    Khác biệt so với ``geo_distance`` không nằm ở kết quả mà ở **cách lọc**:
    thay vì bắt OpenSearch tính khoảng cách trên từng document, ta tra chỉ mục
    đảo bằng ``terms``.

    Đánh đổi: vành hexagon **phủ trùm** hình tròn chứ không trùng khít, nên trả
    về dư một ít POI nằm ngoài bán kính. Đó là chủ ý — ``enrichment.hydrate_
    candidates`` lọc lại bằng ``ST_DWithin``, nên dư thì bị cắt, còn thiếu thì
    mất hẳn recall và không cách nào lấy lại. Mọi công thức trên vì vậy làm
    tròn về phía phủ rộng hơn.

    Trả ``None`` khi ngay cả độ phân giải thô nhất cũng vượt ``max_cells``.
    """
    if max_cells < 1:
        return None
    for resolution in H3_RING_RESOLUTIONS:
        k = h3_ring_size(radius_m, resolution)
        if h3_ring_cell_count(k) > max_cells:
            continue
        origin = h3.latlng_to_cell(latitude, longitude, resolution)
        return H3Ring(
            resolution=resolution,
            k=k,
            origin=origin,
            cells=tuple(sorted(h3.grid_disk(origin, k))),
        )
    return None


def h3_ring_geometry(ring: "H3Ring") -> dict[str, Any] | None:
    """Đường bao hợp nhất của vành hexagon, dạng GeoJSON Polygon.

    Để giao diện VẼ ĐƯỢC vùng mà kênh H3 thật sự đã quét. Không có nó thì
    hexagon vẫn là thứ chỉ tồn tại trong log — hội đồng hỏi "H3 dùng ở đâu" thì
    không chỉ ra được cái gì trên màn hình.

    Trả đường bao hợp nhất chứ không trả từng ô: 331 ô ở r9 mỗi ô 7 đỉnh là
    khoảng 2.300 toạ độ, còn đường bao chỉ ~127 đỉnh (~2,7 KB sau khi làm tròn
    5 chữ số, tức +3% response).

    ``cells_to_h3shape`` cho vòng ĐÃ ĐÓNG và toạ độ theo thứ tự (lng, lat) —
    đúng quy ước GeoJSON. Không dùng ``cell_to_boundary``: nó trả (lat, lng) và
    vòng hở, vẽ lên bản đồ sẽ ra hình méo mà không báo lỗi gì.
    """
    try:
        shape = h3.cells_to_h3shape(list(ring.cells), tight=True)
        geo = h3.h3shape_to_geo(shape)
    except (ValueError, TypeError, AttributeError):
        return None
    if not isinstance(geo, dict) or geo.get("type") not in ("Polygon", "MultiPolygon"):
        return None

    def round_ring(coords):
        return [[round(float(x), 5), round(float(y), 5)] for x, y in coords]

    if geo["type"] == "Polygon":
        geo = {"type": "Polygon", "coordinates": [round_ring(r) for r in geo["coordinates"]]}
    else:
        geo = {
            "type": "MultiPolygon",
            "coordinates": [[round_ring(r) for r in poly] for poly in geo["coordinates"]],
        }
    return geo


def dedupe_fingerprint(
    name: str,
    category: str,
    latitude: float,
    longitude: float,
) -> str:
    payload = f"{normalize_text(name)}|{category}|{latitude:.5f}|{longitude:.5f}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def category_keywords(category: str | None) -> tuple[str, ...]:
    """Từ khoá truy xuất của một loại địa điểm (rỗng nếu loại đó chưa khai báo)."""
    return CATEGORY_KEYWORDS.get((category or "").strip(), ())


def categories_for_query(query_text: str | None) -> tuple[str, ...]:
    """Các loại địa điểm mà truy vấn đang NHẮM TỚI, suy từ `CATEGORY_KEYWORDS`.

    So khớp trên chuỗi đã chuẩn hoá (`normalize_text`) nên "rạp chiếu phim",
    "rap chieu phim" và "RẠP CHIẾU PHIM" cho cùng một kết quả — người dùng gõ
    không dấu là trường hợp phổ biến nhất, không phải ngoại lệ.

    So khớp theo RANH GIỚI TỪ (đệm dấu cách hai đầu) chứ không phải `in` trần:
    từ khoá một âm tiết như "phim" mà so kiểu chuỗi con sẽ khớp cả vào giữa một
    từ khác, đúng kiểu lỗi mà fuzzy "AUTO" đã gây ra cho "bệnh viện" (xem
    `search.query.bm25_body`). Đệm dấu cách cũng xử lý luôn từ khoá nhiều âm
    tiết, nên không cần tách token riêng.
    """
    normalized = normalize_text(query_text)
    if not normalized:
        return ()
    haystack = f" {normalized} "
    matched = {
        category
        for category, keywords in CATEGORY_KEYWORDS.items()
        if any(f" {normalize_text(keyword)} " in haystack for keyword in keywords)
    }
    return tuple(sorted(matched))


def osm_category(tags: dict[str, str]) -> tuple[str, str] | None:
    for key in ("amenity", "tourism", "leisure", "shop", "aeroway"):
        value = tags.get(key)
        if value and (key, value) in CATEGORY_MAP:
            return CATEGORY_MAP[(key, value)]
    return None


def _address(tags: dict[str, str]) -> str:
    street = tags.get("addr:street") or tags.get("addr:place")
    parts = [tags.get("addr:housenumber"), street, tags.get("addr:district")]
    return ", ".join(part for part in parts if part)


def _amenities(tags: dict[str, str]) -> dict[str, bool | str]:
    keys = (
        "wheelchair",
        "internet_access",
        "outdoor_seating",
        "delivery",
        "takeaway",
        "parking",
        "toilets",
    )
    return {key: tags[key] for key in keys if key in tags}


def normalize_osm_element(element: dict[str, Any]) -> dict[str, Any] | None:
    tags = element.get("tags") or {}
    name = tags.get("name") or tags.get("name:vi")
    category_value = osm_category(tags)
    center = element.get("center") or element
    if not name or not category_value or "lat" not in center or "lon" not in center:
        return None
    category, category_label = category_value
    latitude, longitude = float(center["lat"]), float(center["lon"])
    searchable_tags = sorted(
        {
            value
            for key in ("amenity", "tourism", "leisure", "shop", "aeroway", "cuisine")
            for value in str(tags.get(key, "")).split(";")
            if value
        }
    )
    opening_hours = parse_opening_hours(tags.get("opening_hours"))
    description = tags.get("description:vi") or tags.get("description") or ""
    district = normalize_district(
        tags.get("addr:district") or tags.get("addr:city_district") or tags.get("addr:suburb")
    )
    source_id = f"{element.get('type', 'node')}/{element['id']}"
    cells = h3_cells(latitude, longitude)
    embedding = text_embedding((name, description, " ".join(searchable_tags)))
    return {
        "name": name.strip(),
        "normalized_name": normalize_text(name),
        "description": description.strip(),
        "category": category,
        "category_label": category_label,
        "address": _address(tags),
        "normalized_address": normalize_text(_address(tags)),
        "latitude": latitude,
        "longitude": longitude,
        "opening_hours": opening_hours,
        "timezone": DEFAULT_TIMEZONE,
        "open_now": is_open_now(opening_hours, DEFAULT_TIMEZONE),
        "price_level": 0,
        "amenities": _amenities(tags),
        "tags": searchable_tags,
        "brand": tags.get("brand") or tags.get("operator"),
        "district": district,
        "city": tags.get("addr:city") or "Hồ Chí Minh",
        "country_code": (tags.get("addr:country") or "VN").upper(),
        "source": "openstreetmap",
        "source_id": source_id,
        "h3_r7": cells["r7"],
        "h3_r8": cells["r8"],
        "h3_r9": cells["r9"],
        "embedding": embedding,
        "embedding_model": EMBEDDING_MODEL,
        "dedupe_fingerprint": dedupe_fingerprint(name, category, latitude, longitude),
        "raw_payload": element,
    }

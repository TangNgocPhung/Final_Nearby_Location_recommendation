"""Các hàm thuần dựng truy vấn OpenSearch cho từng kênh truy xuất.

Tách khỏi client để test được mà không cần OpenSearch. Mỗi hàm trả về một
``body`` truyền thẳng vào ``client.search(index=..., body=body)``.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from ..config import settings
from ..poi_features import categories_for_query, normalize_text

# Trường của hai clause văn bản. Cổng token (`_token_gate`) dùng lại đúng các
# trường này, bỏ boost (filter không chấm điểm) và bỏ `name.prefix`.
_FOLDED_FIELDS = (
    "name^3",
    "name.prefix^1.5",
    "category_label^2",
    "search_keywords^2",
    "tags^1.5",
    "brand^1.5",
    "description",
)
_STRICT_FIELDS = (
    "name.strict^5",
    "category_label.strict^3",
    "search_keywords.strict^3",
    "tags.strict^2",
    "description.strict^1.5",
)
# AUTO:5,8 thay cho AUTO (=3,6): token <= 4 ký tự phải khớp ĐÚNG. Âm tiết tiếng
# Việt sau khi bỏ dấu phần lớn chỉ 2-4 ký tự, và sửa 1 ký tự trên đó là đổi hẳn
# sang chữ khác: đo được 19/09/2026 "benh" khớp mờ sang "ben" (Công viên BẾN
# Bạch Đằng) và "binh" (Công viên Lãnh BINH Thăng), nên "bệnh viện" trả công
# viên. Lỗi gõ phổ biến nhất (thiếu/sai dấu) đã được analyzer vi_folded lo,
# không cần fuzzy.
_FUZZINESS = "AUTO:5,8"

# Danh từ đầu chung chung: "quán phở" và "phở" cùng tìm một thứ. Chỉ được bỏ
# khỏi phần BẮT BUỘC khi bỏ đi không đổi loại địa điểm mà truy vấn nhắm tới
# (`categories_for_query`): "quán cà phê" -> "cà phê" vẫn là cafe nên bỏ được,
# còn "quán bar" -> "bar", "tiệm bánh" -> "bánh" thì mất loại nên giữ. Cùng
# danh sách với `voice._GENERIC_HEADS` — tầng giọng nói đã bỏ sẵn trước khi tới
# đây, còn ô tìm kiếm thì chưa.
_GENERIC_HEADS = (("cửa", "hàng"), ("cửa", "tiệm"), ("quán",), ("tiệm",))

# Năm dấu thanh (dạng combining). Dấu mũ/móc/trăng (â, ơ, ă...) KHÔNG nằm ở
# đây: chúng là một phần của nguyên âm, không phải thanh điệu.
_TONE_MARKS = "\u0300\u0301\u0309\u0303\u0323"
# Vần mở "oa", "oe", "uy" có HAI kiểu đặt dấu cùng hợp lệ: "hoà"/"hòa",
# "khoẻ"/"khỏe", "thuỷ"/"thủy". Đếm trong DB 2026-10-08: 328 tên kiểu cũ, 1279
# tên kiểu mới — người gõ kiểu này phải khớp được tên viết kiểu kia. "qu" là
# phụ âm đầu ("quả", "quý") nên không thuộc vần này.
_TWO_STYLE_RHYME = re.compile(r"(?<!q)(o[ae]|uy)$")


def _geo_filter(latitude: float, longitude: float, radius_m: int) -> dict[str, Any]:
    return {
        "geo_distance": {
            "distance": f"{radius_m}m",
            "location": {"lat": latitude, "lon": longitude},
        }
    }


def _category_filter(category: str | None) -> list[dict[str, Any]]:
    # Lọc theo category_label.raw (nhãn hiển thị, sub-field keyword), không
    # phải "category" (mã OSM chi tiết): nhiều mã chung một nhãn tiếng Việt,
    # và người dùng chọn theo nhãn trên chip lọc — xem ranking.fetch_categories.
    return [{"term": {"category_label.raw": category}}] if category else []



def _min_should_match() -> dict[str, Any]:
    """``minimum_should_match`` cho hai clause văn bản, hoặc rỗng khi tắt.

    Đọc `settings` mỗi lần gọi (không cache ở cấp module) để bật/tắt được
    trong CÙNG một tiến trình lúc đo A/B — nếu đọc lúc import thì phải dựng
    lại image cho từng giá trị, và khi đó hai lượt đo không còn chung tập dữ
    liệu trending/recency nữa.
    """
    value = (settings.search_text_min_should_match or "").strip()
    return {"minimum_should_match": value} if value else {}

# Các trường văn bản mà kênh BM25 so khớp, lấy kèm trong hit để
# ``retrieval`` loại được hit chỉ khớp nhờ gộp nhầm dấu ("phở" -> "Phố") —
# xem ``poi_features.matches_query_marks``.
BM25_TEXT_FIELDS = ("name", "category_label", "search_keywords", "tags", "brand", "description")


def query_tokens(query_text: str) -> list[str]:
    """Tách truy vấn thành token chữ thường, GIỮ dấu, chuẩn NFC.

    Xấp xỉ tokenizer ``standard`` của OpenSearch đủ cho tiếng Việt (âm tiết
    cách nhau bằng dấu cách). NFC trước khi tách: ở dạng NFD dấu thanh là ký
    tự combining, ``\\w`` không coi là chữ nên "phở" bị cắt làm đôi.
    """
    return re.findall(r"\w+", unicodedata.normalize("NFC", query_text).lower())


def _has_marks(token: str) -> bool:
    return normalize_text(token) != token


def _tone_placements(token: str) -> set[str]:
    """Cả hai kiểu đặt dấu của vần mở oa/oe/uy ("hoà" -> {"hoà", "hòa"})."""
    decomposed = unicodedata.normalize("NFD", token)
    tones = [char for char in decomposed if char in _TONE_MARKS]
    if len(tones) != 1:
        return {token}
    bare = unicodedata.normalize("NFC", decomposed.replace(tones[0], ""))
    match = _TWO_STYLE_RHYME.search(bare)
    if not match:
        return {token}
    stem = bare[: match.start()]
    first, second = match.group(1)
    return {
        unicodedata.normalize("NFC", stem + first + tones[0] + second),
        unicodedata.normalize("NFC", stem + first + second + tones[0]),
    }


def _strict_alternatives(token: str) -> list[str]:
    """Các cách viết trong chỉ mục được coi là CÙNG từ với ``token`` có dấu.

    Đúng dấu (cả hai kiểu đặt dấu, cả dạng NFD — 59 tên trong DB lưu NFD), hoặc
    KHÔNG dấu: tên OSM kiểu "Pho Hien" vẫn là phở. Sai dấu ("phố", "Phòng"...)
    thì không.
    """
    forms = _tone_placements(token)
    forms |= {unicodedata.normalize("NFD", form) for form in forms}
    forms.add(normalize_text(token))
    return sorted(forms)


def _generic_head_positions(tokens: list[str]) -> set[int]:
    """Vị trí các danh từ đầu chung chung bỏ được khỏi phần bắt buộc.

    Gõ có dấu thì so có dấu ("quận" không phải "quán"); gõ không dấu thì so
    không dấu ("quan pho"). Phải còn từ phía sau, và từ ngay sau không phải số:
    "quan 1" là Quận 1, không phải "quán" + "1".
    """
    positions: set[int] = set()
    query = " ".join(tokens)
    categories = categories_for_query(query)
    for head in _GENERIC_HEADS:
        folded_head = tuple(normalize_text(word) for word in head)
        size = len(head)
        for start in range(len(tokens) - size):
            window = tuple(tokens[start : start + size])
            if window != head and window != folded_head:
                continue
            if tokens[start + size].isdigit():
                continue
            rest = tokens[:start] + tokens[start + size :]
            if categories_for_query(" ".join(rest)) == categories:
                positions.update(range(start, start + size))
    return positions


def _token_gate(query_text: str) -> dict[str, Any] | None:
    """Điều kiện LỌT vào kênh BM25, xét từng token của truy vấn.

    Hai lỗi đo được 2026-10-08 với "quán phở" (Phở Nhà Mình 174 m không có
    mặt, thay vào là "Nhà Hát Thành Phố", "Phố Nhật Quán", "Phòng Quản lý..."):

    1. ``vi_folded`` gộp "phở"/"phố" thành ``pho`` và "quán"/"quản" thành
       ``quan``, còn ``.strict`` chỉ CỘNG điểm — khớp sai dấu không bao giờ bị
       loại. Nên token GÕ CÓ DẤU ở đây chỉ được thoả bằng ``.strict`` với
       đúng dấu hoặc không dấu (`_strict_alternatives`). Token không dấu vẫn
       khớp mọi dấu qua ``vi_folded`` như cũ — người dùng gõ không dấu là
       chuyện thường, không phải lỗi.
    2. ``minimum_should_match`` "2<70%" đòi đủ cả "quán" lẫn "phở", loại mất
       mọi quán tên "Phở ..." không có chữ "Quán". Danh từ đầu chung chung
       (`_generic_head_positions`) giờ chỉ còn cộng điểm, không bắt buộc.

    ``minimum_should_match`` áp lên các TOKEN BẮT BUỘC ở đây chứ không còn
    trên từng multi_match: multi_match ``best_fields`` đòi các token khớp
    trong CÙNG một trường, nên không có chỗ để đặt "token này phải đúng dấu".
    Bỏ ``name.prefix``: edge-ngram cho "pho" khớp vào "Phòng" — gõ dở đã có
    endpoint gợi ý riêng (``/pois/suggest``).

    Trả ``None`` khi truy vấn không có token chữ/số nào.
    """
    tokens = query_tokens(query_text)
    if not tokens:
        return None
    optional = _generic_head_positions(tokens)
    required = [token for index, token in enumerate(tokens) if index not in optional]
    clauses: list[dict[str, Any]] = []
    for token in required:
        if _has_marks(token):
            clauses.append(
                {
                    "multi_match": {
                        "query": " ".join(_strict_alternatives(token)),
                        "fields": [field.split("^")[0] for field in _STRICT_FIELDS],
                        "operator": "or",
                    }
                }
            )
        else:
            clauses.append(
                {
                    "multi_match": {
                        "query": token,
                        "fields": [
                            field.split("^")[0]
                            for field in _FOLDED_FIELDS
                            if not field.startswith("name.prefix")
                        ],
                        "fuzziness": _FUZZINESS,
                    }
                }
            )
    return {
        "bool": {
            "should": clauses,
            "minimum_should_match": _min_should_match().get("minimum_should_match", 1),
        }
    }


def bm25_body(
    query_text: str,
    latitude: float,
    longitude: float,
    radius_m: int,
    category: str | None,
    size: int,
) -> dict[str, Any]:
    """Kênh văn bản: multi_match có fuzzy (chịu lỗi chính tả), khớp không dấu
    nhờ analyzer ``vi_folded``, giới hạn theo bán kính và category.

    ``.strict`` (analyzer ``vi_strict``, giữ dấu thanh điệu) cộng thêm điểm
    khi khớp CHÍNH XÁC dấu thanh — đo được thật (Phase 10, 2026-09-12):
    asciifolding gộp nhầm "viện"/"viên" và "tấm"/"Tám" về cùng token, khiến
    "Công viên..." thắng "Bệnh viện..." cho truy vấn "bệnh viện".

    Tách thành HAI multi_match riêng trong ``should`` thay vì gộp chung một
    multi_match: field ``.strict`` KHÔNG được đặt ``fuzziness`` — nếu gộp
    chung, "AUTO" cho phép khoảng cách sửa 1 ký tự, và "viện" với "viên" chỉ
    khác nhau đúng 1 ký tự (ệ/ê) nên fuzzy sẽ lại khớp mờ, xoá sạch tác dụng
    phân biệt dấu thanh mà field này tồn tại để giải quyết. Hai clause cộng
    điểm (không phải lấy max) nên candidate khớp cả hai được thưởng thêm,
    còn candidate chỉ khớp nhờ fold vẫn giữ nguyên điểm cũ.

    Hai clause đó chỉ CHẤM ĐIỂM. Ai được LỌT vào kênh do `_token_gate` quyết
    định (đặt trong ``filter`` nên không đổi điểm): token gõ có dấu phải khớp
    đúng dấu (hoặc tên không dấu), danh từ đầu chung chung như "quán" không
    bắt buộc — đo 2026-10-08, chỉ cộng điểm thì "quán phở" vẫn trả "Nhà Hát
    Thành Phố" và bỏ sót "Phở Nhà Mình" cách 174 m.

    ``search_keywords`` là từ vựng tiếng Việt của LOẠI địa điểm, sinh lúc index
    từ ``poi_features.CATEGORY_KEYWORDS``. Boost đặt ngang ``category_label``
    (^2 fold, ^3 strict) vì cùng bản chất: cả hai nói POI này THUỘC LOẠI nào,
    không phải nó TÊN gì — "rạp chiếu phim" không được thắng một POI thật sự
    mang chữ đó trong tên (``name^3``/``name.strict^5``)."""
    filters = _category_filter(category) + [_geo_filter(latitude, longitude, radius_m)]
    text_match: dict[str, Any] = {
        "minimum_should_match": 1,
        "should": [
            {
                "multi_match": {
                    "query": query_text,
                    "type": "best_fields",
                    "fields": list(_FOLDED_FIELDS),
                    "fuzziness": _FUZZINESS,
                    "operator": "or",
                }
            },
            {
                "multi_match": {
                    "query": query_text,
                    "type": "best_fields",
                    "fields": list(_STRICT_FIELDS),
                    "operator": "or",
                }
            },
            # Thưởng khi tên chứa NGUYÊN cụm theo đúng thứ tự. Cần từ khi
            # "quán" thôi bắt buộc (`_token_gate`): gõ không dấu "quan pho"
            # thì "Quán Phở 32" và "cơ quan ... Thành phố" khớp cùng hai token,
            # chỉ thứ tự liền nhau mới tách được — đo 2026-10-08, thiếu clause
            # này "Quán Phở 32" rơi khỏi top 10.
            {"match_phrase": {"name": {"query": query_text, "boost": 2}}},
        ],
    }
    gate = _token_gate(query_text)
    if gate is not None:
        text_match["filter"] = [gate]
    return {
        "size": size,
        "_source": ["poi_id", *BM25_TEXT_FIELDS],
        "query": {
            "bool": {
                "must": [{"bool": text_match}],
                "filter": filters,
            }
        },
    }


def geo_body(
    latitude: float,
    longitude: float,
    radius_m: int,
    category: str | None,
    size: int,
) -> dict[str, Any]:
    """Kênh không gian thuần: mọi POI trong bán kính, gần nhất trước. Bảo đảm
    recall địa lý ngay cả khi truy vấn văn bản rỗng."""
    filters = _category_filter(category) + [_geo_filter(latitude, longitude, radius_m)]
    return {
        "size": size,
        "_source": ["poi_id"],
        "query": {"bool": {"filter": filters}},
        "sort": [
            {
                "_geo_distance": {
                    "location": {"lat": latitude, "lon": longitude},
                    "order": "asc",
                    "unit": "m",
                }
            }
        ],
    }


def h3_body(
    cells: tuple[str, ...] | list[str],
    field: str,
    latitude: float,
    longitude: float,
    category: str | None,
    size: int,
) -> dict[str, Any]:
    """Kênh không gian bằng **vành hexagon H3**: lọc bằng ``terms`` trên mã ô.

    Lọc là một phép tra chỉ mục đảo trên trường keyword, không phải phép tính
    khoảng cách trên từng document như ``geo_body``. Sắp xếp vẫn theo khoảng
    cách thật để ô gần tâm lên trước — H3 quyết định *ai được vào*, toạ độ
    quyết định *ai đứng trên*.

    Vành phủ trùm hình tròn nên tập trả về rộng hơn bán kính một chút;
    ``enrichment.hydrate_candidates`` cắt lại bằng ``ST_DWithin``.
    """
    filters = _category_filter(category) + [{"terms": {field: list(cells)}}]
    return {
        "size": size,
        "_source": ["poi_id"],
        "query": {"bool": {"filter": filters}},
        "sort": [
            {
                "_geo_distance": {
                    "location": {"lat": latitude, "lon": longitude},
                    "order": "asc",
                    "unit": "m",
                }
            }
        ],
    }


def vector_body(
    embedding: list[float],
    latitude: float,
    longitude: float,
    radius_m: int,
    category: str | None,
    size: int,
) -> dict[str, Any]:
    """Kênh ngữ nghĩa: k-NN trên embedding, lọc theo bán kính/category. Dùng
    ``knn`` có filter (OpenSearch >= 2.4, engine lucene)."""
    filters = _category_filter(category) + [_geo_filter(latitude, longitude, radius_m)]
    return {
        "size": size,
        "_source": ["poi_id"],
        "query": {
            "knn": {
                "embedding": {
                    "vector": embedding,
                    "k": size,
                    "filter": {"bool": {"filter": filters}},
                }
            }
        },
    }


def extract_ranked_hits(response: dict[str, Any]) -> list[tuple[str, float]]:
    """Lấy (poi_id, _score) theo thứ tự hit từ response OpenSearch.

    Điểm thô cần thiết cho kênh BM25: sau RRF chỉ còn thứ hạng, mà thứ hạng
    không phân biệt được "khớp văn bản rất tốt" với "khớp tạm được nhưng là cái
    tốt nhất trong một tập kém". Tín hiệu ``text`` của bộ xếp hạng cần mức khớp
    thật, không phải vị trí.
    """
    hits = (response or {}).get("hits", {}).get("hits", [])
    ranked: list[tuple[str, float]] = []
    for hit in hits:
        source = hit.get("_source") or {}
        poi_id = source.get("poi_id") or hit.get("_id")
        if poi_id is None:
            continue
        try:
            score = float(hit.get("_score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        ranked.append((str(poi_id), score))
    return ranked


def extract_ranked_ids(response: dict[str, Any]) -> list[str]:
    """Lấy danh sách poi_id theo thứ tự hit từ response OpenSearch."""
    return [poi_id for poi_id, _score in extract_ranked_hits(response)]

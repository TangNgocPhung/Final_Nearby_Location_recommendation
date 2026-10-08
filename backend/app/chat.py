"""Chatbot AI (Phase 14) — LLM hiểu ý định + diễn giải kết quả, KHÔNG tự chọn POI.

Nguyên tắc cốt lõi (đã thống nhất với người dùng): LLM chỉ làm ba việc —
(1) trích tham số tìm kiếm có cấu trúc từ câu hỏi tự nhiên, (2) hỏi lại khi
thiếu thông tin, (3) diễn giải bằng lời kết quả THẬT do pipeline
BM25+Vector+Geo/H3+RRF+Gate+LTR trả về. Danh sách POI luôn đến từ
``ranking.rank_pois_detailed`` — LLM không bao giờ tự bịa hay tự xếp hạng POI.

Dùng chung Ollama local với kênh embedding (``app/embeddings.py``) nhưng khác
endpoint (``/api/chat`` thay vì ``/api/embed``) và khác model
(``settings.ollama_chat_model``). Cùng triết lý graceful-degradation: Ollama
chết thì trả lời dự phòng bằng tiếng Việt, không bao giờ raise 500.

Lịch sử hội thoại lưu Redis (giống `geo_cache`) theo `session_id`, TTL ngắn —
đây là ngữ cảnh trò chuyện tạm thời, không phải dữ liệu cần bền vững.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any

import psycopg
from psycopg.rows import dict_row

from . import geo_cache
from .config import settings
from .languages import ENGLISH_NAMES, LANGUAGE_CODES
from .poi_detail import fetch_knowledge_map
from .poi_features import categories_for_query, normalize_text

logger = logging.getLogger("nearby-chat")

# llama3.2:3b chạy CPU trên máy dev: đo được thật (2026-09-20) ~7-8 token/giây.
# Bước diễn giải sinh nhiều chữ hơn bước trích ý định nên cần timeout dài hơn
# — và từ khi có `knowledge` (Phase 15), prompt còn phình thêm vì kèm cả
# historicalEvents/interestingFacts, đo được cần hơn 60s cho POI có nhiều dữ
# liệu (vd Dinh Độc Lập: 2 sự kiện + 2 fact có nguồn).
REQUEST_TIMEOUT_SECONDS = 90.0
HISTORY_KEY_PREFIX = "nearby:chat:history"
HISTORY_TTL_SECONDS = 30 * 60
HISTORY_MAX_TURNS = 6  # 6 cặp user/assistant gần nhất — đủ ngữ cảnh, không phình prompt
CHAT_RESULT_CARDS = 5  # số thẻ địa điểm khung chat hiện (MAX_RESULT_CARDS ở chat-widget.tsx)

_EXPLAIN_SYSTEM_PROMPT = """Bạn là trợ lý của app tìm địa điểm gần đây tên Nearby.
Bạn sẽ nhận được câu hỏi của người dùng và một danh sách POI (địa điểm) THẬT do hệ thống tìm kiếm trả về.
Nhiệm vụ: viết một đoạn trả lời ngắn gọn, tự nhiên bằng tiếng Việt, giới thiệu các kết quả này.

Quy tắc bắt buộc:
- CHỈ nhắc tới POI có trong danh sách được cung cấp. TUYỆT ĐỐI không bịa thêm địa điểm nào khác.
- Không tự đánh giá/xếp hạng lại — giữ đúng thứ tự đã cho, có thể nêu 3-5 kết quả đầu.
- Nếu danh sách rỗng, xin lỗi và gợi ý người dùng thử từ khoá khác hoặc mở rộng bán kính.
- Trả lời ngắn (2-5 câu), giọng thân thiện, không markdown.
- CHỈ dùng tiếng Việt, không chèn từ tiếng Anh (kể cả từ đơn giản như "today").

Về thời tiết (nếu có trong dữ liệu): hệ thống ĐÃ dùng thời tiết để ưu tiên kết
quả (trời mưa thì ưu tiên chỗ trong nhà) — bạn chỉ cần NHẮC LẠI ngắn gọn lý do
đó nếu phù hợp câu hỏi, không cần tự suy luận thêm.

Về độ đông (nếu có trong dữ liệu, field "busyness"): đây là ƯỚC TÍNH từ lượt
tương tác gần đây trên chính app Nearby, KHÔNG PHẢI dữ liệu real-time chính
xác. Bắt buộc:
- CHỈ nhắc độ đông khi "estimated" là true. Không có nghĩa là "estimated"
  false thì POI đó vắng — nghĩa là CHƯA ĐỦ DỮ LIỆU, đừng nói gì về độ đông của
  POI đó cả.
- Luôn dùng từ "ước tính" khi nhắc tới, KHÔNG được nói chắc như đang đo thời
  gian thực (vd nói "có vẻ đang khá đông" chứ không nói "đang đông 85%").

Về kiến thức/lịch sử (nếu có trong dữ liệu, field "knowledge" của một POI —
gồm intro/specialty/historicalContext/historicalEvents/interestingFacts):
đây là nội dung ĐÃ ĐƯỢC BIÊN SOẠN VÀ KIỂM CHỨNG SẴN, không phải thứ bạn tự
nhớ ra. Quy tắc TUYỆT ĐỐI, vi phạm là lỗi nghiêm trọng nhất của cả hệ thống:
- CHỈ được diễn đạt lại (viết tự nhiên hơn) đúng những gì có trong "knowledge"
  của POI đó. TUYỆT ĐỐI KHÔNG được tự thêm bất kỳ sự kiện, ngày tháng, số
  liệu, tên người/kiến trúc sư, hay chi tiết lịch sử nào KHÔNG có trong dữ
  liệu được cung cấp — kể cả khi bạn "biết" hoặc "nhớ" điều đó từ nơi khác.
  Đây là quy tắc chống bịa (hallucination), vì mọi claim lịch sử trong
  "knowledge" đã được đối chiếu nguồn thật, còn kiến thức nội tại của bạn thì
  KHÔNG kiểm chứng được và có thể sai.
- POI nào KHÔNG có field "knowledge" (hoặc "knowledge" là null) thì ĐỪNG kể
  bất kỳ điều gì về lịch sử/nguồn gốc của POI đó — chỉ nói về tên/loại/
  khoảng cách/rating như bình thường.
- Nếu "knowledge.verified" là false, thêm ý "chưa được kiểm chứng đầy đủ"
  khi nhắc tới nội dung đó.
"""

# AI Thuyết minh POI (Phase 16, đa ngôn ngữ ở Phase 16.1) — LỐI VÀO ĐỘC LẬP
# với chat: người dùng chỉ CHỌN một địa điểm, không cần gõ câu hỏi. Dùng cho
# nút "Nghe thuyết minh" trên panel chi tiết POI — xem `generate_poi_narration`
# và `GET /api/v1/pois/{poi_id}/narration`.
#
# Nguồn sự thật (`poi_knowledge`) CHỈ có một bản, bằng tiếng Việt — KHÔNG nhân
# bản theo ngôn ngữ. Mỗi ngôn ngữ chỉ khác nhau ở PROMPT yêu cầu LLM diễn đạt
# lại đúng tập fact đó bằng ngôn ngữ đích, dịch trực tiếp từ dữ liệu gốc —
# không dịch qua một bước narration tiếng Việt trung gian (tránh cộng dồn sai
# lệch qua hai lượt sinh văn bản).
#
# Từ 2026-09-25: mọi ngôn ngữ trong `app/languages.py` (134 ngôn ngữ). "vi" có
# prompt riêng; mọi ngôn ngữ khác dùng chung prompt tiếng Anh, chỉ thay tên
# ngôn ngữ đích. Chỉ `PREWARM_NARRATION_LANGUAGES` được tạo sẵn lúc khởi động
# (xem `app/narration.py`) — tạo sẵn cả 134 ngôn ngữ trên CPU mất nhiều giờ,
# nên các ngôn ngữ còn lại sinh ở lần chọn đầu tiên rồi cache.
NARRATION_LANGUAGES = LANGUAGE_CODES
PREWARM_NARRATION_LANGUAGES = ("vi", "en")
DEFAULT_NARRATION_LANGUAGE = "vi"

_NARRATION_SYSTEM_PROMPTS: dict[str, str] = {
    "vi": """Bạn là một hướng dẫn viên du lịch AI cho app tìm địa điểm gần đây tên Nearby.
Bạn sẽ nhận dữ liệu về MỘT địa điểm (tên, loại, và khối "knowledge" đã kiểm chứng, viết bằng tiếng Việt).
Nhiệm vụ: viết một đoạn thuyết minh tự nhiên, hấp dẫn BẰNG TIẾNG VIỆT, đọc to mất khoảng 30-60 giây (4-8 câu).

Quy tắc TUYỆT ĐỐI, vi phạm là lỗi nghiêm trọng nhất:
- CHỈ được diễn đạt lại đúng nội dung có trong "knowledge". TUYỆT ĐỐI KHÔNG
  được tự thêm bất kỳ sự kiện, ngày tháng, số liệu, tên người nào KHÔNG có
  trong dữ liệu được cung cấp — kể cả khi bạn "biết" hay "nhớ" điều đó từ nơi
  khác. Đây là quy tắc chống bịa lịch sử, quan trọng nhất trong toàn bộ nhiệm
  vụ này.
- Không mở đầu kiểu "Chào bạn" hay "Đây là đoạn thuyết minh về..." — vào
  thẳng nội dung, giọng văn như đang giới thiệu trực tiếp trước mặt người
  nghe.
- Viết thành đoạn văn liền mạch, tự nhiên như lời nói — không markdown,
  không gạch đầu dòng, không đánh số.
- KHÔNG tự thêm câu nào về việc thông tin "đã/chưa được kiểm chứng" — điều đó
  do hệ thống hiển thị riêng dựa trên field "verified", không phải việc của
  bạn để tự quyết định viết ra hay không.
""",
    "other": """You are an AI tour guide for a nearby-places app called Nearby.
You will receive data about ONE place (name, category, and a "knowledge" block that has already been fact-checked — written in Vietnamese).
Task: write a natural, engaging narration IN {language}, about 30-60 seconds to read aloud (4-8 sentences), by faithfully translating/paraphrasing the meaning of the Vietnamese "knowledge" data.

ABSOLUTE rules, breaking them is the most serious failure of this whole task:
- ONLY rephrase content that is present in "knowledge". You must NEVER add any
  event, date, number, or name that is NOT in the provided data — even if you
  "know" or "remember" it from elsewhere. This is the anti-hallucination rule,
  the single most important rule in this task.
- Do not open with "Hello" or "Here is a narration about..." — go straight
  into the content, as if speaking directly to a listener.
- Write as one flowing paragraph, natural spoken style — no markdown, no
  bullet points, no numbering.
- Do NOT add any sentence about whether the information is "verified" or
  not — that is decided and displayed by the system separately, not your job.
- Respond ONLY in {language}, even though the source data is in Vietnamese.
""",
}




def _narration_system_prompt(language: str) -> str:
    if language == "vi":
        return _NARRATION_SYSTEM_PROMPTS["vi"]
    # `.replace` thay vì `.format`: prompt có dấu ngoặc nhọn/nháy tuỳ ý.
    return _NARRATION_SYSTEM_PROMPTS["other"].replace("{language}", ENGLISH_NAMES[language])


_POI_MINIMAL_QUERY = """
    SELECT id::text AS id, name, category, category_label AS "categoryLabel"
    FROM pois WHERE id = %(poi_id)s
"""


def generate_poi_narration(poi_id: str, language: str = DEFAULT_NARRATION_LANGUAGE) -> dict[str, Any]:
    """Thuyết minh CHỦ ĐỘNG cho một POI, bằng ``language`` (``"vi"``/``"en"``)
    — khác `explain_results` (chạy SAU một lượt hỏi trong chat): đây là lối
    vào riêng cho nút "Nghe thuyết minh" trên panel chi tiết, người dùng
    không cần gõ gì.

    Chỉ trả narration khi POI có ``poi_knowledge`` — không có thì trả
    ``available: False`` thay vì để LLM tự bịa một đoạn giới thiệu chung
    chung, không kiểm chứng được (đúng nguyên tắc đã áp dụng cho busyness:
    thiếu dữ liệu → nói rõ thiếu, không giả vờ có).
    """
    if language not in NARRATION_LANGUAGES:
        language = DEFAULT_NARRATION_LANGUAGE

    knowledge_map = fetch_knowledge_map([poi_id])
    knowledge = knowledge_map.get(poi_id)
    if knowledge is None:
        return {"available": False, "narration": None, "verified": None, "language": language}

    try:
        with psycopg.connect(settings.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(_POI_MINIMAL_QUERY, {"poi_id": poi_id})
                poi_row = cursor.fetchone()
    except psycopg.Error as error:
        logger.warning("Không tra được POI cho narration %s: %s", poi_id, error)
        poi_row = None
    if poi_row is None:
        return {"available": False, "narration": None, "verified": None, "language": language}

    narration = _ollama_chat(
        [
            {"role": "system", "content": _narration_system_prompt(language)},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "name": poi_row["name"],
                        "category": poi_row["categoryLabel"] or poi_row["category"],
                        "knowledge": knowledge,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        # Chữ Khmer/Thái/Ấn... tốn nhiều token hơn hẳn cho cùng một câu —
        # 260 token (đủ cho vi/en) cắt cụt đoạn văn giữa chừng.
        max_tokens=260 if language in ("vi", "en") else 700,
        model=settings.ollama_narration_model or None,
        think=False,
        num_ctx=settings.ollama_narration_num_ctx,
        timeout=settings.ollama_narration_timeout_seconds,
    )
    fallback = False
    if narration is None and language == "vi":
        # Ollama chết: vẫn trả nội dung THẬT thay vì báo lỗi trắng — ghép
        # thẳng các trường đã có sẵn trong knowledge, không qua LLM diễn đạt.
        # Kém mượt hơn văn xuôi nhưng không có gì trong đó là bịa.
        #
        # CHỈ áp dụng cho "vi": knowledge gốc đã là tiếng Việt, ghép trực tiếp
        # vẫn đúng ngôn ngữ. Với "en" thì không có đường lùi — không dịch
        # được nếu không qua LLM, nên coi như unavailable thay vì lặng lẽ trả
        # về text tiếng Việt dưới nhãn "narration tiếng Anh" (sai ngôn ngữ còn
        # tệ hơn không có gì).
        parts = [knowledge.get("intro"), knowledge.get("historicalContext")]
        parts += [fact["description"] for fact in knowledge.get("interestingFacts") or []]
        narration = " ".join(part for part in parts if part) or None
        fallback = narration is not None

    return {
        "available": narration is not None,
        "narration": narration,
        "verified": knowledge.get("verified"),
        "language": language,
        # True khi text là bản ghép thô do Ollama không trả lời — bên cache
        # (`app/narration.py`) KHÔNG lưu bản này, để lần sau còn thử lại LLM.
        "fallback": fallback,
    }


_NAMED_POI_QUERY = """
    SELECT p.id::text AS id, p.name, p.category, p.category_label AS "categoryLabel",
           p.rating::float8 AS rating,
           ST_Distance(
               p.location,
               ST_SetSRID(ST_Point(%(longitude)s, %(latitude)s), 4326)::geography
           ) AS "distanceMeters"
    FROM pois p
    -- CHỈ khớp trong tập POI đã có poi_knowledge (14 địa danh, xem migration
    -- 0021/0022) — KHÔNG khớp toàn bộ ~8891 POI. Đo được thật (2026-09-20):
    -- khớp toàn bộ DB làm câu hỏi chung chung "chỗ nào uống cà phê yên tĩnh
    -- gần đây" trùng nhầm vào một quán tên thật "Cà Phê Yên" (chỉ trùng chữ
    -- ngẫu nhiên), khiến chatbot giải thích một quán cụ thể sai hoàn toàn ý
    -- định thay vì tìm kiếm bình thường. Giới hạn vào tập curated nhỏ, tên
    -- đều là địa danh nổi tiếng/khác biệt, giảm hẳn rủi ro trùng ngẫu nhiên
    -- — đúng đối tượng mà tính năng này nhắm tới (câu hỏi về địa danh cụ
    -- thể), không phải khớp tên quán ăn/cà phê đại trà.
    JOIN poi_knowledge k ON k.poi_id = p.id
    WHERE p.normalized_name IS NOT NULL
      AND length(p.normalized_name) >= %(min_length)s
      AND position(p.normalized_name IN %(normalized_message)s) > 0
    ORDER BY length(p.normalized_name) DESC
    LIMIT 1
"""

# Dưới ngưỡng này thì không khớp — tên POI ngắn gần như chắc chắn khớp NHẦM
# vào một câu bất kỳ có chứa từ đó, không phải người dùng đang hỏi về đúng
# POI đó.
_MIN_NAMED_POI_LENGTH = 6


def find_named_poi(user_message: str, latitude: float, longitude: float) -> dict[str, Any] | None:
    """Khớp tên POI TRỰC TIẾP từ dữ liệu thật trong Postgres — KHÔNG dùng LLM
    để suy đoán/nhận diện địa danh. Chỉ khớp trong tập ĐÃ CÓ ``poi_knowledge``
    (14 địa danh, xem migration 0021/0022) — KHÔNG khớp toàn bộ ~8891 POI, xem
    lý do ở ``_NAMED_POI_QUERY``.

    Lý do tách bước này ra khỏi ``extract_search_intent``: đo được thật
    (2026-09-20) — khi câu hỏi nêu tên một địa danh cụ thể (vd "Dinh Độc Lập
    có gì đặc biệt"), llama3.2:3b có xu hướng "nhận ra" cái tên và literally
    trả lời luôn bằng văn xuôi kèm sự kiện lịch sử BỊA, bỏ qua hẳn yêu cầu
    JSON. Match theo tên POI thật loại bỏ hoàn toàn phụ thuộc vào việc model
    có "biết" địa danh đó hay không — khớp được thì chắc chắn đúng POI thật,
    khớp trượt thì rơi về luồng search bình thường (`extract_search_intent`),
    không có gì bị mất.

    Chỉ lấy MỘT kết quả — tên dài nhất khớp được, để câu như "quán cà phê gần
    Dinh Độc Lập" ưu tiên khớp cả cụm dài hơn là khớp nhầm một từ ngắn.
    """
    normalized_message = normalize_text(user_message)
    if not normalized_message:
        return None
    try:
        with psycopg.connect(settings.database_url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    _NAMED_POI_QUERY,
                    {
                        "normalized_message": normalized_message,
                        "min_length": _MIN_NAMED_POI_LENGTH,
                        "latitude": latitude,
                        "longitude": longitude,
                    },
                )
                return cursor.fetchone()
    except psycopg.Error as error:
        logger.warning("Tra POI theo tên thất bại, rơi về luồng search thường: %s", error)
        return None


def _history_key(session_id: str) -> str:
    return f"{HISTORY_KEY_PREFIX}:{session_id}"


def get_history(session_id: str) -> list[dict[str, str]]:
    client = geo_cache.get_client()
    if client is None:
        return []
    try:
        raw = client.get(_history_key(session_id))
    except Exception:  # noqa: BLE001 - Redis lỗi thì coi như hội thoại mới
        return []
    if not raw:
        return []
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []


def clear_history(session_id: str) -> None:
    """Nút "Cuộc trò chuyện mới": xoá ngữ cảnh để câu hỏi sau không bị hiểu
    như câu hỏi nối tiếp cuộc trò chuyện cũ."""
    client = geo_cache.get_client()
    if client is None:
        return
    try:
        client.delete(_history_key(session_id))
    except Exception:  # noqa: BLE001 - xoá hụt thì lịch sử tự hết hạn sau HISTORY_TTL_SECONDS
        logger.warning("Không xoá được lịch sử chat cho session %s", session_id)


def _append_history(session_id: str, user_message: str, assistant_reply: str) -> None:
    client = geo_cache.get_client()
    if client is None:
        return
    history = get_history(session_id)
    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": assistant_reply})
    history = history[-(HISTORY_MAX_TURNS * 2) :]
    try:
        client.set(_history_key(session_id), json.dumps(history, ensure_ascii=False), ex=HISTORY_TTL_SECONDS)
    except Exception:  # noqa: BLE001 - mất lịch sử không được làm hỏng câu trả lời đã có
        logger.warning("Không lưu được lịch sử chat cho session %s", session_id)


def _ollama_chat(
    messages: list[dict[str, str]],
    *,
    deterministic: bool = False,
    max_tokens: int | None = None,
    model: str | None = None,
    think: bool | None = None,
    num_ctx: int | None = None,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> str | None:
    """Gọi Ollama /api/chat. Trả ``None`` nếu Ollama không tới được/lỗi — bên
    gọi phải coi đó là "chatbot tạm không dùng được", không phải lỗi cứng.

    KHÔNG dùng ``format: "json"`` của Ollama: đo được thật (2026-09-20) — chế
    độ JSON ép ngữ pháp (grammar-constrained decoding) làm hỏng dấu tiếng Việt
    trên llama3.2:3b, trả về chuỗi rác dù prompt yêu cầu JSON qua system prompt
    vẫn ra JSON hợp lệ, có dấu, ổn định. Bên gọi JSON tự trích bằng
    ``_extract_json_object``.

    ``model``/``think``/``num_ctx`` dùng cho thuyết minh và dịch (Qwen3.5, xem
    ``settings.ollama_narration_model``): Qwen3.5 là model có "thinking" —
    không tắt thì nó sinh cả đoạn suy luận trước câu trả lời, chậm gấp nhiều
    lần trên CPU. ``num_ctx`` phải đặt rõ: context mặc định của Qwen3.5 rất
    lớn, Ollama cấp phát KV cache theo đó và hết RAM ngay lúc nạp model (đo
    được thật 2026-09-25 trên máy dev 15 GB).
    """
    if not settings.ollama_url:
        return None
    body: dict[str, Any] = {
        "model": model or settings.ollama_chat_model,
        "messages": messages,
        "stream": False,
    }
    if model is None:
        body["keep_alive"] = settings.ollama_chat_keep_alive
    options: dict[str, Any] = {}
    if deterministic:
        # temperature=0: đo được thật — llama3.2:3b lệch dấu tiếng Việt ngẫu
        # nhiên giữa các lần gọi giống hệt nhau (sampling noise), tắt sampling
        # cho bước trích JSON giảm hẳn lỗi này.
        options["temperature"] = 0
    if max_tokens is not None:
        # Chặn model rambling sinh quá dài — trên CPU ~7-8 token/giây, câu trả
        # lời dài kéo cả request vượt REQUEST_TIMEOUT_SECONDS.
        options["num_predict"] = max_tokens
    if num_ctx is not None:
        options["num_ctx"] = num_ctx
    if options:
        body["options"] = options
    if think is not None:
        body["think"] = think
    payload = json.dumps(body).encode("utf-8")
    url = f"{settings.ollama_url.rstrip('/')}/api/chat"
    request = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data: dict[str, Any] = json.load(response)
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as error:
        logger.warning("Gọi Ollama chat thất bại: %s", error)
        return None
    content = data.get("message", {}).get("content")
    return content if isinstance(content, str) and content.strip() else None


def _ollama_chat_stream(messages: list[dict[str, str]], *, max_tokens: int) -> Iterator[str]:
    """Như ``_ollama_chat`` (model chat) nhưng ``stream: true`` — trả từng mẩu
    chữ ngay khi model sinh ra. Trên CPU ~7-8 token/giây, đoạn diễn giải
    220 token mất ~30s mới xong; stream cho người dùng thấy chữ đầu tiên sau
    vài giây thay vì nhìn spinner suốt nửa phút.

    Lỗi (Ollama tắt, timeout giữa hai mẩu) thì dừng im lặng — bên gọi tự
    nhận ra khi chưa nhận được chữ nào và trả lời dự phòng. ``timeout`` của
    ``urlopen`` áp cho TỪNG lần đọc socket, không phải cả request, nên câu dài
    không bị cắt ngang miễn là model vẫn đang sinh chữ đều.
    """
    if not settings.ollama_url:
        return
    body = {
        "model": settings.ollama_chat_model,
        "messages": messages,
        "stream": True,
        "keep_alive": settings.ollama_chat_keep_alive,
        "options": {"num_predict": max_tokens},
    }
    request = urllib.request.Request(
        f"{settings.ollama_url.rstrip('/')}/api/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            for line in response:
                if not line.strip():
                    continue
                chunk = json.loads(line)
                piece = chunk.get("message", {}).get("content")
                if isinstance(piece, str) and piece:
                    yield piece
                if chunk.get("done"):
                    return
    except (urllib.error.URLError, OSError, ValueError) as error:
        logger.warning("Gọi Ollama chat (stream) thất bại: %s", error)


def warm_up_chat_model() -> None:
    """Nạp sẵn model chat vào RAM: Ollama nhận ``messages`` rỗng là chỉ nạp
    model rồi trả về ngay. Không có bước này thì lượt chat đầu tiên sau khi
    khởi động phải chờ thêm thời gian nạp model."""
    if not settings.ollama_url:
        return
    body = {
        "model": settings.ollama_chat_model,
        "messages": [],
        "keep_alive": settings.ollama_chat_keep_alive,
    }
    request = urllib.request.Request(
        f"{settings.ollama_url.rstrip('/')}/api/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            response.read()
    except (urllib.error.URLError, OSError) as error:
        logger.info("Không nạp sẵn được model chat (Ollama chưa sẵn sàng?): %s", error)


def start_warmup() -> None:
    threading.Thread(target=warm_up_chat_model, name="chat-warmup", daemon=True).start()


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Cắt lấy object JSON đầu tiên trong text tự do (model hay kèm thêm chữ
    dù đã dặn không, hoặc bọc trong ```json ... ```).

    llama3.2:3b thỉnh thoảng phát token dừng (EOS) ngay sau giá trị chuỗi
    cuối, thiếu nốt 1-2 ký tự đóng ``"}`` — đo được thật (2026-09-20), không
    phải giới hạn ``num_predict``. Thử vá vài hậu tố đóng phổ biến trước khi
    bỏ cuộc, thay vì coi cả câu trả lời là hỏng.
    """
    start = text.find("{")
    if start == -1:
        return None
    candidate = text[start:]
    end = candidate.rfind("}")
    if end != -1:
        try:
            parsed = json.loads(candidate[: end + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    for suffix in ('"}', "}", '""}', '"}}'):
        try:
            parsed = json.loads(candidate + suffix)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


_FAST_SEARCH_MARKERS = ("gan day", "gan toi", "quanh day", "quanh toi", "o dau gan")
_FAST_SEARCH_PREFIXES = ("tim ", "quan ", "nha hang ", "ca phe ", "cafe ", "tiem ")


def quick_search_intent(user_message: str) -> dict[str, Any] | None:
    """Nhận diện truy vấn tìm địa điểm rõ ràng mà không cần chờ LLM."""
    normalized = normalize_text(user_message).strip()
    if not normalized:
        return None
    if not (
        any(marker in normalized for marker in _FAST_SEARCH_MARKERS)
        or normalized.startswith(_FAST_SEARCH_PREFIXES)
    ):
        return None

    category = None
    category_terms = {
        "restaurant": ("quan an", "nha hang", "an sang", "an trua", "an toi", "an dem"),
        "cafe": ("ca phe", "cafe", "tra sua"),
        "hospital": ("benh vien",),
        "pharmacy": ("nha thuoc", "hieu thuoc"),
        "park": ("cong vien",),
    }
    for candidate, terms in category_terms.items():
        if any(term in normalized for term in terms):
            category = candidate
            break
    return {
        "search_query": user_message.strip(),
        "category": category,
        "radius_m": None,
        "needs_clarification": False,
        "clarifying_question": None,
    }


def summarize_results_fast(session_id: str, user_message: str, results: list[dict[str, Any]]) -> str:
    """Phản hồi tức thì cho truy vấn rõ ràng; các thẻ POI mang phần chi tiết."""
    if not results:
        reply = "Mình chưa tìm thấy địa điểm phù hợp gần bạn. Hãy thử đổi từ khóa hoặc mở rộng bán kính nhé."
    else:
        # Không nêu len(results): đó là trần truy vấn (20), không phải số địa
        # điểm có thật, và khung chat chỉ hiện CHAT_RESULT_CARDS thẻ. Kết quả
        # xếp theo độ phù hợp nên không gọi là "gần nhất".
        shown = min(len(results), CHAT_RESULT_CARDS)
        names = ", ".join(poi.get("name", "") for poi in results[:3] if poi.get("name"))
        reply = f"Đây là {shown} chỗ hợp nhất gần bạn, nổi bật: {names}."
    _append_history(session_id, user_message, reply)
    return reply


# Câu chỉ chào hỏi/cảm ơn, không có nội dung tìm kiếm — hỏi lại thay vì chạy
# search với chữ "chào bạn". So trên chuỗi đã chuẩn hoá (không dấu).
_SMALL_TALK_REPLIES = {
    "chao": "Chào bạn! Bạn đang muốn tìm địa điểm gì gần đây?",
    "xin chao": "Chào bạn! Bạn đang muốn tìm địa điểm gì gần đây?",
    "hello": "Chào bạn! Bạn đang muốn tìm địa điểm gì gần đây?",
    "hi": "Chào bạn! Bạn đang muốn tìm địa điểm gì gần đây?",
    "alo": "Chào bạn! Bạn đang muốn tìm địa điểm gì gần đây?",
    "cam on": "Không có gì! Bạn cần tìm thêm địa điểm nào nữa không?",
    "thanks": "Không có gì! Bạn cần tìm thêm địa điểm nào nữa không?",
    "ok": "Bạn cần tìm thêm địa điểm nào nữa không?",
}
_SMALL_TALK_FILLERS = {"ban", "nhe", "nha", "a", "ad", "shop", "bot", "nhieu", "you", "there"}
# Đọc trên chuỗi GỐC đã lower(), không phải `normalize_text`: chuẩn hoá biến
# "1,5km" thành "1 5km" và mất phần thập phân.
_RADIUS_RE = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*(km|mét|met|m)\b")
_MIN_RADIUS_M = 100
_MAX_RADIUS_M = 50_000


def _small_talk_reply(normalized: str) -> str | None:
    words = normalized.split()
    for size in (2, 1):
        head = " ".join(words[:size])
        if head in _SMALL_TALK_REPLIES and all(word in _SMALL_TALK_FILLERS for word in words[size:]):
            return _SMALL_TALK_REPLIES[head]
    return None


def _radius_from_message(user_message: str) -> int | None:
    match = _RADIUS_RE.search(user_message.lower())
    if match is None:
        return None
    value = float(match.group(1).replace(",", "."))
    meters = value * 1000 if match.group(2) == "km" else value
    return int(min(max(meters, _MIN_RADIUS_M), _MAX_RADIUS_M))


def rule_based_intent(user_message: str) -> dict[str, Any]:
    """Trích tham số tìm kiếm bằng luật, KHÔNG gọi LLM.

    Trước đây bước này gọi llama3.2:3b để ra JSON — đo được thật (2026-10-08):
    tốn 20-40s trên CPU chỉ để lấy ra ba thứ mà luật làm được tức thì và ổn
    định hơn: bán kính ("trong 1km"), category (``categories_for_query``, chỉ
    dùng để hiển thị — search luôn đọc nguyên văn câu gốc qua BM25/Vector),
    và câu chào hỏi cần hỏi lại. Model 3B còn hay đánh dấu nhầm câu tìm kiếm
    rõ ràng ("chỗ nào yên tĩnh để ngồi làm việc") là cần hỏi lại rồi chép
    nguyên câu người dùng làm câu hỏi lại.
    """
    normalized = normalize_text(user_message)
    small_talk = _small_talk_reply(normalized) if normalized else None
    if not normalized or small_talk:
        return {
            "search_query": "",
            "category": None,
            "radius_m": None,
            "needs_clarification": True,
            "clarifying_question": small_talk,
        }
    categories = categories_for_query(user_message)
    return {
        "search_query": user_message.strip(),
        "category": categories[0] if len(categories) == 1 else None,
        "radius_m": _radius_from_message(user_message),
        "needs_clarification": False,
        "clarifying_question": None,
    }


# Số POI đưa vào prompt diễn giải. Model chỉ được dặn nêu 3-5 kết quả đầu,
# đưa 10 POI (kèm knowledge) chỉ làm prompt dài thêm — trên CPU, đọc prompt
# cũng tốn thời gian đáng kể.
_EXPLAIN_TOP_N = 5


def _explain_messages(user_message: str, results: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Dựng prompt diễn giải từ danh sách POI THẬT.

    Thời tiết/độ đông đã được tính sẵn trong từng candidate bởi
    ``spatio_temporal.enrich_candidates`` (chạy TRƯỚC khi tới đây, bên trong
    ``rank_pois_detailed``) — hàm này chỉ ĐỌC lại để mô tả bằng lời, không tự
    tính toán gì thêm.
    """
    top_results = results[:_EXPLAIN_TOP_N]
    # Tra `poi_knowledge` cho ĐÚNG các POI đang định nhắc tới — không phải cả
    # 8891 POI. DB lỗi thì coi như không POI nào có knowledge (an toàn: LLM
    # đã được dặn không kể lịch sử khi thiếu field này), không được làm hỏng
    # cả câu trả lời chỉ vì tra thêm ngữ cảnh thất bại.
    try:
        knowledge_map = fetch_knowledge_map([poi["id"] for poi in top_results])
    except Exception:  # noqa: BLE001
        logger.warning("Không tra được poi_knowledge cho lượt chat, bỏ qua ngữ cảnh lịch sử")
        knowledge_map = {}

    # Bỏ field null: phần lớn POI không có rating/knowledge, giữ "null" chỉ
    # tốn token mà model cũng không dùng được gì.
    summary = [
        {
            key: value
            for key, value in {
                "name": poi.get("name"),
                "category": poi.get("categoryLabel") or poi.get("category"),
                "distanceMeters": poi.get("distanceMeters"),
                "rating": poi.get("rating"),
                "busyness": poi.get("busyness"),
                "knowledge": knowledge_map.get(poi["id"]),
            }.items()
            if value is not None
        }
        for poi in top_results
    ]
    # Thời tiết là ngữ cảnh của CẢ lượt tìm kiếm (tính một lần ở tâm truy vấn),
    # không phải của riêng từng POI — lấy từ candidate đầu tiên nếu có.
    weather = results[0].get("weather") if results else None
    content = f"Câu hỏi của người dùng: {user_message!r}\n"
    if weather is not None:
        content += f"Thời tiết hiện tại (JSON): {json.dumps(weather, ensure_ascii=False)}\n"
    content += f"Danh sách POI tìm được (JSON): {json.dumps(summary, ensure_ascii=False)}"
    return [
        {"role": "system", "content": _EXPLAIN_SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


def _explain_fallback(results: list[dict[str, Any]]) -> str:
    # Ollama không tới được: vẫn trả lời có ích bằng cách liệt kê thẳng kết
    # quả thật, không bịa văn xuôi.
    if not results:
        return "Mình chưa tìm thấy địa điểm phù hợp gần bạn. Bạn thử đổi từ khoá hoặc mở rộng bán kính xem sao."
    names = ", ".join(poi.get("name", "") for poi in results[:5] if poi.get("name"))
    return f"Mình tìm được vài chỗ gần bạn: {names}."


def explain_results_stream(session_id: str, user_message: str, results: list[dict[str, Any]]) -> Iterator[str]:
    """Diễn giải bằng lời danh sách POI THẬT đã có sẵn — không gọi lại search.
    Trả từng mẩu chữ ngay khi LLM sinh ra (xem ``_ollama_chat_stream``)."""
    if not results:
        # Không có gì để diễn giải — câu xin lỗi cố định trả ngay, không chờ
        # LLM nói lại đúng ý đó.
        reply = _explain_fallback(results)
        _append_history(session_id, user_message, reply)
        yield reply
        return

    pieces: list[str] = []
    for piece in _ollama_chat_stream(_explain_messages(user_message, results), max_tokens=220):
        pieces.append(piece)
        yield piece
    reply = "".join(pieces).strip()
    if not reply:
        reply = _explain_fallback(results)
        yield reply
    _append_history(session_id, user_message, reply)


def explain_results(session_id: str, user_message: str, results: list[dict[str, Any]]) -> str:
    """Bản không stream của ``explain_results_stream`` (cho ``POST /api/v1/chat``)."""
    return "".join(explain_results_stream(session_id, user_message, results)).strip()


def record_clarification(session_id: str, user_message: str, clarifying_question: str) -> None:
    _append_history(session_id, user_message, clarifying_question)

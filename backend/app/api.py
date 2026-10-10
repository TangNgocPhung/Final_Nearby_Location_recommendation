import json
import logging
import threading
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal
from urllib.parse import quote
from uuid import UUID, uuid4

import psycopg
from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from . import (
    admin,
    assistant,
    auth,
    bus,
    charging,
    chat,
    chat_tools,
    checkins,
    convenience,
    directions,
    embeddings,
    exploration,
    explore,
    fuel,
    geofence,
    landmarks_admin,
    languages,
    narration,
    parking,
    photos,
    poi_detail,
    poi_videos,
    reviews,
    saved_places,
    storefront,
    streetview,
    toilets,
    translate,
    tts,
    voice,
)
from .ranking_snapshots import record_snapshot
from .config import settings
from .geocoding import parse_location, reverse_geocode
from .ingestion import ingestion_status, persist_events, publish_events
from .ltr import model as ltr_model
from .auth import AuthError, AuthUser
from .models import (
    AdminUserUpdate,
    ChangePasswordRequest,
    ChatHistoryRestore,
    ChatRequest,
    CheckInRequest,
    EventBatch,
    ExplorationRequest,
    ExploreDiscoverRequest,
    GeofenceRequest,
    GeoParseRequest,
    LoginRequest,
    MeetupRequest,
    ParkingReportRequest,
    LandmarkStory,
    NewLandmarkRequest,
    PoiVideoRequest,
    RegisterRequest,
    ReviewRequest,
    SavedPlaceRequest,
    TourRequest,
    SearchRequest,
    TranslateRequest,
    VoiceTurnRequest,
)
from .features.online import feature_store_status
from .features.serving import profile_category_boost, session_profile
from .graph.recommend import graph_candidate_ids
from .meal_fit import filter_for_meal
from .poi_import import data_status
from .ranking import (
    fetch_categories,
    fetch_category_affinity,
    fetch_trending,
    nearest_pois,
    rank_pois,
    rank_pois_detailed,
    suggest_pois,
)


DATABASE_URL = settings.database_url
RATE_LIMIT_PER_MINUTE = settings.rate_limit_per_minute
logger = logging.getLogger("nearby-api")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Thread nền, không chặn khởi động: API sẵn sàng ngay, thuyết minh được
    # tạo dần phía sau (xem app/narration.py).
    narration.start_prewarm()
    chat.start_warmup()
    embeddings.start_warmup()
    # Thread riêng vì database có thể chưa sẵn sàng: kết nối treo không được
    # chặn API khởi động.
    threading.Thread(target=auth.ensure_bootstrap_admin, name="bootstrap-admin", daemon=True).start()
    yield


app = FastAPI(
    title="Nearby POI API",
    version="0.3.0",
    description="Tầng thu thập dữ liệu, định vị và tìm kiếm POI theo không gian.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    # DELETE cần cho /api/v1/geofences/{id}: thiếu nó thì trình duyệt chặn ở
    # bước preflight và nút "bỏ nhắc" hỏng lặng lẽ, chỉ thấy lỗi trong console.
    # PATCH cho /api/v1/admin/users/{id} (đổi vai trò, khoá tài khoản).
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    # X-Narration-*: /narration/audio (Phase 16.2) trả text đã đọc kèm audio
    # qua header — không expose thì frontend gọi được audio nhưng
    # `response.headers.get(...)` luôn ra `null`, lặng lẽ mất phụ đề.
    expose_headers=[
        "X-Request-ID",
        "X-Process-Time-Ms",
        "X-RateLimit-Limit",
        "X-Narration-Text",
        "X-Narration-Verified",
        "X-Narration-Cache",
    ],
)

rate_windows: dict[str, deque[float]] = defaultdict(deque)
TRUSTED_PROXY_HOPS = settings.trusted_proxy_hops


def client_ip(request: Request) -> str:
    """IP thật của client, có tính tới các proxy tin cậy đứng trước.

    Lấy phần tử thứ `trusted_proxy_hops` ĐẾM TỪ CUỐI của X-Forwarded-For, vì mỗi
    proxy nối thêm IP của peer trực tiếp vào cuối. Không bao giờ lấy phần tử đầu:
    đó là phần client tự gửi và bịa được.
    """
    peer = request.client.host if request.client else "unknown"
    if TRUSTED_PROXY_HOPS <= 0:
        return peer
    forwarded = request.headers.get("X-Forwarded-For", "")
    chain = [part.strip() for part in forwarded.split(",") if part.strip()]
    if not chain:
        return peer
    # Danh sách ngắn hơn số hop khai báo: cấu hình sai hoặc ai đó gọi thẳng API,
    # không bỏ qua proxy nào cả — lấy phần tử đầu tiên còn tin được là phần tử đầu.
    index = max(0, len(chain) - TRUSTED_PROXY_HOPS)
    return chain[index] if index < len(chain) else chain[0]


@app.middleware("http")
async def gateway_context(request: Request, call_next) -> Response:
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    started = time.monotonic()
    session_id = request.headers.get("X-Session-ID")
    if session_id:
        try:
            UUID(session_id)
        except ValueError:
            response = JSONResponse(
                status_code=400,
                content={"detail": "X-Session-ID must be a UUID"},
            )
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Process-Time-Ms"] = f"{(time.monotonic() - started) * 1000:.2f}"
            return response

    client_key = session_id or client_ip(request)
    now = time.monotonic()
    window = rate_windows[client_key]
    while window and now - window[0] >= 60:
        window.popleft()
    if len(window) >= RATE_LIMIT_PER_MINUTE:
        response = Response(
            content='{"detail":"Rate limit exceeded"}',
            status_code=429,
            media_type="application/json",
        )
        response.headers["Retry-After"] = "60"
    else:
        window.append(now)
        request.state.request_id = request_id
        request.state.session_id = session_id
        response = await call_next(request)

    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time-Ms"] = f"{(time.monotonic() - now) * 1000:.2f}"
    response.headers["X-RateLimit-Limit"] = str(RATE_LIMIT_PER_MINUTE)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@app.get("/health")
def health(response: Response) -> dict[str, Any]:
    with psycopg.connect(DATABASE_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    response.headers["Cache-Control"] = "no-store"
    return {
        "status": "ok",
        "service": "nearby-ingestion-api",
        "version": app.version,
        # Lộ ra để giao diện biết có nên hiện nút chỉ đường trong ứng dụng hay
        # rơi về deep-link Google Maps, thay vì bấm xong mới biết là hỏng.
        "routing": bool(settings.osrm_url),
    }


@app.get("/api/pois/nearby")
def nearby_pois(
    request: Request,
    lat: float = Query(ge=-90, le=90),
    lng: float = Query(ge=-180, le=180),
    radius: int = Query(default=3_000, ge=100, le=50_000),
    q: str | None = Query(default=None, min_length=1, max_length=160),
    category: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=100),
    meal: Literal["breakfast", "lunch", "dinner", "late_night"] | None = None,
) -> list[dict[str, Any]]:
    # Header X-Session-ID (middleware đã kiểm UUID) chỉ để badge "người quanh
    # đây" không đếm chính người đang xem.
    session_id = getattr(request.state, "session_id", None)
    if meal is None:
        return rank_pois(lat, lng, radius, q, category, limit, session_id=session_id)
    # Lấy dư ứng viên vì bộ lọc theo bữa sẽ bỏ bớt quán sai bữa (chè, kem lúc
    # sáng…) — xem `meal_fit`.
    return filter_for_meal(
        rank_pois(lat, lng, radius, q, category, 100, session_id=session_id), meal, limit
    )


@app.get("/api/v1/pois/around")
def pois_around(
    lat: float = Query(ge=-90, le=90),
    lng: float = Query(ge=-180, le=180),
    radius: int = Query(default=600, ge=50, le=5_000),
    limit: int = Query(default=120, ge=1, le=300),
) -> list[dict[str, Any]]:
    """POI quanh một điểm, GẦN NHẤT trước — không xếp hạng. Cho chế độ AR."""
    return nearest_pois(lat, lng, radius, limit)


@app.get("/api/v1/pois/suggest")
def suggest(
    q: str = Query(min_length=1, max_length=160),
    lat: float | None = Query(default=None, ge=-90, le=90),
    lng: float | None = Query(default=None, ge=-180, le=180),
    limit: int = Query(default=8, ge=1, le=20),
) -> list[dict[str, Any]]:
    """Gợi ý gõ-tới-đâu (autocomplete) cho ô tìm kiếm — chỉ trả tên/toạ độ,
    không chạy qua pipeline ranking đầy đủ nên phản hồi nhanh hơn nhiều.
    """
    return suggest_pois(q, lat, lng, limit)


@app.post("/api/v1/search")
def contextual_search(payload: SearchRequest, request: Request) -> dict[str, Any]:
    parsed = parse_location(
        DATABASE_URL,
        payload.query,
        payload.latitude,
        payload.longitude,
    )
    center_latitude = payload.latitude
    center_longitude = payload.longitude
    if parsed.get("bestMatch"):
        center_latitude = parsed["bestMatch"]["latitude"]
        center_longitude = parsed["bestMatch"]["longitude"]
    subject = parsed["subject"] or None

    # Cá nhân hóa trên ĐƯỜNG TÌM KIẾM, không chỉ trên /recommendations.
    # `SearchRequest` vốn đã nhận `session_id` nhưng trước đây không dùng tới,
    # nên hai tín hiệu `graph` (0.10) và `category_boost` luôn bằng 0 với mọi
    # truy vấn — đúng như ablation đo được (Δ = 0 khi tắt `graph`).
    affinity: dict[str, float] = {}
    graph_ids: set[str] = set()
    if payload.session_id:
        session_key = str(payload.session_id)
        profile = session_profile(session_key)
        affinity = profile_category_boost(profile) or fetch_category_affinity(session_key)
        graph_ids = set(graph_candidate_ids(session_key))

    geo_telemetry: dict[str, Any] = {}
    results, retrieval_backend = rank_pois_detailed(
        center_latitude,
        center_longitude,
        payload.radius,
        subject,
        payload.category,
        payload.limit,
        category_boost=affinity,
        graph_boost=graph_ids,
        ranker=payload.ranker,
        telemetry=geo_telemetry,
        session_id=str(payload.session_id) if payload.session_id else None,
    )
    # Gán rank Ở ĐÂY chứ không trong ranking.py: results tại điểm này đã là thứ
    # tự CUỐI CÙNG sau diversify() — mà diversify đảo thứ tự so với điểm số. Gán
    # theo score thì rank không khớp thứ tự người dùng nhìn thấy, và mọi phân
    # tích position bias sau này thành vô nghĩa. Đặt trong rank_pois_detailed
    # cũng sai vì rank_pois() bọc lại nó, làm /pois/nearby và /recommendations
    # lộ thêm trường rank ngoài ý muốn.
    for index, poi in enumerate(results):
        poi["rank"] = index
    # Ảnh chụp feature THẬT ngay lúc này — sau khi có rank cuối cùng hiển thị
    # cho người dùng, cùng category_boost/graph_boost đã dùng để xếp hạng.
    # Lỗi ghi (DB tạm gián đoạn) không được làm hỏng response tìm kiếm.
    try:
        record_snapshot(
            request.state.request_id,
            payload.session_id,
            retrieval_backend,
            results,
            category_boost=affinity,
            graph_boost=graph_ids,
        )
    except psycopg.Error as error:
        # Không được làm hỏng response tìm kiếm, nhưng im lặng hoàn toàn thì
        # một lỗi ghi snapshot (như bug NaN/JSON đã gặp) có thể kéo dài hàng
        # tháng mà không ai biết dataset training đang rỗng.
        logger.warning("Ghi ranking_snapshots thất bại cho request %s: %s", request.state.request_id, error)
    return {
        "requestId": request.state.request_id,
        "query": subject or "",
        "searchCenter": {
            "latitude": center_latitude,
            "longitude": center_longitude,
            "source": "parsed-location" if parsed.get("matched") else "device-location",
        },
        "parsedLocation": parsed,
        # "opensearch" = truy xuất đa kênh; "postgis" = đã rơi về đường dự phòng
        "retrievalBackend": retrieval_backend,
        # Kênh không gian đã lọc bằng gì: "h3" (vành hexagon, đúng sơ đồ),
        # "geo_distance" (tính khoảng cách từng document) hay "postgis" (đã
        # fallback). Cùng lý do với `retrievalBackend`: hexagon nằm sẵn trong
        # DB không chứng minh được nó có tham gia truy xuất hay không.
        "geoFilter": geo_telemetry or None,
        # Bộ xếp hạng ĐÃ CHẠY THẬT, không phải cái được yêu cầu: xin "ltr" mà
        # thiếu file mô hình thì hệ thống rơi về "linear" một cách im lặng, và
        # nếu không lộ ra đây thì mọi số đo sau đó bị gán nhầm nhãn.
        "ranker": (results[0].get("rankerUsed") if results else payload.ranker),
        "results": results,
    }


def _plan_chat_turn(payload: ChatRequest) -> tuple[dict[str, Any], str | None]:
    """Phần KHÔNG cần LLM của một lượt chat. Trả ``(response, reply)`` —
    ``reply`` là ``None`` khi còn phải để LLM diễn giải ``response["results"]``.

    Thứ tự, tất cả bằng luật (`app/chat_tools.py`): xe buýt → câu hỏi tiếp trên danh sách
    vừa xem ("số 2 mấy giờ đóng cửa?") → địa danh nêu tên → công cụ chuyên
    biệt (xăng, WC, gửi xe…) → search thường, có bộ lọc ("đang mở", "có
    wifi"). Tách riêng để ``/api/v1/chat`` và ``/api/v1/chat/stream`` dùng
    chung đúng một luồng, chỉ khác ở cách trả phần diễn giải.
    """
    session_id = str(payload.session_id)

    # Xe buýt trước cả câu hỏi tiếp: "xe buýt số 2" là tuyến 02, không phải thẻ số 2.
    bus_params = chat_tools.detect_bus(payload.message)
    if bus_params is not None:
        return _bus_turn(payload, bus_params)

    last = chat_tools.recall(session_id)
    plan = chat_tools.follow_up(payload.message, last, payload.latitude, payload.longitude)
    if plan is not None:
        handled = _follow_up_turn(payload, last, plan)
        if handled is not None:
            return handled

    # Khớp tên POI THẬT trước, không qua LLM — xem docstring `chat.find_named_poi`.
    named_poi = chat.find_named_poi(payload.message, payload.latitude, payload.longitude)
    if named_poi is not None:
        chat_tools.remember(
            session_id,
            {
                "kind": "named",
                "radius": payload.radius,
                "results": [chat_tools.compact(named_poi)],
                "page_start": 0,
                "focus": named_poi["id"],
            },
        )
        return {
            "needsClarification": False,
            "searchParams": {
                "query": payload.message,
                "category": named_poi.get("category"),
                "radius": payload.radius,
            },
            "retrievalBackend": "poi-name-match",
            "results": [named_poi],
            "quickReplies": ["Chỉ đường tới đó", "Chỗ đó mấy giờ mở cửa?"],
        }, None

    filters = chat_tools.extract_filters(payload.message)
    tool = chat_tools.detect_tool(payload.message, filters, chat._radius_from_message(payload.message))
    if tool is not None:
        params, ignored = (
            chat_tools.refine_tool_params(tool["tool"], tool["params"], filters.keys)
            if tool["tool"] != "weather"
            else (tool["params"], ())
        )
        return _tool_turn(payload, tool["tool"], params, chat_tools.filter_note((), (*ignored, *filters.unsupported)))

    text = filters.text if filters else payload.message
    quick_intent = chat.quick_search_intent(text) if text else None
    intent = quick_intent or chat.rule_based_intent(text)
    empty_subject = bool(filters) and chat_tools.is_empty_subject(filters.leftover)

    if not filters and (intent["needs_clarification"] or not intent["search_query"]):
        question = intent["clarifying_question"] or "Bạn có thể nói rõ hơn bạn đang muốn tìm gì không?"
        chat.record_clarification(session_id, payload.message, question)
        return {"needsClarification": True, "searchParams": None, "results": []}, question

    # Câu rõ loại địa điểm đi đường nhanh: lọc theo category + khoảng cách,
    # không tạo embedding và không gọi LLM. Câu phức tạp vẫn giữ nguyên văn để
    # BM25/Vector hiểu đầy đủ sắc thái ("yên tĩnh"...). "Chỗ nào có wifi" chỉ
    # còn từ đệm sau khi cắt bộ lọc — không gửi chữ nào cho BM25.
    fast_category = intent["category"] if quick_intent is not None else None
    if filters and fast_category is None:
        fast_category = chat_tools.plain_category(filters)
    query = None if fast_category or empty_subject else (intent["search_query"] or None)
    return _search_turn(
        payload,
        query=query,
        semantic_query=intent.get("semantic_query") if query else None,
        category=fast_category,
        display_category=intent["category"],
        radius=intent["radius_m"] or payload.radius,
        filter_keys=filters.keys,
        unsupported=filters.unsupported,
        code_reply=quick_intent is not None or bool(filters),
    )


def _search_turn(
    payload: ChatRequest,
    *,
    query: str | None,
    category: str | None,
    radius: int,
    filter_keys: tuple[str, ...] = (),
    unsupported: tuple[str, ...] = (),
    code_reply: bool,
    display_category: str | None = None,
    semantic_query: str | None = None,
) -> tuple[dict[str, Any], str | None]:
    """Search thật (+ bộ lọc), rồi lưu danh sách làm ngữ cảnh cho câu hỏi tiếp.

    ``semantic_query``: câu nguyên văn cho kênh vector khi ``query`` (BM25) đã
    bỏ từ đệm — xem `chat.rule_based_intent`."""
    session_id = str(payload.session_id)
    geo_telemetry: dict[str, Any] = {}
    results, retrieval_backend = rank_pois_detailed(
        payload.latitude,
        payload.longitude,
        radius,
        query,
        category,
        chat_tools.FILTER_POOL if filter_keys else 20,
        telemetry=geo_telemetry,
        semantic_text=semantic_query,
        session_id=session_id,
    )
    note = None
    if filter_keys or unsupported:
        kept, unknown = chat_tools.apply_filters(results, filter_keys)
        results = kept[:20]
        note = chat_tools.filter_note(filter_keys, unsupported, unknown)
    for index, poi in enumerate(results):
        poi["rank"] = index

    chat_tools.remember(
        session_id,
        {
            "kind": "search",
            "query": query,
            "semantic_query": semantic_query,
            "category": category,
            "radius": radius,
            "filters": list(filter_keys),
            "results": [chat_tools.compact(poi, payload.latitude, payload.longitude) for poi in results],
            "page_start": 0,
        },
    )
    reply = chat.summarize_results_fast(session_id, payload.message, results, note) if code_reply else None
    return {
        "needsClarification": False,
        "searchParams": {
            "query": query,
            "category": display_category or category,
            "radius": radius,
        },
        "retrievalBackend": retrieval_backend,
        "fastPath": code_reply,
        "filters": [chat_tools.FILTER_LABELS[key] for key in filter_keys],
        "quickReplies": chat_tools.quick_replies("search", len(results), filter_keys),
        "results": results,
    }, reply


def _tool_turn(
    payload: ChatRequest, tool: str, params: dict[str, Any], note: str | None = None
) -> tuple[dict[str, Any], str]:
    """Câu thuộc một công cụ chuyên biệt (xăng, sạc, WC, gửi xe, tiện lợi,
    thời tiết) — gọi đúng module đó, câu trả lời do code ghép."""
    session_id = str(payload.session_id)
    cards, reply = chat_tools.run_tool(tool, params, payload.latitude, payload.longitude)
    if note:
        reply = f"{reply} {note}"
    results = [chat_tools.compact(card) for card in cards]
    # Thời tiết không có danh sách: giữ nguyên ngữ cảnh cũ để "số 2…" vẫn
    # trỏ vào danh sách địa điểm trước đó.
    if tool != "weather":
        chat_tools.remember(
            session_id,
            {"kind": tool, "params": params, "radius": params.get("radius"), "results": results, "page_start": 0},
        )
    chat.record_turn(session_id, payload.message, reply)
    return {
        "needsClarification": False,
        "searchParams": {"query": payload.message, "category": None, "radius": params.get("radius")},
        "retrievalBackend": f"tool:{tool}",
        "tool": tool,
        "quickReplies": chat_tools.quick_replies(tool, len(results)),
        "results": results,
    }, reply


def _bus_turn(payload: ChatRequest, params: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Câu hỏi xe buýt (giờ chạy, lộ trình, trạm gần) — trả lời bằng chữ kèm
    ``overlay`` để khung chat vẽ lộ trình/trạm lên bản đồ. Không có thẻ: trạm
    xe buýt không phải POI, bấm thẻ mở chi tiết POI sẽ lỗi. Như thời tiết, giữ
    nguyên ngữ cảnh cũ để "số 2…" vẫn trỏ vào danh sách địa điểm trước đó."""
    reply, overlay, replies = chat_tools.bus_answer(params, payload.latitude, payload.longitude)
    chat.record_turn(str(payload.session_id), payload.message, reply)
    return {
        "needsClarification": False,
        "searchParams": {"query": payload.message, "category": None, "radius": None},
        "retrievalBackend": "tool:bus",
        "tool": "bus",
        "overlay": overlay,
        "quickReplies": replies,
        "results": [],
    }, reply


def _follow_up_turn(
    payload: ChatRequest, last: dict[str, Any] | None, plan: dict[str, Any]
) -> tuple[dict[str, Any], str | None] | None:
    """Thực hiện kế hoạch của `chat_tools.follow_up`. ``None`` = không làm
    được với loại ngữ cảnh này, để luồng tìm mới xử lý câu."""
    if last is None:
        return None
    session_id = str(payload.session_id)
    kind = last.get("kind")
    plan_type = plan["type"]

    if plan_type == "clarify":
        chat.record_turn(session_id, payload.message, plan["reply"])
        return {"needsClarification": True, "searchParams": None, "results": []}, plan["reply"]

    if plan_type in ("answer", "page", "reorder"):
        context = {**last}
        if plan_type == "answer":
            context["focus"] = plan["focus"]
            results = plan["results"]
            # Câu gợi ý phải tự hiểu được ở lượt sau: "chỗ đó" trỏ vào `focus`.
            replies = []
            if plan.get("directions") is None:
                replies.append("Chỉ đường tới đó")
            if plan.get("question") != "hours":
                replies.append("Chỗ đó mấy giờ đóng cửa?")
        else:
            context["page_start"] = plan["page_start"]
            if plan_type == "reorder":
                context["results"] = plan["results"]
            results = plan["results"][: chat_tools.PAGE_SIZE] if plan_type == "reorder" else plan["results"]
            # Đếm cả phần chưa xem để còn gợi ý "Còn chỗ khác không?".
            remaining = len(context["results"]) - plan["page_start"]
            replies = chat_tools.quick_replies(kind or "search", remaining, tuple(last.get("filters") or ()))
        chat_tools.remember(session_id, context)
        chat.record_turn(session_id, payload.message, plan["reply"])
        return {
            "needsClarification": False,
            "searchParams": None,
            "retrievalBackend": "chat-context",
            "directions": plan.get("directions"),
            "quickReplies": replies,
            "results": results,
        }, plan["reply"]

    # plan_type == "rerun": chạy lại đúng truy vấn trước với bán kính/bộ lọc mới.
    if kind == "search":
        filter_keys = tuple(plan.get("filters", last.get("filters") or ()))
        radius = min(int(plan.get("radius") or last.get("radius") or payload.radius), chat_tools.SEARCH_MAX_RADIUS)
        return _search_turn(
            payload,
            query=last.get("query"),
            semantic_query=last.get("semantic_query"),
            category=last.get("category"),
            radius=radius,
            filter_keys=filter_keys,
            unsupported=tuple(plan.get("unsupported", ())),
            code_reply=True,
        )
    if kind in chat_tools.TOOL_TITLES:
        params = dict(last.get("params") or {})
        ignored: tuple[str, ...] = ()
        if "radius" in plan:
            params = chat_tools.tool_radius(kind, params, 2)
        if "filters" in plan:
            params, ignored = chat_tools.refine_tool_params(kind, params, tuple(plan["filters"]))
        note = chat_tools.filter_note((), (*ignored, *plan.get("unsupported", ())))
        return _tool_turn(payload, kind, params, note)
    return None


@app.post("/api/v1/chat")
def chat_turn(payload: ChatRequest) -> dict[str, Any]:
    """Một lượt chatbot: ý định (luật) -> pipeline search THẬT -> LLM diễn
    giải. LLM không bao giờ tự chọn POI — xem docstring `app/chat.py`.

    Không cá nhân hoá (category_boost/graph_boost) như `/api/v1/search`:
    phạm vi Phase 14 là chứng minh luồng intent->search->explain chạy đúng,
    cá nhân hoá chatbot để lại cho lượt sau khi luồng cơ bản đã ổn định.
    """
    response, reply = _plan_chat_turn(payload)
    if reply is None:
        reply = chat.explain_results(str(payload.session_id), payload.message, response["results"])
    return {"reply": reply, **response}


@app.post("/api/v1/chat/stream")
def chat_turn_stream(payload: ChatRequest) -> StreamingResponse:
    """Như `/api/v1/chat` nhưng trả NDJSON từng dòng để khung chat hiện kết
    quả ngay khi search xong (~1s), rồi hiện dần phần diễn giải khi LLM sinh
    chữ — thay vì bắt người dùng chờ hết ~30s LLM trên CPU mới thấy gì.

    Các dòng: ``{"type": "results", ...}`` (giống `/api/v1/chat` trừ
    ``reply``), rồi 0..n ``{"type": "delta", "text": ...}``, cuối cùng
    ``{"type": "done", "reply": <toàn bộ câu trả lời>}``.
    """
    response, reply = _plan_chat_turn(payload)

    def lines():
        yield json.dumps({"type": "results", **response}, ensure_ascii=False, default=str) + "\n"
        full_reply = reply
        if full_reply is None:
            pieces: list[str] = []
            for piece in chat.explain_results_stream(
                str(payload.session_id), payload.message, response["results"]
            ):
                pieces.append(piece)
                yield json.dumps({"type": "delta", "text": piece}, ensure_ascii=False) + "\n"
            full_reply = "".join(pieces).strip()
        yield json.dumps({"type": "done", "reply": full_reply}, ensure_ascii=False) + "\n"

    # X-Accel-Buffering: nginx (gateway) mặc định gom response rồi mới gửi —
    # tắt cho riêng response này để từng dòng tới trình duyệt ngay.
    return StreamingResponse(
        lines(),
        media_type="application/x-ndjson",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@app.delete("/api/v1/chat/history", status_code=204)
def delete_chat_history(request: Request) -> Response:
    """Bắt đầu cuộc trò chuyện mới: xoá lịch sử hội thoại của phiên trong
    ``X-Session-ID`` (middleware đã kiểm tra là UUID)."""
    owner_id = _owner_id(request)
    if not owner_id:
        return JSONResponse(status_code=400, content={"detail": "Thiếu X-Session-ID"})
    chat.clear_history(owner_id)
    return Response(status_code=204)


@app.put("/api/v1/chat/history", status_code=204)
def restore_chat_history(
    payload: ChatHistoryRestore,
    request: Request,
    _user: auth.AuthUser = Depends(auth.require_user),
) -> Response:
    """Mở lại một cuộc trò chuyện cũ (lịch sử lưu ở trình duyệt): nạp lại ngữ
    cảnh của phiên để câu hỏi tiếp theo được hiểu là câu nối tiếp. Chỉ tài
    khoản đã đăng nhập mới có lịch sử để mở lại."""
    owner_id = _owner_id(request)
    if not owner_id:
        return JSONResponse(status_code=400, content={"detail": "Thiếu X-Session-ID"})
    chat.set_history(owner_id, [turn.model_dump() for turn in payload.turns])
    return Response(status_code=204)


def is_postgres_uuid(value: str) -> bool:
    """Chốt chặt hơn `geofence.is_uuid` cho hai endpoint đẩy thẳng chuỗi vào cột ``uuid``.

    ``UUID()`` của Python dễ dãi hơn hẳn kiểu ``uuid`` của Postgres: nó nuốt cả
    "urn:uuid:<id>", "uuid:<id>", ngoặc nhọn lệch vế ("}<id>") và gạch nối đặt
    tuỳ tiện. Dấu hai chấm hợp lệ trong path segment nên Starlette đưa nguyên
    chuỗi vào handler; chuỗi đó lọt chốt rồi đi thẳng vào ``WHERE id = %s``,
    psycopg ném DataError giữa chừng và FastAPI trả 500 kèm traceback DB trong
    log — thay vì 400 tiếng Việt như hợp đồng đã hứa.

    Cách siết: so lại chuỗi ĐÃ CHUẨN HOÁ chứ không chỉ hỏi "parse được không".
    Hệ quả có chủ đích: dạng 32 ký tự không gạch nối và "{<id>}" đủ cặp — cả hai
    Postgres đều nhận — từ nay trả 400. Không client nào gửi các dạng đó (mọi id
    API phát ra đều là ``id::text``, tức dạng chuẩn).

    KHÔNG siết thẳng trong `geofence.is_uuid`: hàm đó còn là chốt của
    /api/v1/directions và DELETE /api/v1/geofences, đổi nó là đổi hành vi của
    hai tính năng không nằm trong phạm vi bản sửa này.
    """
    if not geofence.is_uuid(value):
        return False
    return str(UUID(value)) == value.lower()


@app.get("/api/v1/pois/{poi_id}")
def get_poi_detail(
    poi_id: str,
    lat: float | None = Query(default=None, ge=-90, le=90),
    lng: float | None = Query(default=None, ge=-180, le=180),
) -> Any:
    """Toàn bộ dữ liệu trang chi tiết, chỉ đọc Postgres.

    Không đụng "/api/pois/nearby": tiền tố khác hẳn (`/api/v1/pois` so với
    `/api/pois`), nên `{poi_id}` không bao giờ nuốt mất chuỗi "nearby".

    ``lat``/``lng`` là vị trí người dùng và HOÀN TOÀN tuỳ chọn. Thiếu chúng thì
    ``distanceMeters``/``etaMinutes`` trả ``null`` chứ không trả 0 — không có
    điểm xuất phát thì không có khoảng cách.
    """
    if not is_postgres_uuid(poi_id):
        return JSONResponse(status_code=400, content={"detail": "poi_id phải là UUID"})
    detail = poi_detail.fetch_detail(poi_id, lat, lng)
    if detail is None:
        return JSONResponse(status_code=404, content={"detail": "Không có địa điểm này"})
    return detail


@app.post("/api/v1/pois/{poi_id}/reviews", status_code=201)
def create_review(poi_id: str, payload: ReviewRequest, request: Request) -> Any:
    """Đánh giá 1-5 sao thật (explicit feedback) cho một POI.

    Khác ClientEvent event_type='review' (tín hiệu nhẹ qua /api/v1/events/batch,
    dùng để tính category affinity) — cái này ghi vào `poi_reviews`, hiển thị
    công khai qua `/api/v1/pois/{poi_id}` (`reviewSummary`), và cập nhật ngay
    `pois.rating`/`review_count` với `rating_source='user'`.

    Phiên lấy từ header ``X-Session-ID`` trước, rồi mới tới body — cùng quy ước
    với `/api/v1/geofences`.
    """
    if not is_postgres_uuid(poi_id):
        return JSONResponse(status_code=400, content={"detail": "poi_id phải là UUID"})
    user = auth.optional_user(request)
    session_id = _account_owner_id(request, payload.session_id)
    if not session_id:
        return JSONResponse(
            status_code=400,
            content={"detail": "Cần X-Session-ID hoặc session_id trong body"},
        )
    result = reviews.submit_review(
        poi_id=poi_id,
        session_id=session_id,
        rating=payload.rating,
        # Đã đăng nhập thì tên hiển thị lấy từ tài khoản khi form để trống.
        author_name=payload.author_name or (user.label if user else None),
        title=payload.title,
        body=payload.body,
    )
    if result is None:
        return JSONResponse(status_code=404, content={"detail": "Không có địa điểm này"})
    return result


@app.get("/api/v1/pois/{poi_id}/reviews/me")
def get_my_review(poi_id: str, request: Request) -> Any:
    """Đánh giá của phiên hiện tại, dùng để điền lại form khi người dùng sửa."""
    if not is_postgres_uuid(poi_id):
        return JSONResponse(status_code=400, content={"detail": "poi_id phải là UUID"})
    session_id = _account_owner_id(request)
    if not session_id:
        return JSONResponse(status_code=400, content={"detail": "Cần X-Session-ID"})
    return {"review": reviews.get_user_review(poi_id, session_id)}


@app.get("/api/v1/pois/{poi_id}/photos")
def get_poi_photos(
    poi_id: str,
    limit: int = Query(default=photos.MAX_PHOTOS, ge=1, le=photos.MAX_PHOTOS),
    confidence: str = Query(default="all", pattern="^(all|place|area)$"),
) -> Any:
    """Ảnh của một địa điểm. Tách khỏi endpoint chi tiết vì CÓ THỂ gọi mạng.

    Wikimedia bắt giãn nhịp tối thiểu một giây giữa hai request, nên một lần dò
    nguội mất vài giây. Gộp chung vào endpoint chi tiết thì cả trang phải chờ
    ảnh; tách ra thì giao diện gọi song song, trang hiện ngay và ảnh điền vào
    sau.

    Ba trạng thái, không được rút còn hai:
      ``ready``       — có ảnh.
      ``empty``       — ĐÃ hỏi Wikimedia, quanh đây thật sự không có ảnh nào.
      ``unavailable`` — CHƯA hỏi được (tắt cấu hình, hoặc không ra được mạng).
    Gộp ``empty`` với ``unavailable`` là biến một lần rớt mạng thành lời khẳng
    định sai về dữ liệu.
    """
    if not is_postgres_uuid(poi_id):
        return JSONResponse(status_code=400, content={"detail": "poi_id phải là UUID"})

    context = photos.poi_photo_context(poi_id)
    if context is None:
        return JSONResponse(status_code=404, content={"detail": "Không có địa điểm này"})

    if settings.photos_enabled and settings.google_maps_api_key and confidence != "area":
        from .google_photos import place_photos

        google = place_photos(poi_id, context, limit)
        if google["status"] == "ready":
            return JSONResponse(content=google, headers={"Cache-Control": "no-store"})

    cached = photos.cached_photos(poi_id, limit, confidence=confidence)
    if cached is not None:
        return cached

    if not settings.photos_enabled:
        return {"poiId": poi_id, "status": "unavailable", "fetchedAt": None, "photos": []}

    fetched = photos.fetch_and_store(
        poi_id, context["latitude"], context["longitude"], context["tags"], limit
    )
    if confidence == "all":
        return fetched
    fetched["photos"] = [
        photo for photo in fetched["photos"] if photo.get("confidence") == confidence
    ]
    if fetched["status"] == "ready" and not fetched["photos"]:
        fetched["status"] = "empty"
    return fetched


@app.get("/api/v1/assistant/suggestions")
def get_assistant_suggestions(
    request: Request,
    lat: float = Query(ge=-90, le=90),
    lng: float = Query(ge=-180, le=180),
) -> dict[str, Any]:
    """Chip gợi ý cho khung chatbot theo vị trí + thời điểm: lễ sắp tới (âm
    lịch) kèm cửa hàng theo tục lệ (tiệm hoa 20/10, 20/11…), mưa, giờ ăn quanh
    đây và quanh NHÀ, tour thuyết minh, săn địa danh, chế độ giọng nói, hẹn
    nhóm. Xem `app/assistant.py`. ``X-Session-ID`` (nếu có) chỉ dùng để đọc địa
    chỉ nhà đã lưu và tiến độ săn địa danh."""
    return assistant.suggestions(lat, lng, owner_id=_owner_id(request))


@app.post("/api/v1/assistant/tour")
def post_assistant_tour(payload: TourRequest) -> dict[str, Any]:
    """Hướng dẫn viên AI: tour đi bộ qua các địa điểm có bài thuyết minh."""
    return assistant.plan_tour(payload.latitude, payload.longitude, payload.minutes)


@app.post("/api/v1/assistant/meetup")
def post_assistant_meetup(
    payload: MeetupRequest,
    _user: auth.AuthUser = Depends(auth.require_user),
) -> dict[str, Any]:
    """Điểm hẹn công bằng: quán mà người đi xa nhất cũng không quá xa. Chỉ
    dành cho tài khoản đã đăng nhập."""
    return assistant.plan_meetup(
        [item.model_dump() for item in payload.participants],
        payload.category,
        payload.need_parking,
    )


# --- Săn địa danh Sài Gòn -----------------------------------------------------------


@app.get("/api/v1/explore")
def get_explore(
    request: Request,
    lat: float = Query(ge=-90, le=90),
    lng: float = Query(ge=-180, le=180),
) -> dict[str, Any]:
    """Bản đồ săn: mọi địa danh có câu chuyện kiểm chứng, gần trước xa sau, kèm
    trạng thái đã khám phá và tiến độ bộ sưu tập của phiên hiện tại."""
    return explore.overview(_owner_id(request), lat, lng)


@app.get("/api/v1/explore/{poi_id}/story")
def get_explore_story(poi_id: str, request: Request) -> Any:
    """Câu chuyện của một địa danh — chỉ mở khi phiên này đã khám phá nó."""
    if not is_postgres_uuid(poi_id):
        return JSONResponse(status_code=400, content={"detail": "poi_id phải là UUID"})
    result = explore.story(_owner_id(request), poi_id)
    if result is None:
        return JSONResponse(status_code=404, content={"detail": "Không phải địa danh săn được"})
    return result


@app.post("/api/v1/explore/{poi_id}/discover")
def post_explore_discover(poi_id: str, payload: ExploreDiscoverRequest, request: Request) -> Any:
    """Tới nơi + chụp ảnh → xác nhận vị trí (PostGIS) và ảnh (model thị giác
    cục bộ) → mở khoá câu chuyện, lưu ảnh vào kho ảnh thật của POI.

    Luôn 200 với trường ``status`` cho các kết cục của trò chơi (``too_far``,
    ``photo_rejected``…) — đó là phản hồi cho người chơi, không phải lỗi HTTP.
    """
    if not is_postgres_uuid(poi_id):
        return JSONResponse(status_code=400, content={"detail": "poi_id phải là UUID"})
    owner_id = _owner_id(request, payload.session_id)
    if not owner_id:
        return JSONResponse(status_code=400, content={"detail": "Cần X-Session-ID hoặc session_id trong body"})
    result = explore.discover(
        owner_id,
        poi_id,
        payload.latitude,
        payload.longitude,
        payload.accuracy_meters,
        payload.image_base64,
        payload.share_publicly,
    )
    if result["status"] == "not_found":
        return JSONResponse(status_code=404, content={"detail": "Không phải địa danh săn được"})
    return result


@app.get("/api/v1/pois/{poi_id}/visitor-photos")
def get_visitor_photos(poi_id: str, limit: int = Query(default=12, ge=1, le=48)) -> Any:
    """Ảnh người chơi Săn địa danh đã chụp tại chỗ — chỉ ảnh AI đã xác minh và
    người chụp đồng ý công khai."""
    if not is_postgres_uuid(poi_id):
        return JSONResponse(status_code=400, content={"detail": "poi_id phải là UUID"})
    return {"poiId": poi_id, "photos": explore.visitor_photos(poi_id, limit)}


@app.get("/api/v1/visitor-photos/{photo_id}")
def get_visitor_photo(photo_id: str, size: str = Query(default="full", pattern="^(full|thumb)$")) -> Response:
    if not is_postgres_uuid(photo_id):
        return JSONResponse(status_code=400, content={"detail": "photo_id phải là UUID"})
    data = explore.photo_bytes(photo_id, thumb=size == "thumb")
    if data is None:
        return JSONResponse(status_code=404, content={"detail": "Không có ảnh này"})
    return Response(
        content=data,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


# --- Chế độ giọng nói ------------------------------------------------------------


def _voice_search(query: str, latitude: float, longitude: float) -> list[dict[str, Any]]:
    """Tìm kiếm cho chế độ giọng nói: cùng pipeline với /api/v1/search, kể cả
    geo-parser ("cà phê gần Bến Thành" tìm quanh Bến Thành)."""
    parsed = parse_location(DATABASE_URL, query, latitude, longitude)
    center_lat, center_lng = latitude, longitude
    if parsed.get("bestMatch"):
        center_lat = parsed["bestMatch"]["latitude"]
        center_lng = parsed["bestMatch"]["longitude"]
    return rank_pois(
        center_lat, center_lng, voice.SEARCH_RADIUS_METERS, parsed["subject"] or query, None, voice.MAX_RESULTS
    )


def _has_story(poi_id: str) -> bool:
    if not is_postgres_uuid(poi_id):
        return False
    with psycopg.connect(DATABASE_URL) as connection:
        return connection.execute("SELECT 1 FROM poi_knowledge WHERE poi_id = %s", (poi_id,)).fetchone() is not None


@app.post("/api/v1/voice/turn")
def post_voice_turn(payload: VoiceTurnRequest) -> dict[str, Any]:
    """Một lượt hội thoại của chế độ giọng nói (người khiếm thị): câu vừa nói →
    câu trả lời để đọc + trạng thái mới + việc client cần làm (dẫn đường,
    thuyết minh…). Không gọi LLM — xem lý do ở docstring `app/voice.py`."""
    return voice.respond(
        payload.text,
        payload.latitude,
        payload.longitude,
        payload.state,
        search=_voice_search,
        has_story=_has_story,
        where=lambda lat, lng: reverse_geocode(DATABASE_URL, lat, lng),
        heading=payload.heading,
    )


_speech_cache: dict[str, bytes] = {}
_SPEECH_CACHE_SIZE = 64


@app.get("/api/v1/voice/speak")
def get_voice_speak(text: str = Query(min_length=1, max_length=400)) -> Response:
    """Đọc một câu tiếng Việt bằng giọng VieNeu-TTS (chạy trên máy chủ).

    Chỉ là đường DỰ PHÒNG: giao diện dùng giọng đọc của trình duyệt trước, và
    chỉ gọi tới đây khi máy người dùng không có giọng tiếng Việt (vd Chrome trên
    Windows chưa cài gói giọng). Cache theo nguyên câu — các câu cố định (chào,
    hướng dẫn, "đã tới nơi") chỉ phải tổng hợp một lần.
    """
    audio = _speech_cache.get(text)
    if audio is None:
        audio = tts.synthesize(text, "vi")
        if audio is None:
            return JSONResponse(status_code=503, content={"detail": "Giọng đọc máy chủ tạm không dùng được"})
        if len(_speech_cache) >= _SPEECH_CACHE_SIZE:
            _speech_cache.pop(next(iter(_speech_cache)))
        _speech_cache[text] = audio
    return Response(content=audio, media_type="audio/wav", headers={"Cache-Control": "private, max-age=3600"})


@app.get("/api/v1/pois/{poi_id}/verification")
def get_poi_verification(poi_id: str) -> Any:
    """Kết quả AI đọc biển hiệu trong ảnh đường phố để xác minh địa điểm còn
    đúng tên (xem `app/storefront.py`). Kết quả do `scripts/verify_storefronts`
    chạy nền ghi sẵn — endpoint này KHÔNG gọi model, chỉ đọc DB."""
    if not is_postgres_uuid(poi_id):
        return JSONResponse(status_code=400, content={"detail": "poi_id phải là UUID"})
    return storefront.get_verification(poi_id)


@app.get("/api/v1/pois/{poi_id}/streetview")
def get_poi_streetview(poi_id: str) -> Any:
    """Ảnh đường phố Mapillary quanh địa điểm: một tấm 360° gần nhất và một
    tấm ảnh thường nhìn thẳng về phía địa điểm. Xem `app/streetview.py`.

    Tách khỏi `/photos` vì khác nguồn, khác nhịp gọi (Mapillary không bắt giãn
    một giây như Wikimedia) và khác ý nghĩa: đây là ảnh ĐƯỜNG PHỐ, giao diện
    phải ghi rõ ngày chụp và khoảng cách.
    """
    if not is_postgres_uuid(poi_id):
        return JSONResponse(status_code=400, content={"detail": "poi_id phải là UUID"})
    context = photos.poi_photo_context(poi_id)
    if context is None:
        return JSONResponse(status_code=404, content={"detail": "Không có địa điểm này"})
    return streetview.street_views(poi_id, context["latitude"], context["longitude"])


@app.get("/api/v1/pois/{poi_id}/narration")
def get_poi_narration(
    poi_id: str,
    language: str = Query(default=chat.DEFAULT_NARRATION_LANGUAGE),
) -> Any:
    """AI thuyết minh CHỦ ĐỘNG cho một POI — người dùng chỉ cần chọn địa
    điểm, không cần gõ câu hỏi như chat. Xem docstring `chat.generate_poi_narration`.

    Tách khỏi endpoint chi tiết (cùng lý do với `/photos`): khi CHƯA có
    cache, gọi Ollama mất tới hàng chục giây, gộp vào sẽ làm cả trang chi
    tiết phải chờ. Chữ được cache và tạo sẵn lúc khởi động (`app/narration.py`),
    nên giao diện gọi ngay khi mở panel để hiện chữ luôn.

    ``available: false`` khi POI chưa có `poi_knowledge` — KHÔNG phải lỗi,
    chỉ là chưa biên soạn; giao diện ẩn hẳn nút thuyết minh trong trường hợp
    này thay vì hiện nút rồi báo lỗi.

    ``language``: một trong 134 mã ở `app/languages.py`. Chỉ vi/en được tạo
    sẵn; ngôn ngữ khác sinh ở lần gọi đầu (tới ~1-2 phút trên CPU) rồi cache.
    Sai giá trị (không có trong danh sách) thì rơi về "vi" thay vì
    400 — cùng nguyên tắc "không nghiêm khắc quá mức với dữ liệu suy đoán
    được" đã dùng ở nơi khác; tự sửa về mặc định an toàn hơn là chặn cả
    request chỉ vì một query param sai.
    """
    if not is_postgres_uuid(poi_id):
        return JSONResponse(status_code=400, content={"detail": "poi_id phải là UUID"})
    return narration.get_text(poi_id, language)


@app.get("/api/v1/pois/{poi_id}/narration/audio")
def get_poi_narration_audio(
    poi_id: str,
    language: str = Query(default=chat.DEFAULT_NARRATION_LANGUAGE),
    cached_only: bool = Query(default=False),
) -> Any:
    """Thuyết minh đọc thành GIỌNG NÓI THẬT (VieNeu-TTS, xem `app/tts.py`) —
    thay cho `speechSynthesis` của trình duyệt vốn phụ thuộc máy người xem có
    cài giọng tiếng Việt hay không.

    Audio LUÔN đọc đúng chữ đã cache của endpoint `/narration` (xem
    `app/narration.get_audio`) — không gọi LLM lần hai, nên chữ đang hiển thị
    và câu đang đọc không bao giờ lệch nhau. Văn bản đã đọc vẫn trả kèm qua
    header `X-Narration-Text` (URL-encoded vì header HTTP không mang được
    UTF-8 thô).

    404 khi POI chưa có `poi_knowledge` (giống endpoint text). 503 khi có
    narration nhưng TTS lỗi/ngôn ngữ chưa có giọng (vd "en" — VieNeu-TTS chỉ
    có giọng tiếng Việt) — frontend tự rơi về `speechSynthesis` trong
    trường hợp này, không phải lỗi cứng.

    Có CACHE (Phase 16.3, ``app/tts.get_cached``/``store``) theo (poi_id,
    language), và backend tạo sẵn audio cho mọi POI có `poi_knowledge` ngay
    lúc khởi động (`narration.start_prewarm`) — người dùng bấm nghe là phát
    luôn, không phải chờ LLM+TTS (~2 phút, đo được thật).
    """
    if not is_postgres_uuid(poi_id):
        return JSONResponse(status_code=400, content={"detail": "poi_id phải là UUID"})

    # `cached_only`: giao diện tải trước audio ngay khi mở panel để bấm là
    # phát luôn — nhưng KHÔNG được vì thế mà kích hoạt LLM+TTS cho mọi POI
    # người dùng chỉ lướt qua. Chưa có cache thì trả 204, chờ người dùng bấm.
    if cached_only and not narration.has_cached_audio(poi_id, language):
        return Response(status_code=204)
    status, result = narration.get_audio(poi_id, language)
    if status == "unavailable":
        return JSONResponse(status_code=404, content={"detail": "Chưa có thuyết minh cho địa điểm này"})
    if status != "ok" or result is None:
        return JSONResponse(
            status_code=503,
            content={"detail": "Chưa tạo được giọng đọc cho ngôn ngữ này"},
        )
    return Response(
        content=result["audio"],
        media_type="audio/wav",
        headers={
            "X-Narration-Text": quote(result["narration"]),
            "X-Narration-Verified": "true" if result["verified"] else "false",
            "X-Narration-Cache": result["cache"],
            # Nội dung cố định theo (poi_id, language) — cho trình duyệt giữ
            # lại, mở lại POI vừa nghe thì phát ngay không cần tải lại.
            "Cache-Control": "private, max-age=3600",
        },
    )


@app.get("/api/v1/parking/search")
def parking_search(
    lat: float = Query(ge=-90, le=90),
    lng: float = Query(ge=-180, le=180),
    vehicle: str = Query(default="motorbike", pattern="^(motorbike|car|bicycle|ev)$"),
    minutes: int = Query(default=120, ge=15, le=7 * 24 * 60),
    dest_lat: float | None = Query(default=None, ge=-90, le=90),
    dest_lng: float | None = Query(default=None, ge=-180, le=180),
    radius: int = Query(default=1000, ge=100, le=5000),
    limit: int = Query(default=20, ge=1, le=50),
) -> dict[str, Any]:
    """Tìm chỗ gửi xe / trạm sạc theo loại xe, xếp hạng theo quãng đi bộ tới
    điểm đến + tiền gửi ước tính cho ``minutes`` phút + độ chắc chắn của dữ
    liệu. Không có điểm đến thì lấy vị trí người dùng. Xem `app/parking.py`."""
    destination = (dest_lat, dest_lng) if dest_lat is not None and dest_lng is not None else None
    return parking.search(
        latitude=lat,
        longitude=lng,
        vehicle=vehicle,
        minutes=minutes,
        destination=destination,
        radius=radius,
        limit=limit,
    )


@app.get("/api/v1/charging/search")
def charging_search(
    lat: float = Query(ge=-90, le=90),
    lng: float = Query(ge=-180, le=180),
    vehicle: str = Query(default="any", pattern="^(any|motorbike|car)$"),
    network: str = Query(default="any", pattern="^(any|vinfast|other)$"),
    open_now: bool = Query(default=False),
    radius: int = Query(default=charging.DEFAULT_RADIUS_METERS, ge=500, le=30_000),
    limit: int = Query(default=20, ge=1, le=50),
) -> dict[str, Any]:
    """Trạm sạc xe điện theo loại xe (xe máy/ô tô điện), mạng sạc (VinFast /
    V-Green), đang mở cửa — xếp theo THỜI GIAN CHẠY XE THẬT tới trạm (OSRM).
    Xem `app/charging.py`."""
    return charging.search_stations(
        latitude=lat,
        longitude=lng,
        vehicle=vehicle,
        network=network,
        open_now=open_now,
        radius=radius,
        limit=limit,
    )


@app.get("/api/v1/fuel/search")
def fuel_search(
    lat: float = Query(ge=-90, le=90),
    lng: float = Query(ge=-180, le=180),
    vehicle: str = Query(default="motorbike", pattern="^(motorbike|car)$"),
    brand: str = Query(default="any", pattern="^(any|petrolimex|pvoil|saigon_petro|comeco|mipec|other)$"),
    open_now: bool = Query(default=False),
    radius: int = Query(default=fuel.DEFAULT_RADIUS_METERS, ge=500, le=30_000),
    limit: int = Query(default=20, ge=1, le=50),
) -> dict[str, Any]:
    """Trạm xăng theo hãng (Petrolimex, PVOIL, Saigon Petro, Comeco…), đang mở
    cửa — xếp theo THỜI GIAN CHẠY XE THẬT tới trạm (OSRM). Xem `app/fuel.py`."""
    return fuel.search_stations(
        latitude=lat,
        longitude=lng,
        vehicle=vehicle,
        brand=brand,
        open_now=open_now,
        radius=radius,
        limit=limit,
    )


@app.get("/api/v1/convenience/search")
def convenience_search(
    lat: float = Query(ge=-90, le=90),
    lng: float = Query(ge=-180, le=180),
    mode: str = Query(default="foot", pattern="^(foot|motorbike)$"),
    brand: str = Query(default="any", pattern="^(any|chain|circle_k|familymart|gs25|seven_eleven|ministop|winmart|bach_hoa_xanh|coop_food|bsmart|shop_go|satrafoods|other)$"),
    open_now: bool = Query(default=False),
    radius: int = Query(default=convenience.DEFAULT_RADIUS_METERS, ge=300, le=15_000),
    limit: int = Query(default=20, ge=1, le=50),
) -> dict[str, Any]:
    """Cửa hàng tiện lợi theo chuỗi (Circle K, FamilyMart, GS25, 7-Eleven…),
    đang mở cửa — xếp theo THỜI GIAN ĐI THẬT (đi bộ hoặc xe máy, OSRM). Xem
    `app/convenience.py`."""
    return convenience.search_stores(
        latitude=lat,
        longitude=lng,
        mode=mode,
        brand=brand,
        open_now=open_now,
        radius=radius,
        limit=limit,
    )


@app.get("/api/v1/toilets/search")
def toilets_search(
    lat: float = Query(ge=-90, le=90),
    lng: float = Query(ge=-180, le=180),
    mode: str = Query(default="foot", pattern="^(foot|motorbike)$"),
    source: str = Query(default="all", pattern="^(all|public)$"),
    free_only: bool = Query(default=False),
    wheelchair: bool = Query(default=False),
    open_now: bool = Query(default=False),
    radius: int = Query(default=toilets.DEFAULT_RADIUS_METERS, ge=300, le=15_000),
    limit: int = Query(default=20, ge=1, le=50),
) -> dict[str, Any]:
    """Nhà vệ sinh: WC công cộng, cộng cây xăng / trung tâm thương mại / quán
    có WC cho khách (ghi rõ nguồn) — xếp theo THỜI GIAN ĐI THẬT. Xem
    `app/toilets.py`."""
    return toilets.search_toilets(
        latitude=lat,
        longitude=lng,
        mode=mode,
        source=source,
        free_only=free_only,
        wheelchair=wheelchair,
        open_now=open_now,
        radius=radius,
        limit=limit,
    )


@app.get("/api/v1/bus/lines")
def bus_lines(
    q: str = Query(default="", max_length=80),
    limit: int = Query(default=60, ge=1, le=250),
) -> dict[str, Any]:
    """Tra tuyến xe buýt theo số tuyến ("14", "1" khớp "01"), tên bến hoặc
    đường đi qua. Mỗi tuyến gộp các lượt cùng số. Xem `app/bus.py`."""
    return bus.search_lines(q, limit)


@app.get("/api/v1/bus/routes/{route_id}")
def bus_route(route_id: int) -> Any:
    """Chi tiết một tuyến từ id một lượt: giờ chạy, giãn cách, giá vé, và với
    từng lượt — quãng đường, thời gian chuyến, lộ trình, trạm theo thứ tự."""
    detail = bus.route_detail(route_id)
    if detail is None:
        return JSONResponse(status_code=404, content={"detail": "Không có tuyến xe buýt này"})
    return detail


@app.get("/api/v1/bus/stops")
def bus_stops(
    lat: float = Query(ge=-90, le=90),
    lng: float = Query(ge=-180, le=180),
    q: str = Query(default="", max_length=80),
    radius: int = Query(default=bus.DEFAULT_STOP_RADIUS_METERS, ge=200, le=5_000),
    limit: int = Query(default=15, ge=1, le=50),
) -> dict[str, Any]:
    """Trạm xe buýt gần (xếp theo thời gian ĐI BỘ thật) kèm các tuyến dừng ở
    trạm; có ``q`` thì tìm trạm theo tên khắp thành phố."""
    return bus.search_stops(latitude=lat, longitude=lng, query=q, radius=radius, limit=limit)


@app.get("/api/v1/parking/{poi_id}")
def parking_detail(poi_id: str, minutes: int = Query(default=120, ge=15, le=7 * 24 * 60)) -> Any:
    """Thông tin gửi xe của một bãi/trạm sạc cho panel chi tiết: giá từng loại
    xe (kèm mức tin cậy + nguồn), giờ mở cửa, sức chứa, cổng sạc."""
    if not is_postgres_uuid(poi_id):
        return JSONResponse(status_code=400, content={"detail": "poi_id phải là UUID"})
    detail = parking.facility_detail(poi_id, minutes)
    if detail is None:
        return JSONResponse(status_code=404, content={"detail": "Địa điểm này không phải bãi xe/trạm sạc"})
    return detail


@app.post("/api/v1/parking/{poi_id}/reports", status_code=201)
def parking_report(poi_id: str, payload: ParkingReportRequest) -> Any:
    """Người dùng báo giá/giờ thực tế (crowdsource). Mỗi phiên một lần / bãi /
    loại xe / ngày."""
    if not is_postgres_uuid(poi_id):
        return JSONResponse(status_code=400, content={"detail": "poi_id phải là UUID"})
    status = parking.add_report(
        poi_id, payload.session_id, payload.vehicle, payload.amount_vnd, payload.unit, payload.opening_hours
    )
    if status == "not_parking":
        return JSONResponse(status_code=404, content={"detail": "Địa điểm này không phải bãi xe/trạm sạc"})
    if status == "duplicate":
        return JSONResponse(status_code=409, content={"detail": "Hôm nay bạn đã báo cho bãi này rồi"})
    return parking.facility_detail(poi_id)


@app.get("/api/v1/languages")
def list_languages(translations_only: bool = Query(default=False)) -> dict[str, Any]:
    """134 ngôn ngữ cho ô chọn ngôn ngữ giao diện và thuyết minh — xem
    `app/languages.py`. Tiếng Việt là ngôn ngữ gốc, không cần dịch."""
    items = languages.as_dicts()
    if translations_only:
        ready = {languages.SOURCE_LANGUAGE, *translate.cached_language_codes()}
        items = [item for item in items if item["code"] in ready]
    return {"source": languages.SOURCE_LANGUAGE, "languages": items}


@app.get("/api/v1/translations/{language}")
def get_translations(language: str) -> Any:
    """Mọi bản dịch giao diện ĐÃ CÓ cho một ngôn ngữ (chỉ đọc cache, không gọi
    LLM) — frontend áp ngay khi đổi ngôn ngữ và giữ nguyên tiếng Việt cho
    chuỗi chưa có bản dịch sẵn."""
    if not translate.is_supported(language):
        return JSONResponse(status_code=404, content={"detail": "Ngôn ngữ không được hỗ trợ"})
    return {"language": language, "translations": translate.cached_translations(language)}


@app.post("/api/v1/translations/{language}")
def post_translations(language: str, payload: TranslateRequest) -> Any:
    """Dịch một lô chuỗi giao diện bằng Qwen (xem `app/translate.py`). Chuỗi
    đã dịch trước đó trả từ cache; chuỗi dịch hỏng thì vắng mặt trong kết
    quả, frontend giữ nguyên tiếng Việt cho chuỗi đó."""
    if not translate.is_supported(language):
        return JSONResponse(status_code=404, content={"detail": "Ngôn ngữ không được hỗ trợ"})
    return {"language": language, "translations": translate.translate_texts(payload.texts, language)}


@app.get("/api/v1/categories")
def list_categories() -> list[dict[str, Any]]:
    return fetch_categories()


@app.get("/api/v1/trending")
def trending(limit: int = Query(default=10, ge=1, le=50)) -> dict[str, Any]:
    return fetch_trending(limit)


@app.get("/api/v1/recommendations")
def recommendations(
    request: Request,
    lat: float = Query(ge=-90, le=90),
    lng: float = Query(ge=-180, le=180),
    radius: int = Query(default=5_000, ge=100, le=50_000),
    session_id: UUID | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
) -> dict[str, Any]:
    # Ưu tiên đọc user profile từ ML Feature Store (online store); nếu chưa
    # materialize thì tính trực tiếp từ Postgres như trước.
    profile = session_profile(str(session_id)) if session_id else None
    affinity = profile_category_boost(profile)
    if not affinity and session_id:
        affinity = fetch_category_affinity(str(session_id))
    graph_ids = set(graph_candidate_ids(str(session_id))) if session_id else set()

    # Vùng chưa tới (bản đồ sương mù) chỉ ảnh hưởng việc CHỌN trong nhóm ứng viên
    # đã xếp hạng, không chạm vào ranker — điểm liên quan vẫn do ranker quyết định.
    owner_id = _account_owner_id(request, session_id)
    explored: set[str] = set()
    if owner_id:
        try:
            explored = exploration.explored_cells(owner_id)
        except psycopg.Error as error:
            logger.warning("Đọc explored_cells thất bại, bỏ qua gợi ý vùng mới: %s", error)
    results = rank_pois(
        lat,
        lng,
        radius,
        None,
        None,
        min(limit * 4, 50) if explored else limit,
        category_boost=affinity,
        graph_boost=graph_ids,
        session_id=str(session_id) if session_id else None,
    )
    results = exploration.mix_unexplored(results, explored, limit)
    top_category = max(affinity, key=affinity.get) if affinity else None
    for poi in results:
        if poi.get("unexplored"):
            poi["reason"] = f"Vùng bạn chưa từng tới · {poi['categoryLabel']}"
        elif poi.get("graphRecommended"):
            poi["reason"] = "Người có hành vi tương tự cũng thích địa điểm này"
        elif top_category and poi["category"] == top_category:
            poi["reason"] = f"Vì bạn hay xem địa điểm {poi['categoryLabel']}"
        elif affinity:
            poi["reason"] = "Gợi ý dựa trên lịch sử tìm kiếm của bạn"
        else:
            poi["reason"] = "Đang được nhiều người quan tâm gần đây"
    return {
        "personalized": bool(affinity) or bool(graph_ids),
        "graphRecommendations": len(graph_ids),
        "unexploredCount": sum(1 for poi in results if poi["unexplored"]),
        "profileSource": "feature-store" if profile else ("postgres" if affinity else "none"),
        "preferredCategories": sorted(affinity, key=affinity.get, reverse=True),
        "results": results,
    }


@app.post("/api/v1/geocode/parse")
def geocode_parse(payload: GeoParseRequest) -> dict[str, Any]:
    return parse_location(DATABASE_URL, payload.text, payload.latitude, payload.longitude)


@app.get("/api/v1/geocode/reverse")
def geocode_reverse(
    lat: float = Query(ge=-90, le=90),
    lng: float = Query(ge=-180, le=180),
) -> dict[str, Any]:
    return reverse_geocode(DATABASE_URL, lat, lng)


@app.post("/api/v1/events/batch", status_code=202)
def ingest_events(batch: EventBatch) -> dict[str, Any]:
    accepted_ids = persist_events(batch.events)
    accepted_set = set(accepted_ids)
    new_events = [event for event in batch.events if str(event.id) in accepted_set]
    queued_count, stream_available = publish_events(new_events) if new_events else (0, True)
    return {
        "accepted": len(accepted_ids),
        "eventIds": accepted_ids,
        "queued": queued_count,
        "delivery": "redis-stream" if stream_available else "durable-postgres-fallback",
    }


@app.get("/api/v1/ingestion/status")
def get_ingestion_status(
    session_id: UUID | None = Query(default=None),
) -> dict[str, Any]:
    return ingestion_status(str(session_id) if session_id else None)


@app.get("/api/v1/data/status")
def get_data_status() -> dict[str, Any]:
    return data_status(DATABASE_URL)


@app.get("/api/v1/features/status")
def get_feature_status() -> dict[str, Any]:
    """Độ tươi/độ phủ của ML Feature Store (online store)."""
    return feature_store_status()


@app.get("/api/v1/directions")
def get_directions(
    from_lat: float = Query(ge=-90, le=90),
    from_lng: float = Query(ge=-180, le=180),
    to_poi_id: str | None = Query(default=None, min_length=1, max_length=64),
    to_lat: float | None = Query(default=None, ge=-90, le=90),
    to_lng: float | None = Query(default=None, ge=-180, le=180),
    to_name: str = Query(default="Điểm đến", min_length=1, max_length=200),
    mode: str = Query(default=directions.DEFAULT_MODE, max_length=16),
) -> dict[str, Any]:
    """Tuyến đường thật từ vị trí người dùng tới một POI.

    ``mode`` là "car" | "motorbike" | "foot" (xem ``directions.MODES``) — mỗi
    hồ sơ một đồ thị OSRM riêng. Khi đồ thị của hồ sơ được yêu cầu chưa dựng,
    response tự khai báo ``route.approximate = true`` để tầng gọi biết tuyến
    đang tính bằng đồ thị mượn tạm.

    POI thật nhận bằng ``to_poi_id`` và luôn lấy toạ độ đích từ database. Cặp
    ``to_lat``/``to_lng`` chỉ dành cho các địa điểm mẫu của giao diện, vốn chưa
    có UUID trong database nhưng vẫn phải chỉ đường được ngay trong ứng dụng.
    """
    if mode not in directions.MODES:
        return JSONResponse(
            status_code=400,
            content={"detail": f"mode phải là một trong {sorted(directions.MODES)}"},
        )

    destination_id: str
    destination_address: str | None = None
    if to_poi_id is not None:
        if not geofence.is_uuid(to_poi_id):
            return JSONResponse(status_code=400, content={"detail": "to_poi_id phải là UUID"})
        with psycopg.connect(DATABASE_URL) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT name, ST_Y(location::geometry), ST_X(location::geometry), address
                    FROM pois WHERE id = %s
                    """,
                    (to_poi_id,),
                )
                row = cursor.fetchone()
        if row is None:
            return JSONResponse(status_code=404, content={"detail": "Không có POI này"})
        name, destination_lat, destination_lng, destination_address = row
        destination_address = (destination_address or "").strip() or None
        destination_id = to_poi_id
    elif to_lat is not None and to_lng is not None:
        name = to_name.strip()
        destination_lat, destination_lng = to_lat, to_lng
        destination_id = "sample-coordinate"
    else:
        return JSONResponse(
            status_code=400,
            content={"detail": "Cần to_poi_id hoặc đầy đủ to_lat và to_lng"},
        )

    # POI không có địa chỉ (trạm sạc, cây xăng… từ OSM) thì thẻ chỉ đường chỉ có
    # tên: mượn tên đường sát điểm đến từ OSRM (ước lượng, có cache) để người
    # dùng biết điểm đến nằm ở đâu. Chỉ POI thật trong DB mới có "địa chỉ".
    destination_street = (
        directions.nearest_streets(float(destination_lat), float(destination_lng))
        if to_poi_id is not None and destination_address is None
        else None
    )
    destination_info = {
        "latitude": float(destination_lat),
        "longitude": float(destination_lng),
        "address": destination_address,
        "streetAddress": destination_street,
    }

    result = directions.route(
        from_lat,
        from_lng,
        float(destination_lat),
        float(destination_lng),
        mode,
    )
    if result is None:
        # 200 kèm route rỗng chứ không phải 5xx: "chưa dựng OSRM" và "OSRM chết"
        # đều là trạng thái BÌNH THƯỜNG của hệ thống này, và giao diện cần phân
        # biệt chúng với một lỗi thật để còn rơi về deep-link.
        osrm_url = getattr(settings, directions.MODES[mode]["osrm_url_attr"])
        return {
            "poiId": destination_id,
            "poiName": name,
            "destination": destination_info,
            "route": None,
            "reason": "osrm-unavailable" if not osrm_url else "no-route",
        }

    return {
        "poiId": destination_id,
        "poiName": name,
        "origin": {"latitude": from_lat, "longitude": from_lng},
        "destination": destination_info,
        "route": result,
    }


@app.post("/api/v1/geofences", status_code=201)
def create_geofence(payload: GeofenceRequest, request: Request) -> dict[str, Any]:
    """Đăng ký nhắc khi tới gần một POI ("Proximity Notification Service").

    Phiên lấy từ header ``X-Session-ID`` trước, rồi mới tới body: header đã được
    middleware kiểm là UUID hợp lệ, còn body thì client tự khai.
    """
    session_id = getattr(request.state, "session_id", None) or (
        str(payload.session_id) if payload.session_id else None
    )
    if not session_id:
        return JSONResponse(
            status_code=400,
            content={"detail": "Cần X-Session-ID hoặc session_id trong body"},
        )
    created = geofence.subscribe(
        session_id=session_id,
        poi_id=str(payload.poi_id),
        radius_meters=payload.radius_meters,
        label=payload.label,
        notify_only_when_open=payload.notify_only_when_open,
        cooldown_minutes=payload.cooldown_minutes,
    )
    if created is None:
        return JSONResponse(status_code=404, content={"detail": "Không có POI này"})
    return created


@app.get("/api/v1/geofences")
def list_geofences(request: Request) -> dict[str, Any]:
    session_id = getattr(request.state, "session_id", None)
    if not session_id:
        return {"subscriptions": [], "reason": "no-session"}
    return {"subscriptions": geofence.list_subscriptions(session_id)}


@app.delete("/api/v1/geofences/{subscription_id}")
def delete_geofence(subscription_id: str, request: Request) -> dict[str, Any]:
    session_id = getattr(request.state, "session_id", None)
    if not session_id:
        return JSONResponse(status_code=400, content={"detail": "Cần X-Session-ID"})
    if not geofence.is_uuid(subscription_id):
        return JSONResponse(status_code=400, content={"detail": "subscription_id phải là UUID"})
    removed = geofence.unsubscribe(session_id, subscription_id)
    if not removed:
        return JSONResponse(status_code=404, content={"detail": "Không có vùng nhắc này"})
    return {"deleted": subscription_id}


# --- Địa điểm đã lưu ----------------------------------------------------------
#
# Chủ sở hữu là tài khoản (`user:<id>`) khi đã đăng nhập, ngược lại là
# `session_id` ẩn danh — xem `_account_owner_id`. Đăng nhập thì dữ liệu ẩn danh
# được chuyển sang tài khoản qua `saved_places.transfer_owner`.


def _owner_id(request: Request, payload_session: Any = None) -> str | None:
    return getattr(request.state, "session_id", None) or (
        str(payload_session) if payload_session else None
    )


def _account_owner_id(request: Request, payload_session: Any = None) -> str | None:
    """Chủ sở hữu cho dữ liệu đi theo TÀI KHOẢN (địa điểm đã lưu, đánh giá):
    ``user:<id>`` khi có token hợp lệ, ngược lại là phiên ẩn danh như cũ.

    Tách khỏi `_owner_id` có chủ đích: lịch sử chat, săn địa danh, gợi ý trợ lý
    vẫn ghi theo phiên — đổi chủ sở hữu ở đó thì ghi một nơi, xoá một nẻo.
    """
    user = auth.optional_user(request)
    return user.owner_id if user else _owner_id(request, payload_session)


@app.post("/api/v1/saved", status_code=201)
def create_saved_place(payload: SavedPlaceRequest, request: Request) -> Any:
    """Lưu một POI hoặc một điểm tự do. Lưu lại cùng POI là cập nhật, không nhân đôi."""
    owner_id = _account_owner_id(request, payload.session_id)
    if not owner_id:
        return JSONResponse(
            status_code=400,
            content={"detail": "Cần X-Session-ID hoặc session_id trong body"},
        )
    try:
        saved = saved_places.save_place(
            owner_id,
            poi_id=str(payload.poi_id) if payload.poi_id else None,
            latitude=payload.latitude,
            longitude=payload.longitude,
            label=payload.label,
            address=payload.address,
            note=payload.note,
            kind=payload.kind,
        )
    except ValueError as error:
        return JSONResponse(status_code=400, content={"detail": str(error)})
    if saved is None:
        return JSONResponse(status_code=404, content={"detail": "Không có POI này"})
    return saved


@app.get("/api/v1/saved")
def list_saved_places(request: Request) -> dict[str, Any]:
    """Không có phiên thì trả danh sách rỗng, không phải lỗi: giao diện luôn
    gọi endpoint này lúc khởi động, kể cả trước khi người dùng lưu gì."""
    owner_id = _account_owner_id(request)
    if not owner_id:
        return {"places": [], "reason": "no-session"}
    return {"places": saved_places.list_places(owner_id)}


@app.delete("/api/v1/saved/{place_id}")
def delete_saved_place(place_id: str, request: Request) -> Any:
    owner_id = _account_owner_id(request)
    if not owner_id:
        return JSONResponse(status_code=400, content={"detail": "Cần X-Session-ID"})
    if not saved_places.delete_place(owner_id, place_id):
        return JSONResponse(status_code=404, content={"detail": "Không có địa điểm này"})
    return {"deleted": place_id}


@app.post("/api/v1/checkins")
def create_checkin(payload: CheckInRequest, request: Request) -> Any:
    """Check-in tại một POI khi đứng đủ gần (khám phá AR). Đi theo tài khoản như
    địa điểm đã lưu — huy hiệu là thành quả người dùng muốn giữ khi đổi máy.

    Luôn 200 với ``status`` cho các kết cục của trò chơi (``too_far``,
    ``not_allowed``, ``already``) — đó là phản hồi cho người chơi, không phải
    lỗi HTTP; giống `/api/v1/explore/{poi_id}/discover`.
    """
    owner_id = _account_owner_id(request, payload.session_id)
    if not owner_id:
        return JSONResponse(
            status_code=400,
            content={"detail": "Cần X-Session-ID hoặc session_id trong body"},
        )
    result = checkins.check_in(
        owner_id,
        str(payload.poi_id),
        payload.latitude,
        payload.longitude,
        payload.accuracy_meters,
    )
    if result["status"] == "not_found":
        return JSONResponse(status_code=404, content={"detail": "Không có POI này"})
    if result["status"] in ("checked_in", "already"):
        # Đứng tại địa điểm thì ô đó cũng đã "sáng" trên bản đồ sương mù.
        exploration.record(
            owner_id,
            [{"latitude": payload.latitude, "longitude": payload.longitude, "accuracy_meters": payload.accuracy_meters}],
        )
    return result


@app.get("/api/v1/checkins")
def list_checkins(request: Request) -> dict[str, Any]:
    """Không có phiên thì trả rỗng (kèm huy hiệu chưa đạt), không phải lỗi:
    màn AR gọi endpoint này ngay khi mở."""
    owner_id = _account_owner_id(request)
    if not owner_id:
        return {**checkins.badge_summary_empty(), "reason": "no-session"}
    return checkins.summary(owner_id)


@app.post("/api/v1/exploration")
def record_exploration(payload: ExplorationRequest, request: Request) -> Any:
    """Ghi ô H3 vừa đi qua cho bản đồ sương mù; trả đường bao mới kèm ``added``.
    Chỉ giữ ô, không giữ toạ độ hay giờ — xem migration 0033."""
    owner_id = _account_owner_id(request, payload.session_id)
    if not owner_id:
        return JSONResponse(
            status_code=400,
            content={"detail": "Cần X-Session-ID hoặc session_id trong body"},
        )
    return exploration.record(owner_id, [point.model_dump() for point in payload.points])


@app.get("/api/v1/exploration")
def get_exploration(request: Request) -> dict[str, Any]:
    owner_id = _account_owner_id(request)
    if not owner_id:
        return {**exploration.empty_overview(), "reason": "no-session"}
    return exploration.overview(owner_id)


@app.get("/api/v1/exploration/districts")
def get_exploration_districts(request: Request) -> dict[str, Any]:
    """Số ô đã mở theo quận. Tách khỏi `GET /api/v1/exploration` vì mỗi ô phải dò
    POI gần nhất — chỉ tính khi giao diện mở bảng thống kê."""
    owner_id = _account_owner_id(request)
    if not owner_id:
        return {**exploration.group_by_district([]), "reason": "no-session"}
    return exploration.district_stats(owner_id)


@app.delete("/api/v1/exploration")
def clear_exploration(request: Request) -> Any:
    """Người dùng tự xoá toàn bộ vùng đã khám phá — dữ liệu vị trí của họ, họ
    phải xoá được bằng một nút."""
    owner_id = _account_owner_id(request)
    if not owner_id:
        return JSONResponse(status_code=400, content={"detail": "Cần X-Session-ID"})
    return {"deleted": exploration.clear(owner_id)}


@app.get("/api/v1/notifications/stream")
def notification_stream(request: Request) -> Response:
    """Server-Sent Events: đẩy thông báo tới gần xuống trình duyệt.

    Chọn SSE thay vì Web Push vì SSE không cần VAPID key, không cần máy chủ đẩy
    của bên thứ ba, và chỉ cần một endpoint. Đánh đổi: chỉ chạy khi tab còn mở —
    với phạm vi một đồ án thì đó là đánh đổi đúng, và phải nói rõ trong báo cáo
    thay vì để hội đồng tự phát hiện.

    Mỗi kết nối tự đóng sau ``NOTIFICATION_STREAM_TTL_SECONDS``; trình duyệt tự
    kết nối lại. Không có trần này thì mỗi tab bỏ quên giữ một luồng vĩnh viễn
    trong threadpool của FastAPI.
    """
    session_id = getattr(request.state, "session_id", None)
    if not session_id:
        return JSONResponse(status_code=400, content={"detail": "Cần X-Session-ID"})
    return StreamingResponse(
        geofence.stream_notifications(session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            # Bắt buộc khi đứng sau nginx: proxy_buffering mặc định gom kết quả
            # lại rồi mới trả, nên SSE không bao giờ tới nơi đúng lúc.
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/v1/ltr/status")
def get_ltr_status() -> dict[str, Any]:
    """Mô hình LambdaMART đang nạp được hay không, và huấn luyện trên bao nhiêu.

    Cần lộ ra ngoài vì `?ranker=ltr` rơi về tuyến tính một cách IM LẶNG khi
    thiếu mô hình: không có endpoint này thì không cách nào biết một phép đo
    "LTR" có thật sự chạy LTR hay không.
    """
    return ltr_model.info()


# --- Đăng nhập & phân quyền ----------------------------------------------------
#
# Hai vai trò: `user` (mặc định khi đăng ký) và `admin`. Xem `app/auth.py` về
# token và `app/admin.py` về các chốt chặn khi đổi quyền.


def _session_payload(user: AuthUser) -> dict[str, Any]:
    return {"token": auth.issue_token(user.id), "user": user.public()}


def _adopt_session_data(request: Request, user: AuthUser, payload_session: Any) -> None:
    """Đăng nhập trên trình duyệt đã có dữ liệu ẩn danh thì chuyển nó sang tài
    khoản. Lỗi ở bước này không được làm hỏng việc đăng nhập."""
    session_id = _owner_id(request, payload_session)
    if not session_id:
        return
    try:
        saved_places.transfer_owner(session_id, user.owner_id)
        reviews.transfer_owner(session_id, user.owner_id)
        checkins.transfer_owner(session_id, user.owner_id)
        exploration.transfer_owner(session_id, user.owner_id)
    except psycopg.Error as error:
        logger.warning("Không chuyển được dữ liệu phiên sang tài khoản: %s", error)


@app.post("/api/v1/auth/register", status_code=201)
def register(payload: RegisterRequest, request: Request) -> Any:
    try:
        user = auth.create_user(
            payload.username, payload.password, display_name=payload.display_name, role="user"
        )
    except AuthError as error:
        return JSONResponse(status_code=400, content={"detail": str(error)})
    _adopt_session_data(request, user, payload.session_id)
    return _session_payload(user)


@app.post("/api/v1/auth/login")
def login(payload: LoginRequest, request: Request) -> Any:
    try:
        user = auth.authenticate(payload.username, payload.password)
    except AuthError as error:
        return JSONResponse(status_code=401, content={"detail": str(error)})
    _adopt_session_data(request, user, payload.session_id)
    return _session_payload(user)


@app.get("/api/v1/auth/me")
def get_me(user: AuthUser = Depends(auth.require_user)) -> dict[str, Any]:
    return {"user": user.public()}


@app.post("/api/v1/auth/password")
def post_change_password(
    payload: ChangePasswordRequest, user: AuthUser = Depends(auth.require_user)
) -> Any:
    try:
        auth.change_password(user, payload.current_password, payload.new_password)
    except AuthError as error:
        return JSONResponse(status_code=400, content={"detail": str(error)})
    return {"changed": True}


@app.get("/api/v1/admin/overview")
def admin_overview(_admin: AuthUser = Depends(auth.require_admin)) -> dict[str, Any]:
    return admin.overview()


@app.get("/api/v1/admin/users")
def admin_list_users(
    q: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _admin: AuthUser = Depends(auth.require_admin),
) -> dict[str, Any]:
    return admin.list_users(q, limit, offset)


@app.patch("/api/v1/admin/users/{user_id}")
def admin_update_user(
    user_id: str, payload: AdminUserUpdate, actor: AuthUser = Depends(auth.require_admin)
) -> Any:
    try:
        updated = admin.update_user(
            actor,
            user_id,
            role=payload.role,
            is_active=payload.is_active,
            display_name=payload.display_name,
            password=payload.password,
        )
    except AuthError as error:
        return JSONResponse(status_code=400, content={"detail": str(error)})
    if updated is None:
        return JSONResponse(status_code=404, content={"detail": "Không có tài khoản này"})
    return {"user": updated}


@app.get("/api/v1/admin/reviews")
def admin_list_reviews(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _admin: AuthUser = Depends(auth.require_admin),
) -> dict[str, Any]:
    return admin.list_reviews(limit, offset)


@app.delete("/api/v1/admin/reviews/{review_id}")
def admin_delete_review(review_id: str, _admin: AuthUser = Depends(auth.require_admin)) -> Any:
    if not is_postgres_uuid(review_id):
        return JSONResponse(status_code=400, content={"detail": "review_id phải là UUID"})
    result = reviews.delete_review(review_id)
    if result is None:
        return JSONResponse(status_code=404, content={"detail": "Không có đánh giá này"})
    return result


# Video YouTube gắn vào địa điểm: admin dán link, `app/poi_videos.py` chuẩn hoá
# về id video. Trang chi tiết đọc chúng qua `videos` của `/api/v1/pois/{id}`.


@app.get("/api/v1/admin/videos")
def admin_list_videos(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _admin: AuthUser = Depends(auth.require_admin),
) -> dict[str, Any]:
    return poi_videos.list_recent(limit, offset)


@app.post("/api/v1/admin/pois/{poi_id}/videos", status_code=201)
def admin_add_video(
    poi_id: str, payload: PoiVideoRequest, actor: AuthUser = Depends(auth.require_admin)
) -> Any:
    if not is_postgres_uuid(poi_id):
        return JSONResponse(status_code=400, content={"detail": "poi_id phải là UUID"})
    try:
        video = poi_videos.add_video(actor, poi_id, payload.url, payload.title)
    except poi_videos.DuplicateVideoError as error:
        return JSONResponse(status_code=409, content={"detail": str(error)})
    except poi_videos.VideoError as error:
        return JSONResponse(status_code=400, content={"detail": str(error)})
    if video is None:
        return JSONResponse(status_code=404, content={"detail": "Không có địa điểm này"})
    return {"video": video}


@app.delete("/api/v1/admin/videos/{video_id}")
def admin_delete_video(video_id: str, _admin: AuthUser = Depends(auth.require_admin)) -> Any:
    if not is_postgres_uuid(video_id):
        return JSONResponse(status_code=400, content={"detail": "video_id phải là UUID"})
    if not poi_videos.delete_video(video_id):
        return JSONResponse(status_code=404, content={"detail": "Không có video này"})
    return {"deleted": True}


# --- Admin: địa danh cho Săn địa danh Sài Gòn -----------------------------------------
# Thêm/sửa/gỡ bài giới thiệu (`poi_knowledge`) của địa danh săn được, kể cả tạo POI
# mới chưa có trong dữ liệu. Xem `app/landmarks_admin.py`.


@app.get("/api/v1/admin/landmarks")
def admin_list_landmarks(
    q: str = Query(default="", max_length=100),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _admin: AuthUser = Depends(auth.require_admin),
) -> dict[str, Any]:
    return landmarks_admin.list_landmarks(q, limit, offset)


@app.get("/api/v1/admin/landmarks/candidates")
def admin_landmark_candidates(
    q: str = Query(min_length=2, max_length=100),
    _admin: AuthUser = Depends(auth.require_admin),
) -> dict[str, Any]:
    """POI theo tên để chọn gắn bài giới thiệu."""
    return {"pois": landmarks_admin.search_pois(q)}


@app.get("/api/v1/admin/landmarks/{poi_id}")
def admin_get_landmark(poi_id: str, _admin: AuthUser = Depends(auth.require_admin)) -> Any:
    if not is_postgres_uuid(poi_id):
        return JSONResponse(status_code=400, content={"detail": "poi_id phải là UUID"})
    landmark = landmarks_admin.get_landmark(poi_id)
    if landmark is None:
        return JSONResponse(status_code=404, content={"detail": "Không phải địa danh săn được"})
    return landmark


@app.put("/api/v1/admin/landmarks/{poi_id}")
def admin_save_landmark(
    poi_id: str, payload: LandmarkStory, actor: AuthUser = Depends(auth.require_admin)
) -> Any:
    """Gắn hoặc sửa bài giới thiệu của một POI có sẵn → POI thành địa danh săn được."""
    if not is_postgres_uuid(poi_id):
        return JSONResponse(status_code=400, content={"detail": "poi_id phải là UUID"})
    try:
        landmark = landmarks_admin.upsert_story(actor, poi_id, payload.model_dump())
    except landmarks_admin.LandmarkError as error:
        return JSONResponse(status_code=409, content={"detail": str(error)})
    if landmark is None:
        return JSONResponse(status_code=404, content={"detail": "Không có địa điểm này"})
    return landmark


@app.post("/api/v1/admin/landmarks", status_code=201)
def admin_create_landmark(
    payload: NewLandmarkRequest, actor: AuthUser = Depends(auth.require_admin)
) -> Any:
    """Tạo địa điểm mới (chưa có trong dữ liệu) kèm bài giới thiệu."""
    try:
        return landmarks_admin.create_landmark(actor, payload.model_dump())
    except landmarks_admin.DuplicateLandmarkError as error:
        return JSONResponse(status_code=409, content={"detail": str(error), "existing": error.existing})
    except landmarks_admin.LandmarkError as error:
        return JSONResponse(status_code=400, content={"detail": str(error)})


@app.delete("/api/v1/admin/landmarks/{poi_id}")
def admin_delete_landmark(poi_id: str, actor: AuthUser = Depends(auth.require_admin)) -> Any:
    """Gỡ khỏi Săn địa danh (xoá bài giới thiệu; POI được giữ)."""
    if not is_postgres_uuid(poi_id):
        return JSONResponse(status_code=400, content={"detail": "poi_id phải là UUID"})
    if not landmarks_admin.delete_story(actor, poi_id):
        return JSONResponse(status_code=404, content={"detail": "Không phải địa danh săn được"})
    return {"deleted": True}

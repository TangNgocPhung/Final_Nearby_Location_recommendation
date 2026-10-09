'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  History,
  Home,
  MapPin,
  MessageCircle,
  RotateCw,
  Search,
  Send,
  Sparkles,
  SquarePen,
  Star,
  Users,
  X,
} from 'lucide-react';

import { AssistantExplore } from '@/components/assistant-explore';
import { AssistantMeetup } from '@/components/assistant-meetup';
import { AssistantTour } from '@/components/assistant-tour';
import {
  ChatHistory,
  conversationTitle,
  loadConversations,
  MAX_CONVERSATIONS,
  newConversationId,
  saveConversations,
  type SavedConversation,
} from '@/components/chat-history';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Spinner } from '@/components/ui/spinner';
import {
  Bubble,
  BubbleContent,
  BubbleGroup,
} from '@/components/ui/bubble';
import { Message, MessageContent } from '@/components/ui/message';
import {
  MessageScroller,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerProvider,
  MessageScrollerViewport,
} from '@/components/ui/message-scroller';
import {
  distanceMeters,
  formatMeters,
  type AssistantOverlay,
  type PlaceRef,
  type SearchAction,
  type Suggestion,
  type SuggestionsResponse,
} from '@/lib/assistant';
import { cn } from '@/lib/utils';

/* ------------------------------------------------------------------ *
 * Kiểu dữ liệu — gõ đúng response của POST /api/v1/chat (app/api.py).
 * ------------------------------------------------------------------ */

type ChatBusyness = {
  estimated: boolean;
  level: 'Đông' | 'Khá đông' | 'Vắng' | null;
  score: number | null;
};

type ChatPoiResult = {
  id: string;
  name: string;
  categoryLabel?: string | null;
  category?: string | null;
  distanceMeters?: number | null;
  rating?: number | null;
  busyness?: ChatBusyness | null;
};

// Từng dòng NDJSON của POST /api/v1/chat/stream: kết quả search tới trước
// (~1s), lời diễn giải của LLM tới dần sau — xem `chat_turn_stream` (app/api.py).
type ChatStreamEvent =
  | { type: 'results'; needsClarification: boolean; results: ChatPoiResult[] }
  | { type: 'delta'; text: string }
  | { type: 'done'; reply: string };

type ChatTurn = {
  role: 'user' | 'assistant';
  content: string;
  /** câu trả lời đang được LLM viết dần (stream chưa xong) */
  pending?: boolean;
  results?: ChatPoiResult[];
  /** địa điểm gắn với một gợi ý sự kiện (có thể là con phố, không có poiId) */
  places?: PlaceRef[];
  /** câu hỏi gợi ý tiếp theo, bấm là gửi cho chatbot */
  followUp?: string | null;
  /** nút tìm trực tiếp (tiệm hoa gần bạn…) — chạy pipeline xếp hạng, không qua LLM */
  search?: SearchAction | null;
  /** hiện nút "đặt vị trí hiện tại làm nhà" */
  offerSetHome?: boolean;
};

// Tải lại gợi ý khi người dùng đi xa hơn mức này, hoặc sau REFRESH_MS.
const SUGGESTION_MOVE_METERS = 1000;
const SUGGESTION_REFRESH_MS = 10 * 60 * 1000;
// Số thẻ địa điểm hiện dưới mỗi câu trả lời — tìm trực tiếp cũng chỉ lấy
// đúng chừng này để câu "N địa điểm…" khớp với số thẻ người dùng thấy.
const MAX_RESULT_CARDS = 5;
const SAMPLE_QUESTION = 'Quán cà phê yên tĩnh gần đây';
// Số cuộc gần nhất hiện sẵn ở màn hình chào, còn lại vào "Lịch sử".
const RECENT_CONVERSATIONS = 3;
// Backend chỉ dùng vài lượt cuối làm ngữ cảnh (chat.HISTORY_MAX_TURNS) và
// giới hạn độ dài mỗi lượt (ChatHistoryTurn) — cắt sẵn trước khi gửi.
const RESTORE_TURNS = 12;
const RESTORE_CONTENT_CHARS = 4000;

// Tính năng của trợ lý luôn hiện sẵn, không chờ API gợi ý: API chậm (lần đầu
// phải gọi dịch vụ thời tiết) hoặc lỗi thì các tính năng này vẫn mở được.
// API trả chip cùng loại thì chỉ mượn dòng phụ có số liệu thật của nó.
const FEATURE_CHIPS: Suggestion[] = [
  { id: 'tour', kind: 'tour', icon: '🎧', title: 'Tour thuyết minh', subtitle: 'Đi bộ nghe kể chuyện di tích', action: { type: 'tour' } },
  { id: 'explore', kind: 'explore', icon: '🗺️', title: 'Săn địa danh', subtitle: 'Khám phá địa danh quanh bạn', action: { type: 'explore' } },
  { id: 'voice', kind: 'voice', icon: '🎙️', title: 'Giọng nói', subtitle: 'Tìm và đi tới chỉ bằng lời', action: { type: 'voice' } },
  { id: 'meetup', kind: 'meetup', icon: '🤝', title: 'Hẹn nhóm', subtitle: 'Quán công bằng cho cả nhóm', action: { type: 'meetup' } },
];
const FEATURE_KINDS = new Set<Suggestion['kind']>(FEATURE_CHIPS.map((chip) => chip.kind));

function SuggestionChip({
  suggestion,
  onPick,
  large = false,
}: {
  suggestion: Suggestion;
  onPick: (suggestion: Suggestion) => void;
  large?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={() => onPick(suggestion)}
      title={suggestion.subtitle}
      className={cn(
        'flex shrink-0 items-center gap-2 rounded-xl border border-border bg-background text-left transition hover:border-primary/40 hover:bg-muted',
        large ? 'w-full px-3 py-2' : 'max-w-56 px-2.5 py-1.5',
      )}
    >
      <span className={large ? 'text-lg' : 'text-base'} aria-hidden>
        {suggestion.icon}
      </span>
      <span className="min-w-0">
        <span className="block truncate text-xs font-semibold">{suggestion.title}</span>
        <span className="block truncate text-[11px] text-muted-foreground">{suggestion.subtitle}</span>
      </span>
    </button>
  );
}

function PlaceCard({
  place,
  onView,
  onFocus,
}: {
  place: PlaceRef;
  onView: (poiId: string) => void;
  onFocus: (latitude: number, longitude: number) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => (place.poiId ? onView(place.poiId) : onFocus(place.latitude, place.longitude))}
      className="flex w-full min-w-0 items-center gap-2 rounded-lg border border-border bg-background px-3 py-2 text-left text-sm transition-colors hover:bg-muted"
    >
      <MapPin className="size-4 shrink-0 text-muted-foreground" />
      <span className="min-w-0 flex-1 truncate font-medium">{place.name}</span>
      {place.distanceMeters != null && (
        <span className="shrink-0 text-xs text-muted-foreground">{formatMeters(place.distanceMeters)}</span>
      )}
    </button>
  );
}

// Ước tính từ tương tác gần đây trên Nearby, KHÔNG PHẢI dữ liệu real-time
// thật — xem `spatio_temporal._busyness_estimate` phía backend. Màu chỉ là
// gợi ý trực quan, chữ "(ước tính)" luôn đi kèm để không đọc nhầm thành số đo.
const BUSYNESS_STYLE: Record<string, string> = {
  'Đông': 'bg-red-500/10 text-red-600 dark:text-red-400',
  'Khá đông': 'bg-amber-500/10 text-amber-600 dark:text-amber-400',
  'Vắng': 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
};

function ChatPoiCard({
  poi,
  onView,
}: {
  poi: ChatPoiResult;
  onView: (poiId: string) => void;
}) {
  const distance = formatMeters(poi.distanceMeters);
  const busyLevel = poi.busyness?.estimated ? poi.busyness.level : null;
  return (
    <button
      type="button"
      onClick={() => onView(poi.id)}
      className="flex w-full min-w-0 flex-col gap-1 rounded-lg border border-border bg-background px-3 py-2 text-left text-sm transition-colors hover:bg-muted"
    >
      <span className="flex w-full min-w-0 items-center gap-2">
        <MapPin className="size-4 shrink-0 text-muted-foreground" />
        <span className="min-w-0 flex-1 truncate font-medium">{poi.name}</span>
        {typeof poi.rating === 'number' && (
          <span className="flex shrink-0 items-center gap-0.5 text-xs text-muted-foreground">
            <Star className="size-3 fill-current" />
            {poi.rating.toFixed(1)}
          </span>
        )}
        {distance && (
          <span className="shrink-0 text-xs text-muted-foreground">{distance}</span>
        )}
      </span>
      {busyLevel && (
        <span
          className={cn(
            'ml-6 flex w-fit items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium',
            BUSYNESS_STYLE[busyLevel],
          )}
        >
          <Users className="size-3" />
          {busyLevel} (ước tính)
        </span>
      )}
    </button>
  );
}

export function ChatWidget({
  apiBaseUrl,
  sessionId,
  position,
  language,
  onViewPoi,
  onFocusLocation,
  onMapOverlay,
  onPickOnMap,
  onOpenVoice,
  onSimulatePosition,
  onSavedChanged,
  onOpenChange,
}: {
  apiBaseUrl: string;
  sessionId: string;
  position: { latitude: number; longitude: number };
  /** ngôn ngữ giao diện — tour thuyết minh đọc bằng ngôn ngữ này */
  language: string;
  onViewPoi: (poiId: string) => void;
  onFocusLocation: (latitude: number, longitude: number) => void;
  onMapOverlay: (overlay: AssistantOverlay | null) => void;
  onPickOnMap: (callback: ((latitude: number, longitude: number) => void) | null) => void;
  /** mở chế độ giọng nói (người khiếm thị) */
  onOpenVoice?: () => void;
  /** đặt vị trí mô phỏng khi trình diễn trên máy không có GPS */
  onSimulatePosition?: (latitude: number, longitude: number) => void;
  /** danh sách "Đã lưu" vừa đổi (vd vừa đặt nhà) — để thanh bên tải lại */
  onSavedChanged?: () => void;
  /** Báo cho bố cục chính dành một cột riêng cho trợ lý trên màn hình rộng. */
  onOpenChange?: (open: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const changeOpen = useCallback((next: boolean | ((current: boolean) => boolean)) => {
    setOpen((current) => {
      const value = typeof next === 'function' ? next(current) : next;
      onOpenChange?.(value);
      return value;
    });
  }, [onOpenChange]);
  const viewPoi = (poiId: string) => {
    if (window.innerWidth < 1280) changeOpen(false);
    onViewPoi(poiId);
  };
  const focusLocation = (latitude: number, longitude: number) => {
    if (window.innerWidth < 1280) changeOpen(false);
    onFocusLocation(latitude, longitude);
  };
  const pickOnMap = (callback: ((latitude: number, longitude: number) => void) | null) => {
    if (!callback) {
      onPickOnMap(null);
      return;
    }
    const restoreChat = window.innerWidth < 1280;
    if (restoreChat) changeOpen(false);
    onPickOnMap((latitude, longitude) => {
      callback(latitude, longitude);
      if (restoreChat) changeOpen(true);
    });
  };
  const [view, setView] = useState<'chat' | 'tour' | 'meetup' | 'explore' | 'history'>('chat');
  const [suggestions, setSuggestions] = useState<SuggestionsResponse | null>(null);
  const [suggestionsFailed, setSuggestionsFailed] = useState(false);
  const suggestedAtRef = useRef<{ at: number; latitude: number; longitude: number } | null>(null);
  // Tăng lên để buộc tải lại gợi ý (vd vừa lưu nhà → hiện chip "quán gần nhà").
  const [suggestionsVersion, setSuggestionsVersion] = useState(0);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [conversations, setConversations] = useState<SavedConversation<ChatTurn>[]>([]);
  // Cuộc đang mở: null = cuộc mới, chưa lưu lượt nào. Ref để effect lưu lịch
  // sử không phải chạy lại khi id vừa được cấp; state để danh sách tô "đang mở".
  const conversationIdRef = useRef<string | null>(null);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  // Danh sách lượt vừa mở lại từ lịch sử — chưa hỏi thêm gì thì không lưu
  // lại, kẻo chỉ mở xem thôi cũng đẩy cuộc cũ lên đầu "Hôm nay".
  const restoredTurnsRef = useRef<ChatTurn[] | null>(null);
  // `position` đổi liên tục khi có GPS (watchPosition) — chỉ cần toạ độ TẠI
  // LÚC gửi tin, không muốn effect nào chạy lại vì nó đổi.
  const positionRef = useRef(position);
  useEffect(() => {
    positionRef.current = position;
  }, [position]);

  const send = useCallback(async (text?: string) => {
    const message = (text ?? input).trim();
    if (!message || loading || !sessionId) return;
    if (text === undefined) setInput('');
    setTurns((prev) => [...prev, { role: 'user', content: message }]);
    setLoading(true);
    let started = false;
    // Sửa lượt trợ lý cuối cùng — chính lượt đang được stream.
    const updateReply = (patch: (turn: ChatTurn) => ChatTurn) =>
      setTurns((prev) => [...prev.slice(0, -1), patch(prev[prev.length - 1])]);
    const failMessage = 'Xin lỗi, trợ lý hiện không phản hồi được. Bạn thử lại sau ít phút nhé.';
    try {
      const response = await fetch(`${apiBaseUrl}/api/v1/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          message,
          latitude: positionRef.current.latitude,
          longitude: positionRef.current.longitude,
        }),
      });
      if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`);
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      const handle = (event: ChatStreamEvent) => {
        if (event.type === 'results') {
          started = true;
          setTurns((prev) => [
            ...prev,
            { role: 'assistant', content: '', results: event.results, pending: true },
          ]);
        } else if (event.type === 'delta') {
          updateReply((turn) => ({ ...turn, content: turn.content + event.text }));
        } else {
          updateReply((turn) => ({ ...turn, content: event.reply || turn.content, pending: false }));
        }
      };
      let chunk = await reader.read();
      while (!chunk.done) {
        buffer += decoder.decode(chunk.value, { stream: true });
        let newline = buffer.indexOf('\n');
        while (newline >= 0) {
          const line = buffer.slice(0, newline).trim();
          buffer = buffer.slice(newline + 1);
          if (line) handle(JSON.parse(line) as ChatStreamEvent);
          newline = buffer.indexOf('\n');
        }
        chunk = await reader.read();
      }
      if (!started) throw new Error('empty stream');
      // Stream đứt giữa chừng (mất mạng) mà chưa có chữ nào thì báo lỗi thay
      // vì để bong bóng trống mãi.
      updateReply((turn) => ({ ...turn, content: turn.content || failMessage, pending: false }));
    } catch {
      // Backend/Ollama tạm không tới được — nói thẳng, không bịa câu trả lời
      // giả như đang tìm kiếm thành công.
      if (started) {
        updateReply((turn) => ({ ...turn, content: turn.content || failMessage, pending: false }));
      } else {
        setTurns((prev) => [...prev, { role: 'assistant', content: failMessage }]);
      }
    } finally {
      setLoading(false);
    }
  }, [apiBaseUrl, input, loading, sessionId]);

  // Gợi ý theo vị trí + thời điểm: tải khi mở khung, tải lại khi đi xa hoặc
  // sau một lúc (lễ, giờ ăn, dự báo mưa đều đổi theo thời gian).
  useEffect(() => {
    if (!open) return;
    const last = suggestedAtRef.current;
    const moved = last ? distanceMeters(last, position) : Infinity;
    if (last && moved < SUGGESTION_MOVE_METERS && Date.now() - last.at < SUGGESTION_REFRESH_MS) return;
    suggestedAtRef.current = { at: Date.now(), ...position };
    const controller = new AbortController();
    const params = new URLSearchParams({ lat: String(position.latitude), lng: String(position.longitude) });
    // X-Session-ID: backend đọc địa chỉ "Nhà" đã lưu và tiến độ săn địa danh.
    fetch(`${apiBaseUrl}/api/v1/assistant/suggestions?${params}`, {
      signal: controller.signal,
      headers: { 'X-Session-ID': sessionId },
    })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json() as Promise<SuggestionsResponse>;
      })
      .then((data) => {
        setSuggestions(data);
        setSuggestionsFailed(false);
      })
      .catch(() => {
        // Lỗi thì cho phép thử lại (nút "Thử lại" hoặc lần mở sau). Bị huỷ vì
        // effect chạy lại thì không phải lỗi — lần tải mới đang chạy.
        suggestedAtRef.current = null;
        if (!controller.signal.aborted) setSuggestionsFailed(true);
      });
    return () => controller.abort();
  }, [apiBaseUrl, open, position, sessionId, suggestionsVersion]);

  // Nạp lịch sử ngay lúc render khi phiên đổi (không qua effect). An toàn với
  // hydrate: sessionId rỗng ở server và lần render đầu, chỉ có sau khi mount.
  const [conversationsSessionId, setConversationsSessionId] = useState('');
  if (sessionId !== conversationsSessionId) {
    setConversationsSessionId(sessionId);
    setConversations(sessionId ? loadConversations<ChatTurn>(sessionId) : []);
  }

  // Lưu cuộc đang mở vào lịch sử mỗi khi có lượt mới — đợi stream xong để
  // không ghi localStorage theo từng mẩu chữ.
  useEffect(() => {
    if (!sessionId || loading || turns.length === 0 || turns.some((turn) => turn.pending)) return;
    if (turns === restoredTurnsRef.current) return;
    let id = conversationIdRef.current;
    if (!id) {
      id = newConversationId();
      conversationIdRef.current = id;
      setActiveConversationId(id);
    }
    const saved: SavedConversation<ChatTurn> = { id, title: conversationTitle(turns), updatedAt: Date.now(), turns };
    setConversations((prev) => {
      const next = [saved, ...prev.filter((conversation) => conversation.id !== saved.id)].slice(0, MAX_CONVERSATIONS);
      saveConversations(sessionId, next);
      return next;
    });
  }, [loading, sessionId, turns]);

  /** Xoá cả lịch sử phía backend: không xoá thì câu hỏi đầu của cuộc mới vẫn
   * bị hiểu như câu nối tiếp ("còn chỗ nào khác không?"). Chỉ bấm được khi
   * không có lượt nào đang stream — stream sẽ ghi vào lượt cuối của danh sách. */
  const newConversation = () => {
    setTurns([]);
    conversationIdRef.current = null;
    setActiveConversationId(null);
    restoredTurnsRef.current = null;
    void fetch(`${apiBaseUrl}/api/v1/chat/history`, {
      method: 'DELETE',
      headers: { 'X-Session-ID': sessionId },
    }).catch(() => {
      // Xoá hụt thì lịch sử tự hết hạn sau 30 phút — không chặn người dùng.
    });
  };

  /** Mở lại cuộc cũ: hiện lại đủ thẻ địa điểm đã lưu, và nạp lại ngữ cảnh
   * phía backend để câu hỏi tiếp theo vẫn được hiểu là câu nối tiếp. */
  const openConversation = (conversation: SavedConversation<ChatTurn>) => {
    if (loading) return;
    restoredTurnsRef.current = conversation.turns;
    conversationIdRef.current = conversation.id;
    setActiveConversationId(conversation.id);
    setTurns(conversation.turns);
    setView('chat');
    void fetch(`${apiBaseUrl}/api/v1/chat/history`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'X-Session-ID': sessionId },
      body: JSON.stringify({
        turns: conversation.turns
          .filter((turn) => turn.content.trim())
          .slice(-RESTORE_TURNS)
          .map((turn) => ({ role: turn.role, content: turn.content.slice(0, RESTORE_CONTENT_CHARS) })),
      }),
    }).catch(() => {
      // Nạp hụt thì câu sau chỉ mất ngữ cảnh — vẫn trả lời được như câu mới.
    });
  };

  const deleteConversation = (id: string) => {
    setConversations((prev) => {
      const next = prev.filter((conversation) => conversation.id !== id);
      saveConversations(sessionId, next);
      return next;
    });
    if (id === conversationIdRef.current) newConversation();
  };

  const clearConversations = () => {
    setConversations([]);
    saveConversations(sessionId, []);
    if (conversationIdRef.current) newConversation();
  };

  const retrySuggestions = () => {
    setSuggestionsFailed(false);
    suggestedAtRef.current = null;
    setSuggestionsVersion((value) => value + 1);
  };

  // Chip ngữ cảnh (lễ, mưa, giờ ăn, nhà) tách khỏi chip tính năng: tính năng
  // đã có hàng cố định riêng, không lặp lại.
  const contextChips = (suggestions?.suggestions ?? []).filter((chip) => !FEATURE_KINDS.has(chip.kind));
  const featureChips = FEATURE_CHIPS.filter((chip) => chip.kind !== 'voice' || onOpenVoice).map((chip) => {
    const live = suggestions?.suggestions.find((item) => item.kind === chip.kind);
    return live ? { ...chip, subtitle: live.subtitle } : chip;
  });

  /** Tìm trực tiếp theo category quanh một toạ độ (tiệm hoa, quán gần nhà) —
   * pipeline xếp hạng thật, không qua LLM nên chạy cả khi Ollama tắt. */
  const runSearch = useCallback(
    async (action: SearchAction) => {
      setLoading(true);
      try {
        const params = new URLSearchParams({
          lat: String(action.latitude),
          lng: String(action.longitude),
          radius: String(action.radius),
          limit: String(MAX_RESULT_CARDS),
        });
        if (action.category) params.set('category', action.category);
        // Category đã đủ để lọc trực tiếp. Chỉ gửi q khi không biết category;
        // q kích hoạt semantic search/embedding và chậm hơn đáng kể.
        if (action.query && !action.category) params.set('q', action.query);
        const res = await fetch(`${apiBaseUrl}/api/pois/nearby?${params}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const results = (await res.json()) as ChatPoiResult[];
        const radius = formatMeters(action.radius);
        setTurns((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: results.length
              ? `${action.title}: ${results.length} địa điểm trong bán kính ${radius}, xếp theo độ phù hợp và khoảng cách.`
              : `Chưa có địa điểm nào phù hợp trong bán kính ${radius}.`,
            results,
          },
        ]);
      } catch {
        setTurns((prev) => [
          ...prev,
          { role: 'assistant', content: 'Xin lỗi, chưa tìm được lúc này. Bạn thử lại sau ít phút nhé.' },
        ]);
      } finally {
        setLoading(false);
      }
    },
    [apiBaseUrl],
  );

  const setHomeHere = useCallback(async () => {
    const here = positionRef.current;
    try {
      const res = await fetch(`${apiBaseUrl}/api/v1/saved`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Session-ID': sessionId },
        body: JSON.stringify({ kind: 'home', label: 'Nhà', latitude: here.latitude, longitude: here.longitude }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setTurns((prev) => [
        ...prev,
        { role: 'assistant', content: '🏠 Đã lưu vị trí hiện tại làm Nhà. Từ giờ mình sẽ gợi ý quán ăn quanh nhà cho bạn.' },
      ]);
      suggestedAtRef.current = null;
      setSuggestionsVersion((value) => value + 1);
      onSavedChanged?.();
    } catch {
      setTurns((prev) => [...prev, { role: 'assistant', content: 'Chưa lưu được địa chỉ nhà, bạn thử lại nhé.' }]);
    }
  }, [apiBaseUrl, onSavedChanged, sessionId]);

  const pickSuggestion = useCallback(
    (suggestion: Suggestion) => {
      const action = suggestion.action;
      if (action.type === 'ask') {
        void send(action.prompt);
      } else if (action.type === 'search') {
        setTurns((prev) => [...prev, { role: 'user', content: `${suggestion.icon} ${suggestion.title}` }]);
        void runSearch(action);
      } else if (action.type === 'set_home') {
        setTurns((prev) => [
          ...prev,
          { role: 'user', content: `${suggestion.icon} ${suggestion.title}` },
          {
            role: 'assistant',
            content:
              'Bạn đang ở nhà? Bấm nút dưới để lưu vị trí hiện tại làm Nhà. Hoặc mở một địa điểm trên bản đồ và chọn “Đặt làm nhà”.',
            offerSetHome: true,
          },
        ]);
      } else if (action.type === 'tour') {
        setView('tour');
      } else if (action.type === 'explore') {
        setView('explore');
      } else if (action.type === 'voice') {
        onOpenVoice?.();
      } else if (action.type === 'meetup') {
        setView('meetup');
      } else {
        // Sự kiện: trả lời tại chỗ bằng dữ liệu lịch — không qua LLM, không bịa.
        const event = action.event;
        const when =
          event.daysUntil === 0
            ? 'hôm nay'
            : event.daysUntil === 1
              ? 'ngày mai'
              : `còn ${event.daysUntil} ngày (${event.date.split('-').reverse().join('/')})`;
        setTurns((prev) => [
          ...prev,
          { role: 'user', content: `${suggestion.icon} ${event.name}?` },
          {
            role: 'assistant',
            content: `${event.name} — ${when}${event.lunar ? ', tính theo âm lịch' : ''}. ${event.note}`,
            places: event.places,
            // Có cửa hàng thật để gợi ý (tiệm hoa, tiệm vàng) thì nút tìm trực
            // tiếp thay cho câu hỏi gửi LLM.
            search: event.search ?? null,
            followUp: event.search ? null : (event.ask ?? null),
          },
        ]);
      }
    },
    [onOpenVoice, runSearch, send],
  );

  return (
    <>
      {/* z-40: trên panel chi tiết POI (z-30) — chatbot phải luôn bấm được dù
          panel đang mở. */}
      <Button
        type="button"
        size="icon"
        onClick={() => changeOpen((value) => !value)}
        aria-label={open ? 'Đóng trợ lý' : 'Mở trợ lý tìm kiếm'}
        className="chat-launcher fixed right-4 bottom-4 z-40 size-12 rounded-full shadow-lg sm:right-6 sm:bottom-6"
      >
        {open ? <X className="size-5" /> : <MessageCircle className="size-5" />}
      </Button>

      {/* Luôn giữ khung trong DOM, chỉ ẩn đi khi đóng: tour đang thuyết minh
          phải tiếp tục đọc khi người dùng thu nhỏ trợ lý để nhìn bản đồ. */}
      <div
        className={cn(
          'chat-panel fixed inset-0 z-40 flex h-dvh min-h-0 flex-col overflow-hidden border border-border bg-card shadow-2xl sm:inset-x-auto sm:top-auto sm:right-6 sm:bottom-24 sm:h-[min(620px,calc(100dvh-8rem))] sm:w-96 sm:rounded-xl xl:static xl:z-auto xl:h-full xl:max-h-none xl:min-h-0 xl:w-full xl:rounded-[26px] xl:shadow-[0_18px_60px_rgb(14_68_48/12%)]',
          !open && 'hidden',
        )}
      >
        <div className="flex shrink-0 items-center justify-between border-b border-border px-4 py-3">
          <div className="min-w-0">
            <p className="flex items-baseline gap-2 text-sm font-semibold">
              Trợ lý Nearby
              {suggestions?.lunarDate && (
                <span className="truncate text-[11px] font-normal text-muted-foreground">
                  Âm lịch {suggestions.lunarDate}
                </span>
              )}
            </p>
            <p className="text-xs text-muted-foreground">Hỏi bằng lời — mình tìm địa điểm thật gần bạn</p>
          </div>
          <div className="flex shrink-0 items-center">
            {view === 'chat' && (
              <Button
                type="button"
                size="icon"
                variant="ghost"
                onClick={() => setView('history')}
                aria-label="Lịch sử trò chuyện"
                title="Lịch sử trò chuyện"
              >
                <History className="size-4" />
              </Button>
            )}
            {view === 'chat' && turns.length > 0 && (
              <Button
                type="button"
                size="icon"
                variant="ghost"
                onClick={newConversation}
                disabled={loading}
                aria-label="Cuộc trò chuyện mới"
                title="Cuộc trò chuyện mới"
              >
                <SquarePen className="size-4" />
              </Button>
            )}
            <Button
              type="button"
              size="icon"
              variant="ghost"
              onClick={() => changeOpen(false)}
              aria-label="Đóng"
            >
              <X className="size-4" />
            </Button>
          </div>
        </div>

        {view === 'history' ? (
          <ChatHistory
            conversations={conversations}
            activeId={activeConversationId}
            disabled={loading}
            onOpen={openConversation}
            onDelete={deleteConversation}
            onClear={clearConversations}
            onBack={() => setView('chat')}
          />
        ) : view === 'tour' ? (
          <AssistantTour
            apiBaseUrl={apiBaseUrl}
            position={position}
            language={language}
            onBack={() => setView('chat')}
            onViewPoi={viewPoi}
            onMapOverlay={onMapOverlay}
            onFocusLocation={focusLocation}
          />
        ) : view === 'meetup' ? (
          <AssistantMeetup
            apiBaseUrl={apiBaseUrl}
            position={position}
            onBack={() => setView('chat')}
            onViewPoi={viewPoi}
            onMapOverlay={onMapOverlay}
            onPickOnMap={pickOnMap}
          />
        ) : view === 'explore' ? (
          <AssistantExplore
            apiBaseUrl={apiBaseUrl}
            sessionId={sessionId}
            position={position}
            language={language}
            onBack={() => {
              setView('chat');
              // Tiến độ vừa đổi → chip "Săn địa danh" cần số mới.
              suggestedAtRef.current = null;
              setSuggestionsVersion((value) => value + 1);
            }}
            onViewPoi={viewPoi}
            onMapOverlay={onMapOverlay}
            onFocusLocation={focusLocation}
            onPickOnMap={pickOnMap}
            onSimulatePosition={onSimulatePosition}
          />
        ) : (
          <>
            <MessageScrollerProvider>
              <MessageScroller className="min-h-0 flex-1">
                <MessageScrollerViewport className="px-4 py-3">
                  <MessageScrollerContent>
                    {turns.length === 0 && (
                      <div className="space-y-4 py-2">
                        <div className="space-y-2">
                          <p className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
                            <Sparkles className="size-3.5 text-primary" aria-hidden />
                            Gợi ý cho bạn lúc này
                          </p>
                          {suggestions ? (
                            contextChips.map((suggestion) => (
                              <SuggestionChip
                                key={suggestion.id}
                                suggestion={suggestion}
                                onPick={pickSuggestion}
                                large
                              />
                            ))
                          ) : suggestionsFailed ? (
                            <div className="flex items-center justify-between gap-2 rounded-xl border border-dashed border-border px-3 py-2.5 text-xs text-muted-foreground">
                              <span>Chưa tải được gợi ý theo vị trí.</span>
                              <button
                                type="button"
                                onClick={retrySuggestions}
                                className="flex shrink-0 items-center gap-1 font-semibold text-primary hover:underline"
                              >
                                <RotateCw className="size-3" />
                                Thử lại
                              </button>
                            </div>
                          ) : (
                            <p className="flex items-center gap-2 px-1 py-2.5 text-xs text-muted-foreground">
                              <Spinner className="size-3.5" />
                              Đang xem quanh bạn có gì: lễ sắp tới, thời tiết, giờ ăn…
                            </p>
                          )}
                          <button
                            type="button"
                            onClick={() => void send(SAMPLE_QUESTION)}
                            disabled={loading}
                            className="flex w-fit items-center gap-1.5 rounded-full border border-primary/30 px-3 py-1.5 text-xs font-medium text-primary transition hover:bg-primary/5"
                          >
                            <MessageCircle className="size-3.5" />
                            Thử hỏi: “{SAMPLE_QUESTION.toLowerCase()}”
                          </button>
                          {suggestions && !suggestions.calendarAvailable && (
                            <p className="text-[11px] text-muted-foreground">
                              Lịch lễ hội hiện chỉ có cho Việt Nam.
                            </p>
                          )}
                        </div>
                        <div className="space-y-2">
                          <p className="text-xs font-semibold text-muted-foreground">Tính năng của trợ lý</p>
                          <div className="grid grid-cols-2 gap-2">
                            {featureChips.map((suggestion) => (
                              <SuggestionChip
                                key={suggestion.id}
                                suggestion={suggestion}
                                onPick={pickSuggestion}
                                large
                              />
                            ))}
                          </div>
                        </div>
                        {conversations.length > 0 && (
                          <div className="space-y-2">
                            <div className="flex items-center justify-between">
                              <p className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
                                <History className="size-3.5" aria-hidden />
                                Trò chuyện gần đây
                              </p>
                              <button
                                type="button"
                                onClick={() => setView('history')}
                                className="text-xs font-medium text-primary hover:underline"
                              >
                                Xem tất cả
                              </button>
                            </div>
                            {conversations.slice(0, RECENT_CONVERSATIONS).map((conversation) => (
                              <button
                                key={conversation.id}
                                type="button"
                                onClick={() => openConversation(conversation)}
                                disabled={loading}
                                className="flex w-full items-center gap-2 rounded-xl border border-border bg-background px-3 py-2 text-left transition hover:border-primary/40 hover:bg-muted"
                              >
                                <MessageCircle className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                                <span className="min-w-0 flex-1 truncate text-xs font-medium">{conversation.title}</span>
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                    {turns.map((turn, index) => (
                      <MessageScrollerItem key={index}>
                        <Message align={turn.role === 'user' ? 'end' : 'start'}>
                          <MessageContent>
                            <BubbleGroup>
                              <Bubble align={turn.role === 'user' ? 'end' : 'start'}>
                                <BubbleContent
                                  className={cn(
                                    turn.role === 'user'
                                      ? 'bg-primary text-primary-foreground'
                                      : 'bg-muted',
                                  )}
                                >
                                  {turn.pending && !turn.content ? (
                                    <span className="flex items-center gap-2 text-muted-foreground">
                                      <Spinner className="size-3.5" />
                                      Đang viết câu trả lời…
                                    </span>
                                  ) : (
                                    turn.content
                                  )}
                                </BubbleContent>
                              </Bubble>
                            </BubbleGroup>
                            {turn.results && turn.results.length > 0 && (
                              <div className="flex w-full flex-col gap-1.5 pt-1">
                                {turn.results.slice(0, MAX_RESULT_CARDS).map((poi) => (
                                  <ChatPoiCard key={poi.id} poi={poi} onView={viewPoi} />
                                ))}
                              </div>
                            )}
                            {turn.places && turn.places.length > 0 && (
                              <div className="flex w-full flex-col gap-1.5 pt-1">
                                {turn.places.map((place) => (
                                  <PlaceCard
                                    key={place.poiId ?? place.name}
                                    place={place}
                                    onView={viewPoi}
                                    onFocus={focusLocation}
                                  />
                                ))}
                              </div>
                            )}
                            {turn.followUp && (
                              <button
                                type="button"
                                onClick={() => void send(turn.followUp!)}
                                className="mt-1 w-fit rounded-full border border-primary/30 px-2.5 py-1 text-xs font-medium text-primary hover:bg-primary/5"
                              >
                                {turn.followUp} →
                              </button>
                            )}
                            {turn.search && (
                              <button
                                type="button"
                                onClick={() => void runSearch(turn.search!)}
                                disabled={loading}
                                className="mt-1 flex w-fit items-center gap-1 rounded-full border border-primary/30 px-2.5 py-1 text-xs font-medium text-primary hover:bg-primary/5"
                              >
                                <Search className="size-3" />
                                Xem {turn.search.title.toLowerCase()}
                                {turn.search.count ? ` (${turn.search.count})` : ''} →
                              </button>
                            )}
                            {turn.offerSetHome && (
                              <button
                                type="button"
                                onClick={() => void setHomeHere()}
                                className="mt-1 flex w-fit items-center gap-1 rounded-full bg-primary px-3 py-1 text-xs font-semibold text-primary-foreground hover:bg-primary/90"
                              >
                                <Home className="size-3" />
                                Đặt vị trí hiện tại làm Nhà
                              </button>
                            )}
                          </MessageContent>
                        </Message>
                      </MessageScrollerItem>
                    ))}
                    {loading && !turns.at(-1)?.pending && (
                      <MessageScrollerItem>
                        <Message align="start">
                          <MessageContent>
                            <BubbleGroup>
                              <Bubble align="start">
                                <BubbleContent className="bg-secondary text-secondary-foreground">
                                  <span className="flex items-center gap-2 text-secondary-foreground">
                                    <Spinner className="size-3.5" />
                                    Đang tìm kiếm…
                                  </span>
                                </BubbleContent>
                              </Bubble>
                            </BubbleGroup>
                          </MessageContent>
                        </Message>
                      </MessageScrollerItem>
                    )}
                  </MessageScrollerContent>
                </MessageScrollerViewport>
              </MessageScroller>
            </MessageScrollerProvider>

            {turns.length > 0 && (
              <div className="flex shrink-0 gap-1.5 overflow-x-auto border-t border-border px-3 pt-2">
                {[...contextChips, ...featureChips].map((suggestion) => (
                  <SuggestionChip key={suggestion.id} suggestion={suggestion} onPick={pickSuggestion} />
                ))}
              </div>
            )}

            <form
              className="flex shrink-0 items-center gap-2 p-3"
              onSubmit={(event) => {
                event.preventDefault();
                void send();
              }}
            >
              <Input
                className="min-w-0 flex-1"
                value={input}
                onChange={(event) => setInput(event.target.value)}
                placeholder="Bạn muốn tìm gì gần đây?"
              />
              <Button type="submit" size="icon" aria-label="Gửi tin nhắn" disabled={loading || !input.trim()}>
                <Send className="size-4" />
              </Button>
            </form>
          </>
        )}
      </div>
    </>
  );
}

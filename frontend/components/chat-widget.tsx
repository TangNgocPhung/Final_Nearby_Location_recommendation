'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { MapPin, MessageCircle, Send, Sparkles, Star, Users, X } from 'lucide-react';

import { AssistantMeetup } from '@/components/assistant-meetup';
import { AssistantTour } from '@/components/assistant-tour';

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

type ChatResponse = {
  reply: string;
  needsClarification: boolean;
  searchParams: { query: string; category: string | null; radius: number } | null;
  results: ChatPoiResult[];
};

type ChatTurn = {
  role: 'user' | 'assistant';
  content: string;
  results?: ChatPoiResult[];
  /** địa điểm gắn với một gợi ý sự kiện (có thể là con phố, không có poiId) */
  places?: PlaceRef[];
  /** câu hỏi gợi ý tiếp theo, bấm là gửi cho chatbot */
  followUp?: string | null;
};

// Tải lại gợi ý khi người dùng đi xa hơn mức này, hoặc sau REFRESH_MS.
const SUGGESTION_MOVE_METERS = 1000;
const SUGGESTION_REFRESH_MS = 10 * 60 * 1000;

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

function formatDistance(meters: number | null | undefined): string | null {
  if (meters == null) return null;
  return meters < 1000 ? `${Math.round(meters)} m` : `${(meters / 1000).toFixed(1)} km`;
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
  const distance = formatDistance(poi.distanceMeters);
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
}) {
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<'chat' | 'tour' | 'meetup'>('chat');
  const [suggestions, setSuggestions] = useState<SuggestionsResponse | null>(null);
  const suggestedAtRef = useRef<{ at: number; latitude: number; longitude: number } | null>(null);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
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
    try {
      const response = await fetch(`${apiBaseUrl}/api/v1/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          message,
          latitude: positionRef.current.latitude,
          longitude: positionRef.current.longitude,
        }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data: ChatResponse = await response.json();
      setTurns((prev) => [
        ...prev,
        { role: 'assistant', content: data.reply, results: data.results },
      ]);
    } catch {
      // Backend/Ollama tạm không tới được — nói thẳng, không bịa câu trả lời
      // giả như đang tìm kiếm thành công.
      setTurns((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: 'Xin lỗi, trợ lý hiện không phản hồi được. Bạn thử lại sau ít phút nhé.',
        },
      ]);
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
    fetch(`${apiBaseUrl}/api/v1/assistant/suggestions?${params}`, { signal: controller.signal })
      .then((res) => (res.ok ? (res.json() as Promise<SuggestionsResponse>) : null))
      .then((data) => {
        if (data) setSuggestions(data);
      })
      .catch(() => {
        // Lỗi thì cho phép thử lại lần mở sau.
        suggestedAtRef.current = null;
      });
    return () => controller.abort();
  }, [apiBaseUrl, open, position]);

  const pickSuggestion = useCallback(
    (suggestion: Suggestion) => {
      const action = suggestion.action;
      if (action.type === 'ask') {
        void send(action.prompt);
      } else if (action.type === 'tour') {
        setView('tour');
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
            followUp: event.ask ?? null,
          },
        ]);
      }
    },
    [send],
  );

  return (
    <>
      {/* z-40: trên panel chi tiết POI (z-30) — chatbot phải luôn bấm được dù
          panel đang mở. */}
      <Button
        type="button"
        size="icon"
        onClick={() => setOpen((value) => !value)}
        aria-label={open ? 'Đóng trợ lý' : 'Mở trợ lý tìm kiếm'}
        className="fixed right-4 bottom-4 z-40 size-12 rounded-full shadow-lg sm:right-6 sm:bottom-6"
      >
        {open ? <X className="size-5" /> : <MessageCircle className="size-5" />}
      </Button>

      {/* Luôn giữ khung trong DOM, chỉ ẩn đi khi đóng: tour đang thuyết minh
          phải tiếp tục đọc khi người dùng thu nhỏ trợ lý để nhìn bản đồ. */}
      <div
        className={cn(
          'fixed inset-x-4 bottom-20 z-40 flex h-[70vh] max-h-[600px] flex-col overflow-hidden rounded-xl border border-border bg-card shadow-2xl sm:right-6 sm:bottom-24 sm:left-auto sm:w-96',
          !open && 'hidden',
        )}
      >
        <div className="flex shrink-0 items-center justify-between border-b border-border px-4 py-3">
          <div>
            <p className="text-sm font-semibold">Trợ lý Nearby</p>
            <p className="text-xs text-muted-foreground">
              {suggestions?.lunarDate
                ? `Âm lịch ${suggestions.lunarDate}`
                : 'Hỏi bằng lời — mình tìm địa điểm thật gần bạn'}
            </p>
          </div>
          <Button
            type="button"
            size="icon"
            variant="ghost"
            onClick={() => setOpen(false)}
            aria-label="Đóng"
          >
            <X className="size-4" />
          </Button>
        </div>

        {view === 'tour' ? (
          <AssistantTour
            apiBaseUrl={apiBaseUrl}
            position={position}
            language={language}
            onBack={() => setView('chat')}
            onViewPoi={onViewPoi}
            onMapOverlay={onMapOverlay}
            onFocusLocation={onFocusLocation}
          />
        ) : view === 'meetup' ? (
          <AssistantMeetup
            apiBaseUrl={apiBaseUrl}
            position={position}
            onBack={() => setView('chat')}
            onViewPoi={onViewPoi}
            onMapOverlay={onMapOverlay}
            onPickOnMap={onPickOnMap}
          />
        ) : (
          <>
            <MessageScrollerProvider>
              <MessageScroller className="min-h-0 flex-1">
                <MessageScrollerViewport className="px-4 py-3">
                  <MessageScrollerContent>
                    {turns.length === 0 && (
                      <div className="space-y-2 py-2">
                        <p className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
                          <Sparkles className="size-3.5 text-primary" aria-hidden />
                          Gợi ý cho bạn lúc này
                        </p>
                        {suggestions ? (
                          suggestions.suggestions.map((suggestion) => (
                            <SuggestionChip
                              key={suggestion.id}
                              suggestion={suggestion}
                              onPick={pickSuggestion}
                              large
                            />
                          ))
                        ) : (
                          <p className="py-4 text-center text-sm text-muted-foreground">
                            Thử hỏi: &quot;quán cà phê yên tĩnh gần đây&quot;
                          </p>
                        )}
                        {suggestions && !suggestions.calendarAvailable && (
                          <p className="text-[11px] text-muted-foreground">
                            Lịch lễ hội hiện chỉ có cho Việt Nam.
                          </p>
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
                                  {turn.content}
                                </BubbleContent>
                              </Bubble>
                            </BubbleGroup>
                            {turn.results && turn.results.length > 0 && (
                              <div className="flex w-full flex-col gap-1.5 pt-1">
                                {turn.results.slice(0, 5).map((poi) => (
                                  <ChatPoiCard key={poi.id} poi={poi} onView={onViewPoi} />
                                ))}
                              </div>
                            )}
                            {turn.places && turn.places.length > 0 && (
                              <div className="flex w-full flex-col gap-1.5 pt-1">
                                {turn.places.map((place) => (
                                  <PlaceCard
                                    key={place.poiId ?? place.name}
                                    place={place}
                                    onView={onViewPoi}
                                    onFocus={onFocusLocation}
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
                          </MessageContent>
                        </Message>
                      </MessageScrollerItem>
                    ))}
                    {loading && (
                      <MessageScrollerItem>
                        <Message align="start">
                          <MessageContent>
                            <BubbleGroup>
                              <Bubble align="start">
                                <BubbleContent className="bg-muted">
                                  <span className="flex items-center gap-2 text-muted-foreground">
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

            {turns.length > 0 && suggestions && suggestions.suggestions.length > 0 && (
              <div className="flex shrink-0 gap-1.5 overflow-x-auto border-t border-border px-3 pt-2">
                {suggestions.suggestions.map((suggestion) => (
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
                value={input}
                onChange={(event) => setInput(event.target.value)}
                placeholder="Bạn muốn tìm gì gần đây?"
                disabled={loading}
              />
              <Button type="submit" size="icon" disabled={loading || !input.trim()}>
                <Send className="size-4" />
              </Button>
            </form>
          </>
        )}
      </div>
    </>
  );
}

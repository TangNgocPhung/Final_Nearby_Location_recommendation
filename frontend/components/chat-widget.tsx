'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { MapPin, MessageCircle, Send, Star, Users, X } from 'lucide-react';

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
};

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
  onViewPoi,
}: {
  apiBaseUrl: string;
  sessionId: string;
  position: { latitude: number; longitude: number };
  onViewPoi: (poiId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  // `position` đổi liên tục khi có GPS (watchPosition) — chỉ cần toạ độ TẠI
  // LÚC gửi tin, không muốn effect nào chạy lại vì nó đổi.
  const positionRef = useRef(position);
  useEffect(() => {
    positionRef.current = position;
  }, [position]);

  const send = useCallback(async () => {
    const message = input.trim();
    if (!message || loading || !sessionId) return;
    setInput('');
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

      {open && (
        <div className="fixed inset-x-4 bottom-20 z-40 flex h-[70vh] max-h-[560px] flex-col overflow-hidden rounded-xl border border-border bg-card shadow-2xl sm:right-6 sm:bottom-24 sm:left-auto sm:w-96">
          <div className="flex shrink-0 items-center justify-between border-b border-border px-4 py-3">
            <div>
              <p className="text-sm font-semibold">Trợ lý Nearby</p>
              <p className="text-xs text-muted-foreground">
                Hỏi bằng lời — mình tìm địa điểm thật gần bạn
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

          <MessageScrollerProvider>
            <MessageScroller className="min-h-0 flex-1">
              <MessageScrollerViewport className="px-4 py-3">
                <MessageScrollerContent>
                  {turns.length === 0 && (
                    <p className="py-6 text-center text-sm text-muted-foreground">
                      Thử hỏi: &quot;quán cà phê yên tĩnh gần đây&quot;
                    </p>
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

          <form
            className="flex shrink-0 items-center gap-2 border-t border-border p-3"
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
        </div>
      )}
    </>
  );
}

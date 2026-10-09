'use client';

import { useMemo, useState } from 'react';
import { ArrowLeft, History, MessageCircle, Search, Trash2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';

/* ------------------------------------------------------------------ *
 * Lịch sử chat của trợ lý — lưu ở trình duyệt (localStorage), không cần
 * đăng nhập. Backend chỉ giữ ngữ cảnh của cuộc đang mở trong 30 phút; mở lại
 * cuộc cũ thì khung chat gọi PUT /api/v1/chat/history để nạp lại ngữ cảnh.
 * ------------------------------------------------------------------ */

export type SavedConversation<Turn> = {
  id: string;
  title: string;
  /** epoch ms của lượt cuối */
  updatedAt: number;
  turns: Turn[];
};

const STORAGE_PREFIX = 'nearby:chat:conversations';
// Giữ chừng này cuộc gần nhất — mỗi cuộc kèm cả thẻ địa điểm nên không giữ vô hạn.
export const MAX_CONVERSATIONS = 30;
const TITLE_MAX_CHARS = 60;

const storageKey = (sessionId: string) => `${STORAGE_PREFIX}:${sessionId}`;

export function loadConversations<Turn>(sessionId: string): SavedConversation<Turn>[] {
  try {
    const raw = window.localStorage.getItem(storageKey(sessionId));
    const parsed = raw ? (JSON.parse(raw) as SavedConversation<Turn>[]) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    // Chế độ ẩn danh/chặn dữ liệu trang: chạy như chưa có lịch sử.
    return [];
  }
}

export function saveConversations<Turn>(sessionId: string, conversations: SavedConversation<Turn>[]) {
  try {
    const key = storageKey(sessionId);
    if (conversations.length) window.localStorage.setItem(key, JSON.stringify(conversations));
    else window.localStorage.removeItem(key);
  } catch {
    // Đầy bộ nhớ hoặc bị chặn — mất lịch sử không được làm hỏng khung chat.
  }
}

export function conversationTitle(turns: { role: string; content: string }[]): string {
  const first = turns.find((turn) => turn.role === 'user')?.content.trim() ?? 'Cuộc trò chuyện';
  return first.length > TITLE_MAX_CHARS ? `${first.slice(0, TITLE_MAX_CHARS - 1)}…` : first;
}

export function newConversationId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

const DAY_MS = 24 * 60 * 60 * 1000;

function startOfDay(time: number) {
  const date = new Date(time);
  date.setHours(0, 0, 0, 0);
  return date.getTime();
}

function groupLabel(updatedAt: number, now: number) {
  const days = Math.round((startOfDay(now) - startOfDay(updatedAt)) / DAY_MS);
  if (days <= 0) return 'Hôm nay';
  if (days === 1) return 'Hôm qua';
  if (days < 7) return '7 ngày qua';
  return 'Cũ hơn';
}

function timeLabel(updatedAt: number, now: number) {
  const minutes = Math.floor((now - updatedAt) / 60_000);
  if (minutes < 1) return 'Vừa xong';
  if (minutes < 60) return `${minutes} phút trước`;
  const date = new Date(updatedAt);
  if (startOfDay(now) === startOfDay(updatedAt)) {
    return date.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' });
  }
  return date.toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit', year: 'numeric' });
}

export function ChatHistory<Turn extends { role: string; content: string }>({
  conversations,
  activeId,
  disabled,
  onOpen,
  onDelete,
  onClear,
  onBack,
}: {
  conversations: SavedConversation<Turn>[];
  activeId: string | null;
  /** đang có lượt stream — chưa cho đổi cuộc trò chuyện */
  disabled?: boolean;
  onOpen: (conversation: SavedConversation<Turn>) => void;
  onDelete: (id: string) => void;
  onClear: () => void;
  onBack: () => void;
}) {
  const [query, setQuery] = useState('');
  const groups = useMemo(() => {
    const now = Date.now();
    const needle = query.trim().toLowerCase();
    const matched = conversations
      .filter(
        (conversation) =>
          !needle || conversation.turns.some((turn) => turn.content.toLowerCase().includes(needle)),
      )
      .sort((a, b) => b.updatedAt - a.updatedAt);
    const byLabel = new Map<string, { conversation: SavedConversation<Turn>; time: string }[]>();
    for (const conversation of matched) {
      const label = groupLabel(conversation.updatedAt, now);
      const items = byLabel.get(label) ?? [];
      items.push({ conversation, time: timeLabel(conversation.updatedAt, now) });
      byLabel.set(label, items);
    }
    return [...byLabel.entries()];
  }, [conversations, query]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2">
        <Button type="button" size="icon" variant="ghost" onClick={onBack} aria-label="Quay lại trò chuyện">
          <ArrowLeft className="size-4" />
        </Button>
        <History className="size-4 text-primary" aria-hidden />
        <p className="min-w-0 flex-1 text-sm font-semibold">Lịch sử trò chuyện</p>
        {conversations.length > 0 && (
          <button
            type="button"
            onClick={() => {
              if (window.confirm('Xoá toàn bộ lịch sử trò chuyện trên máy này?')) onClear();
            }}
            disabled={disabled}
            className="shrink-0 text-xs font-medium text-muted-foreground hover:text-destructive disabled:opacity-50"
          >
            Xoá tất cả
          </button>
        )}
      </div>

      {conversations.length > 0 && (
        <div className="shrink-0 px-4 pt-3">
          <div className="relative">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Tìm trong lịch sử…"
              className="h-8 pl-8 text-sm"
            />
          </div>
        </div>
      )}

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-3">
        {conversations.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-10 text-center text-sm text-muted-foreground">
            <MessageCircle className="size-8 opacity-40" aria-hidden />
            <p>Chưa có cuộc trò chuyện nào.</p>
            <p className="text-xs">Các câu bạn hỏi trợ lý sẽ được lưu ở đây, ngay trên máy này.</p>
          </div>
        ) : groups.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">Không có cuộc nào khớp “{query}”.</p>
        ) : (
          groups.map(([label, items]) => (
            <div key={label} className="space-y-1.5">
              <p className="text-xs font-semibold text-muted-foreground">{label}</p>
              {items.map(({ conversation, time }) => {
                const active = conversation.id === activeId;
                const count = conversation.turns.filter((turn) => turn.role === 'user').length;
                return (
                  <div
                    key={conversation.id}
                    className={cn(
                      'group flex items-center gap-1 rounded-xl border transition',
                      active
                        ? 'border-primary/40 bg-primary/5'
                        : 'border-border bg-background hover:border-primary/40 hover:bg-muted',
                    )}
                  >
                    <button
                      type="button"
                      onClick={() => onOpen(conversation)}
                      disabled={disabled}
                      className="min-w-0 flex-1 px-3 py-2 text-left disabled:opacity-60"
                    >
                      <span className="block truncate text-sm font-medium">{conversation.title}</span>
                      <span className="block truncate text-[11px] text-muted-foreground">
                        {time} · {count} câu hỏi{active ? ' · đang mở' : ''}
                      </span>
                    </button>
                    <Button
                      type="button"
                      size="icon"
                      variant="ghost"
                      onClick={() => onDelete(conversation.id)}
                      disabled={disabled}
                      aria-label={`Xoá cuộc trò chuyện “${conversation.title}”`}
                      title="Xoá"
                      className="mr-1 size-8 shrink-0 text-muted-foreground opacity-60 group-hover:opacity-100 hover:text-destructive"
                    >
                      <Trash2 className="size-3.5" />
                    </Button>
                  </div>
                );
              })}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Accessibility, Check, Mic, MicOff, RotateCcw, X } from 'lucide-react';

import { useMicLevel } from '@/hooks/use-mic-level';
import { getRecognition, recognitionLang, type SpeechRecognitionLike } from '@/lib/speech-recognition';
import { cn } from '@/lib/utils';
import { VoiceCues } from '@/lib/voice-cues';

/**
 * Tìm nhanh bằng giọng nói: bấm micro → nói "cà phê gần đây" → ô tìm kiếm được
 * điền và tìm luôn. Bảng nhỏ nổi trên bản đồ, không che cả màn hình như chế độ
 * giọng nói cho người khiếm thị (voice-mode.tsx) — chế độ đó vẫn mở được từ đây
 * hoặc bằng Alt+V.
 */

type Status = 'listening' | 'heard' | 'nothing' | 'denied' | 'error' | 'unsupported';

const EXAMPLES = ['Cà phê', 'Quán phở', 'ATM', 'Nhà thuốc', 'Công viên'];

// Từ đệm ở đầu/cuối câu nói — khớp `_FILLERS` của backend/app/voice.py. Chỉ bỏ ở
// hai đầu câu: "gần Bến Thành" ở giữa câu là thông tin vị trí, phải giữ.
const LEADING_FILLERS = /^(?:(?:hãy|làm ơn)\s+)?(?:tìm kiếm|tìm giúp tôi|tìm cho tôi|tìm giúp|tìm|cho tôi xem|cho tôi|tôi muốn tìm|tôi muốn|tôi cần)\s+/iu;
const TRAILING_FILLERS = /\s+(?:ở gần đây|gần đây|quanh đây|ở đâu|nào)$/iu;

/** "Tìm cho tôi quán phở gần đây." → "quán phở". Câu chỉ toàn từ đệm thì giữ nguyên. */
export function cleanSpokenQuery(text: string): string {
  const trimmed = text.trim().replace(/[.?!,]+$/u, '');
  const cleaned = trimmed.replace(LEADING_FILLERS, '').replace(TRAILING_FILLERS, '').trim();
  return cleaned || trimmed;
}

export function VoiceSearch({
  language,
  onResult,
  onOpenFullMode,
  onClose,
}: {
  language: string;
  onResult: (query: string) => void;
  onOpenFullMode: () => void;
  onClose: () => void;
}) {
  const [status, setStatus] = useState<Status>('listening');
  const [interim, setInterim] = useState('');
  const [heard, setHeard] = useState('');
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const orbRef = useRef<HTMLButtonElement>(null);
  const doneTimerRef = useRef(0);
  const [cues] = useState(() => new VoiceCues());
  // Gọi qua ref: `onResult`/`onClose` của cha đổi mỗi lần render.
  const onResultRef = useRef(onResult);
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onResultRef.current = onResult;
    onCloseRef.current = onClose;
  }, [onClose, onResult]);

  useMicLevel(status === 'listening', orbRef);

  const listen = useCallback(() => {
    const recognition = getRecognition();
    if (!recognition) {
      setStatus('unsupported');
      return;
    }
    recognitionRef.current?.abort();
    recognitionRef.current = recognition;
    recognition.lang = recognitionLang(language);
    recognition.interimResults = true;
    recognition.continuous = false;
    recognition.maxAlternatives = 1;
    let finalText = '';
    let error = '';
    recognition.onresult = (event) => {
      let partial = '';
      for (let index = 0; index < event.results.length; index += 1) {
        const result = event.results[index];
        if (result.isFinal) finalText += result[0].transcript;
        else partial += result[0].transcript;
      }
      setInterim(finalText + partial);
    };
    recognition.onerror = (event) => {
      error = event.error;
    };
    recognition.onend = () => {
      // Lượt nghe cũ bị huỷ để mở lượt mới (bấm "Thử lại"): bỏ qua.
      if (recognitionRef.current !== recognition) return;
      recognitionRef.current = null;
      const text = finalText.trim();
      if (text) {
        const query = cleanSpokenQuery(text);
        cues.play('heard');
        setHeard(query);
        setStatus('heard');
        // Để người dùng kịp thấy máy nghe ra chữ gì rồi mới đóng bảng.
        doneTimerRef.current = window.setTimeout(() => {
          onResultRef.current(query);
          onCloseRef.current();
        }, 450);
      } else if (error === 'not-allowed' || error === 'service-not-allowed') {
        setStatus('denied');
      } else if (error && error !== 'no-speech' && error !== 'aborted') {
        cues.play('error');
        setStatus('error');
      } else {
        cues.play('nothing');
        setStatus('nothing');
      }
    };
    setInterim('');
    setHeard('');
    setStatus('listening');
    try {
      recognition.start();
      cues.play('listen');
    } catch {
      recognitionRef.current = null;
      setStatus('error');
    }
  }, [cues, language]);

  // Mở bảng là nghe luôn — lượt bấm micro đã là thao tác của người dùng.
  useEffect(() => {
    // Ngoài thân effect: `listen` đặt state, gọi đồng bộ ở đây là render dây chuyền.
    const timer = window.setTimeout(listen, 0);
    return () => {
      window.clearTimeout(timer);
      window.clearTimeout(doneTimerRef.current);
      const recognition = recognitionRef.current;
      recognitionRef.current = null;
      recognition?.abort();
      cues.close();
    };
    // Chỉ một lần khi mở; "Thử lại" gọi `listen` trực tiếp.
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Esc đóng; bấm ra ngoài bảng cũng đóng (trừ chính nút micro đã mở bảng).
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCloseRef.current();
    };
    const onPointer = (event: PointerEvent) => {
      const target = event.target as HTMLElement | null;
      if (!target || panelRef.current?.contains(target) || target.closest('[data-voice-search-trigger]')) return;
      onCloseRef.current();
    };
    window.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onPointer);
    return () => {
      window.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onPointer);
    };
  }, []);

  /** Nút giữa: đang nghe → dừng (lấy luôn câu đã nói); không thì nghe lại. */
  const onOrb = () => {
    if (status === 'listening') recognitionRef.current?.stop();
    else if (status !== 'heard' && status !== 'unsupported') listen();
  };

  const pick = (query: string) => {
    const recognition = recognitionRef.current;
    recognitionRef.current = null;
    recognition?.abort();
    onResult(query);
    onClose();
  };

  const title = {
    listening: interim ? 'Đang nghe…' : 'Mời bạn nói',
    heard: 'Đã nghe',
    nothing: 'Không nghe thấy gì',
    denied: 'Chưa có quyền dùng micro',
    error: 'Không nhận dạng được giọng nói',
    unsupported: 'Trình duyệt chưa hỗ trợ',
  }[status];

  const hint = {
    listening: 'Nói tên món, loại địa điểm hoặc tên quán — ví dụ “cà phê gần đây”.',
    heard: '',
    nothing: 'Bấm micro để thử lại, hoặc chọn nhanh bên dưới.',
    denied: 'Hãy cho phép micro ở biểu tượng ổ khoá trên thanh địa chỉ rồi thử lại.',
    error: 'Kiểm tra kết nối mạng rồi bấm micro để thử lại.',
    unsupported: 'Hãy dùng Chrome hoặc Edge để tìm bằng giọng nói — hoặc chọn nhanh bên dưới.',
  }[status];

  return (
    <div
      ref={panelRef}
      // Bảng nổi không chặn trang (không modal): bản đồ phía sau vẫn dùng được.
      // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role
      role="dialog"
      aria-label="Tìm bằng giọng nói"
      className="voice-fade-in fixed inset-x-0 top-[calc(env(safe-area-inset-top)+4.5rem)] z-[55] mx-auto w-[min(calc(100%-2rem),24rem)] rounded-3xl border border-emerald-950/10 bg-white/95 p-5 text-foreground shadow-[0_24px_64px_-16px_rgb(14_68_48/35%)] backdrop-blur-md dark:border-white/10 dark:bg-popover/95"
    >
      <button
        type="button"
        onClick={onClose}
        aria-label="Đóng tìm bằng giọng nói (Esc)"
        className="absolute right-3 top-3 grid size-8 place-items-center rounded-full text-muted-foreground hover:bg-muted"
      >
        <X className="size-4" />
      </button>

      <div className="flex flex-col items-center gap-4 pt-2 text-center">
        <button
          ref={orbRef}
          type="button"
          onClick={onOrb}
          disabled={status === 'unsupported' || status === 'heard'}
          data-phase={status === 'listening' ? 'listening' : undefined}
          aria-label={status === 'listening' ? 'Đang nghe — bấm để dừng' : 'Bấm để nói lại'}
          className={cn(
            'mic-orb grid size-20 place-items-center rounded-full text-white shadow-lg transition-colors',
            status === 'listening' && 'bg-amber-400 text-slate-950',
            status === 'heard' && 'bg-emerald-600',
            (status === 'nothing' || status === 'error' || status === 'denied') && 'bg-emerald-600 hover:bg-emerald-500',
            status === 'unsupported' && 'bg-muted text-muted-foreground',
          )}
        >
          {status === 'heard' ? (
            <Check className="size-9" />
          ) : status === 'unsupported' || status === 'denied' ? (
            <MicOff className="size-9" />
          ) : status === 'listening' ? (
            <Mic className="size-9" />
          ) : (
            <RotateCcw className="size-8" />
          )}
        </button>

        <div className="min-h-[4.5rem] w-full" aria-live="polite">
          <p className="text-base font-semibold">{title}</p>
          {status === 'heard' ? (
            <p className="voice-fade-in mt-1 break-words text-xl font-bold text-primary">“{heard}”</p>
          ) : interim ? (
            <p className="mt-1 break-words text-xl text-foreground/80">“{interim}”</p>
          ) : (
            <p className="mt-1 text-sm text-muted-foreground">{hint}</p>
          )}
        </div>

        {status !== 'heard' && status !== 'listening' && (
          <fieldset className="flex min-w-0 flex-wrap justify-center gap-2 border-0 p-0">
            <legend className="sr-only">Tìm nhanh</legend>
            {EXAMPLES.map((example) => (
              <button
                key={example}
                type="button"
                onClick={() => pick(example)}
                className="rounded-full border border-emerald-950/10 bg-emerald-50 px-3 py-1.5 text-sm font-medium text-emerald-900 hover:bg-emerald-100 dark:border-white/10 dark:bg-white/5 dark:text-emerald-100 dark:hover:bg-white/10"
              >
                {example}
              </button>
            ))}
          </fieldset>
        )}

        <button
          type="button"
          onClick={() => {
            onClose();
            onOpenFullMode();
          }}
          className="flex w-full items-center justify-center gap-2 rounded-2xl border border-emerald-950/10 px-3 py-2.5 text-sm text-muted-foreground hover:bg-muted hover:text-foreground dark:border-white/10"
        >
          <Accessibility className="size-4 shrink-0" aria-hidden />
          <span>
            Chế độ giọng nói đầy đủ — đọc to, dẫn đường{' '}
            <kbd className="rounded border border-border px-1 font-mono text-xs">Alt+V</kbd>
          </span>
        </button>
      </div>
    </div>
  );
}

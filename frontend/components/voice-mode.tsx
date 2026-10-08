'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Keyboard, Mic, MicOff, Volume2, VolumeX, X } from 'lucide-react';

import { NarrationPlayer, distanceMeters, type AssistantOverlay } from '@/lib/assistant';
import { cn } from '@/lib/utils';

/**
 * Chế độ giọng nói cho người khiếm thị: tìm, chọn và đi tới địa điểm hoàn toàn
 * bằng lời nói.
 *
 * Chia việc:
 * - Trình duyệt NGHE (Web Speech API, `vi-VN`) và ĐỌC (giọng tiếng Việt của máy;
 *   máy không có giọng Việt thì xin backend đọc bằng VieNeu-TTS).
 * - Backend HIỂU câu nói và soạn câu trả lời (`POST /api/v1/voice/turn`, xem
 *   backend/app/voice.py) — không dùng LLM, để mỗi lượt trả lời trong 1-2 giây.
 * - Dẫn đường chạy ở đây vì nó bám theo GPS từng giây: tuyến đi bộ thật từ OSRM,
 *   đọc chỉ dẫn khi TỚI GẦN chỗ rẽ; không có tuyến thì chỉ hướng la bàn.
 *
 * Người dùng trình đọc màn hình (NVDA, TalkBack) có thể tắt "Tự đọc to": câu
 * trả lời vẫn vào vùng `aria-live` để trình đọc màn hình đọc, không bị nói chồng.
 */

type VoiceState = Record<string, unknown> | null;

type TurnResponse = {
  speech: string;
  state: VoiceState;
  action:
    | { type: 'navigate'; poiId: string; name: string; latitude: number; longitude: number }
    | { type: 'stop_navigation' }
    | { type: 'narrate'; poiId: string; name: string }
    | { type: 'exit' }
    | null;
};

type RouteStep = {
  text: string;
  distanceMeters: number;
  location: [number, number] | null;
};

type DirectionsRoute = {
  steps?: RouteStep[];
  geometry: NonNullable<AssistantOverlay['line']>;
  distanceMeters: number;
  durationMinutes: number;
  approximate?: boolean;
};

type Navigation = {
  poiId: string;
  name: string;
  latitude: number;
  longitude: number;
  steps: RouteStep[];
  nextStep: number;
  announcedAhead: number;
  lastProgressAt: number;
  lastProgressMeters: number;
};

type Line = { who: 'user' | 'app'; text: string };

type Phase = 'idle' | 'listening' | 'thinking' | 'speaking';

const GREETING =
  'Chế độ giọng nói đã bật. Bạn muốn tìm gì? Ví dụ: “quán phở gần đây”. Nói “trợ giúp” để nghe hướng dẫn. ' +
  'Nhấn phím cách để nói, phím Escape để thoát.';

// Ngưỡng dẫn đường (mét). GPS điện thoại trong phố sai 5-20 m.
const ARRIVE_METERS = 20;
const TURN_NOW_METERS = 20;
const TURN_AHEAD_METERS = 60;
const PROGRESS_EVERY_MS = 60_000;
const PROGRESS_EVERY_METERS = 150;

const COMPASS = ['bắc', 'đông bắc', 'đông', 'đông nam', 'nam', 'tây nam', 'tây', 'tây bắc'];

function bearing(from: { latitude: number; longitude: number }, to: { latitude: number; longitude: number }) {
  const toRad = (value: number) => (value * Math.PI) / 180;
  const p1 = toRad(from.latitude);
  const p2 = toRad(to.latitude);
  const dl = toRad(to.longitude - from.longitude);
  const x = Math.sin(dl) * Math.cos(p2);
  const y = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
  return ((Math.atan2(x, y) * 180) / Math.PI + 360) % 360;
}

function sayMeters(meters: number): string {
  if (meters < 1000) return `${Math.max(10, Math.round(meters / 10) * 10)} mét`;
  return `${(meters / 1000).toFixed(1).replace('.', ',').replace(',0', '')} ki lô mét`;
}

type SpeechRecognitionLike = {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  maxAlternatives: number;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
};

function getRecognition(): SpeechRecognitionLike | null {
  if (typeof window === 'undefined') return null;
  const Ctor =
    (window as unknown as { SpeechRecognition?: new () => SpeechRecognitionLike }).SpeechRecognition ??
    (window as unknown as { webkitSpeechRecognition?: new () => SpeechRecognitionLike }).webkitSpeechRecognition;
  return Ctor ? new Ctor() : null;
}

export function VoiceMode({
  apiBaseUrl,
  position,
  onClose,
  onMapOverlay,
}: {
  apiBaseUrl: string;
  position: { latitude: number; longitude: number };
  onClose: () => void;
  onMapOverlay: (overlay: AssistantOverlay | null) => void;
}) {
  const [phase, setPhase] = useState<Phase>('idle');
  const [lines, setLines] = useState<Line[]>([]);
  const [interim, setInterim] = useState('');
  const [selfVoice, setSelfVoice] = useState(true);
  const [autoListen, setAutoListen] = useState(true);
  const [typed, setTyped] = useState('');
  const [recognitionSupported] = useState(() => getRecognition() !== null);
  const [navigation, setNavigation] = useState<Navigation | null>(null);
  const [livePosition, setLivePosition] = useState<{ latitude: number; longitude: number } | null>(null);

  const stateRef = useRef<VoiceState>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [player] = useState(() => new NarrationPlayer(apiBaseUrl));
  const selfVoiceRef = useRef(selfVoice);
  const autoListenRef = useRef(autoListen);
  const navigationRef = useRef<Navigation | null>(null);
  const busyRef = useRef(false);
  const closedRef = useRef(false);
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    selfVoiceRef.current = selfVoice;
    autoListenRef.current = autoListen;
    navigationRef.current = navigation;
  }, [autoListen, navigation, selfVoice]);

  // Vị trí: GPS thật nếu được cấp quyền, không thì vị trí đang dùng trên bản đồ
  // (kể cả vị trí mô phỏng khi trình diễn trên máy tính).
  const here = livePosition ?? position;
  const hereRef = useRef(here);
  useEffect(() => {
    hereRef.current = here;
  }, [here]);

  useEffect(() => {
    if (typeof navigator === 'undefined' || !navigator.geolocation) return;
    const id = navigator.geolocation.watchPosition(
      ({ coords }) => {
        if (coords.accuracy <= 100) setLivePosition({ latitude: coords.latitude, longitude: coords.longitude });
      },
      () => undefined,
      { enableHighAccuracy: true, maximumAge: 3000 },
    );
    return () => navigator.geolocation.clearWatch(id);
  }, []);

  const addLine = useCallback((line: Line) => {
    setLines((prev) => [...prev.slice(-30), line]);
  }, []);

  // --- Đọc ---------------------------------------------------------------------

  const speakWithBrowser = useCallback((text: string): Promise<boolean> => {
    if (typeof window === 'undefined' || !('speechSynthesis' in window)) return Promise.resolve(false);
    const voices = window.speechSynthesis.getVoices();
    const voice = voices.find((item) => item.lang.toLowerCase().startsWith('vi'));
    // Không có giọng tiếng Việt: đọc tiếng Việt bằng giọng Anh là vô nghĩa với
    // người nghe — báo "không đọc được" để chuyển sang giọng máy chủ.
    if (!voice && voices.length > 0) return Promise.resolve(false);
    return new Promise((resolve) => {
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = 'vi-VN';
      if (voice) utterance.voice = voice;
      utterance.rate = 1.05;
      utterance.onend = () => resolve(true);
      utterance.onerror = () => resolve(true);
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(utterance);
    });
  }, []);

  const speakWithServer = useCallback(
    async (text: string): Promise<boolean> => {
      try {
        const res = await fetch(`${apiBaseUrl}/api/v1/voice/speak?${new URLSearchParams({ text })}`);
        if (!res.ok) return false;
        const url = URL.createObjectURL(await res.blob());
        return await new Promise((resolve) => {
          const audio = new Audio(url);
          audioRef.current = audio;
          const done = () => {
            URL.revokeObjectURL(url);
            resolve(true);
          };
          audio.onended = done;
          audio.onerror = done;
          audio.play().catch(done);
        });
      } catch {
        return false;
      }
    },
    [apiBaseUrl],
  );

  const stopSpeaking = useCallback(() => {
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) window.speechSynthesis.cancel();
    audioRef.current?.pause();
    audioRef.current = null;
  }, []);

  const say = useCallback(
    async (text: string) => {
      addLine({ who: 'app', text });
      if (!selfVoiceRef.current || closedRef.current) return;
      setPhase('speaking');
      const ok = (await speakWithBrowser(text)) || (await speakWithServer(text));
      if (!ok) await speakWithBrowser(text);
      if (!closedRef.current) setPhase('idle');
    },
    [addLine, speakWithBrowser, speakWithServer],
  );

  // --- Nghe --------------------------------------------------------------------

  const handleUtteranceRef = useRef<(text: string) => Promise<void>>(async () => undefined);

  const listen = useCallback(() => {
    if (closedRef.current || busyRef.current) return;
    const recognition = getRecognition();
    if (!recognition) return;
    stopSpeaking();
    recognitionRef.current?.abort();
    recognitionRef.current = recognition;
    recognition.lang = 'vi-VN';
    recognition.interimResults = true;
    recognition.continuous = false;
    recognition.maxAlternatives = 1;
    let finalText = '';
    recognition.onresult = (event) => {
      let partial = '';
      for (let index = 0; index < event.results.length; index += 1) {
        const result = event.results[index];
        if (result.isFinal) finalText += result[0].transcript;
        else partial += result[0].transcript;
      }
      setInterim(partial);
    };
    recognition.onerror = (event) => {
      if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
        void say('Trình duyệt chưa cho phép dùng micro. Hãy cấp quyền micro rồi nhấn phím cách để nói.');
      }
    };
    recognition.onend = () => {
      setInterim('');
      if (recognitionRef.current === recognition) recognitionRef.current = null;
      if (closedRef.current) return;
      if (finalText.trim()) {
        void handleUtteranceRef.current(finalText.trim());
      } else {
        setPhase('idle');
      }
    };
    setPhase('listening');
    try {
      recognition.start();
    } catch {
      setPhase('idle');
    }
  }, [say, stopSpeaking]);

  const afterSpeech = useCallback(() => {
    if (autoListenRef.current && recognitionSupported && !closedRef.current) listen();
  }, [listen, recognitionSupported]);

  // --- Dẫn đường -----------------------------------------------------------------

  const stopNavigation = useCallback(() => {
    setNavigation(null);
    navigationRef.current = null;
    onMapOverlay(null);
  }, [onMapOverlay]);

  const startNavigation = useCallback(
    async (target: { poiId: string; name: string; latitude: number; longitude: number }) => {
      const from = hereRef.current;
      let steps: RouteStep[] = [];
      let intro = '';
      try {
        const params = new URLSearchParams({
          from_lat: String(from.latitude),
          from_lng: String(from.longitude),
          to_poi_id: target.poiId,
          mode: 'foot',
        });
        const res = await fetch(`${apiBaseUrl}/api/v1/directions?${params}`);
        const data = (res.ok ? await res.json() : null) as { route?: DirectionsRoute | null } | null;
        const route = data?.route;
        if (route) {
          steps = (route.steps ?? []) as RouteStep[];
          onMapOverlay({
            line: route.geometry,
            points: [
              {
                id: target.poiId,
                latitude: target.latitude,
                longitude: target.longitude,
                label: '★',
                tone: 'result',
                title: target.name,
                poiId: target.poiId,
              },
            ],
          });
          intro =
            `Quãng đường đi bộ ${sayMeters(route.distanceMeters)}, khoảng ${route.durationMinutes} phút` +
            (route.approximate ? ', tính gần đúng' : '') +
            '. ' +
            (steps[0]?.text ? `${steps[0].text}. ` : '') +
            (steps[1]?.text ? `Sau đó, ${steps[1].text.toLowerCase()} sau khoảng ${sayMeters(steps[0]?.distanceMeters ?? 0)}.` : '');
        }
      } catch {
        // rơi xuống chỉ hướng la bàn
      }
      if (!steps.length) {
        const direction = COMPASS[Math.round(bearing(from, target) / 45) % 8];
        intro = `Chưa có tuyến đường đi bộ. Điểm đến ở hướng ${direction}, cách ${sayMeters(distanceMeters(from, target))} đường chim bay. Tôi sẽ báo khoảng cách khi bạn di chuyển.`;
      }
      const nav: Navigation = {
        ...target,
        steps,
        nextStep: 1,
        announcedAhead: 0,
        lastProgressAt: Date.now(),
        lastProgressMeters: distanceMeters(from, target),
      };
      setNavigation(nav);
      navigationRef.current = nav;
      await say(intro);
    },
    [apiBaseUrl, onMapOverlay, say],
  );

  // Mỗi lần vị trí đổi: tới nơi chưa, sắp tới chỗ rẽ chưa, báo tiến độ.
  useEffect(() => {
    const nav = navigationRef.current;
    // Đang nghe/đang đọc thì chờ: effect chạy lại khi `phase` về idle, chỉ dẫn
    // không bị mất mà cũng không cắt ngang câu đang đọc dở.
    if (!nav || busyRef.current || phase === 'listening' || phase === 'speaking') return;
    const remaining = distanceMeters(here, nav);
    let message: string | null = null;
    let next = { ...nav };

    if (remaining <= ARRIVE_METERS) {
      message = `Bạn đã tới ${nav.name}. Đã kết thúc dẫn đường.`;
      stateRef.current = { ...stateRef.current, stage: 'selected' };
      stopNavigation();
    } else {
      const step = nav.steps[nav.nextStep];
      if (step?.location) {
        const toTurn = distanceMeters(here, { latitude: step.location[1], longitude: step.location[0] });
        if (toTurn <= TURN_NOW_METERS) {
          message = `${step.text}.`;
          next = { ...next, nextStep: nav.nextStep + 1, lastProgressAt: Date.now(), lastProgressMeters: remaining };
        } else if (toTurn <= TURN_AHEAD_METERS && nav.announcedAhead !== nav.nextStep) {
          message = `Khoảng ${sayMeters(toTurn)} nữa, ${step.text.toLowerCase()}.`;
          next = { ...next, announcedAhead: nav.nextStep };
        }
      }
      if (
        !message &&
        (Date.now() - nav.lastProgressAt > PROGRESS_EVERY_MS ||
          nav.lastProgressMeters - remaining > PROGRESS_EVERY_METERS)
      ) {
        const direction = COMPASS[Math.round(bearing(here, nav) / 45) % 8];
        message = `Còn khoảng ${sayMeters(remaining)} tới ${nav.name}${nav.steps.length ? '' : `, về hướng ${direction}`}.`;
        next = { ...next, lastProgressAt: Date.now(), lastProgressMeters: remaining };
      }
      if (message) {
        setNavigation(next);
        navigationRef.current = next;
      }
    }
    // Phản ứng với GPS (hệ thống bên ngoài) bằng giọng nói — đúng việc của effect.
    // oxlint-disable-next-line react/react-compiler
    if (message) void say(message);
  }, [here, phase, say, stopNavigation]);

  // --- Một lượt hội thoại ---------------------------------------------------------

  const handleUtterance = useCallback(
    async (text: string) => {
      if (busyRef.current) return;
      busyRef.current = true;
      addLine({ who: 'user', text });
      setPhase('thinking');
      let response: TurnResponse | null = null;
      try {
        const res = await fetch(`${apiBaseUrl}/api/v1/voice/turn`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            text,
            latitude: hereRef.current.latitude,
            longitude: hereRef.current.longitude,
            state: stateRef.current,
          }),
        });
        if (res.ok) response = (await res.json()) as TurnResponse;
      } catch {
        response = null;
      }
      busyRef.current = false;
      if (!response) {
        await say('Xin lỗi, tôi không kết nối được máy chủ. Bạn thử lại nhé.');
        afterSpeech();
        return;
      }
      stateRef.current = response.state;
      const action = response.action;
      if (action?.type === 'exit') {
        await say(response.speech);
        onClose();
        return;
      }
      if (action?.type === 'stop_navigation') stopNavigation();
      await say(response.speech);
      if (action?.type === 'navigate') {
        await startNavigation(action);
      } else if (action?.type === 'narrate') {
        setPhase('speaking');
        await player.play(action.poiId, 'vi', (narration) => addLine({ who: 'app', text: narration }));
        setPhase('idle');
      }
      afterSpeech();
    },
    [addLine, afterSpeech, apiBaseUrl, onClose, player, say, startNavigation, stopNavigation],
  );

  useEffect(() => {
    handleUtteranceRef.current = handleUtterance;
  }, [handleUtterance]);

  // Mở chế độ: chào, rồi lắng nghe luôn.
  useEffect(() => {
    closedRef.current = false;
    dialogRef.current?.focus();
    const loadVoices = () => undefined;
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      // Chrome nạp danh sách giọng bất đồng bộ — gọi trước để lần đọc đầu có giọng.
      window.speechSynthesis.getVoices();
      window.speechSynthesis.addEventListener('voiceschanged', loadVoices);
    }
    const timer = setTimeout(() => {
      void say(GREETING).then(afterSpeech);
    }, 300);
    return () => {
      clearTimeout(timer);
      closedRef.current = true;
      recognitionRef.current?.abort();
      player.stop();
      if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
        window.speechSynthesis.cancel();
        window.speechSynthesis.removeEventListener('voiceschanged', loadVoices);
      }
      audioRef.current?.pause();
      onMapOverlay(null);
    };
    // Chỉ chạy một lần khi mở chế độ giọng nói.
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Phím tắt: Space = nói, Esc = thoát. Bỏ qua khi đang gõ trong ô nhập.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing = target?.tagName === 'INPUT' || target?.tagName === 'TEXTAREA';
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
      } else if (event.code === 'Space' && !typing) {
        event.preventDefault();
        if (phase === 'listening') recognitionRef.current?.stop();
        else listen();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [listen, onClose, phase]);

  const lastApp = [...lines].reverse().find((line) => line.who === 'app');
  const phaseLabel = {
    idle: recognitionSupported ? 'Nhấn để nói (phím cách)' : 'Gõ lệnh bên dưới',
    listening: 'Đang nghe…',
    thinking: 'Đang tìm…',
    speaking: 'Đang đọc…',
  }[phase];

  return (
    <div
      ref={dialogRef}
      // Lớp phủ toàn màn hình tự quản lý focus (dialogRef), không dùng <dialog> gốc.
      // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role
      role="dialog"
      aria-modal="true"
      aria-label="Chế độ giọng nói cho người khiếm thị"
      tabIndex={-1}
      className="voice-mode fixed inset-0 z-[60] flex h-dvh flex-col overflow-hidden bg-slate-950 text-white outline-none"
    >
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-white/10 px-3 py-2 sm:px-4 sm:py-3">
        <p className="flex items-center gap-2 text-base font-bold sm:text-lg"><Mic className="size-5 shrink-0" aria-hidden /> Chế độ giọng nói</p>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setSelfVoice((value) => !value)}
            aria-pressed={selfVoice}
            aria-label={selfVoice ? 'Tự đọc to: bật' : 'Tự đọc to: tắt'}
            title="Tự đọc to"
            className="flex items-center gap-1.5 rounded-lg border border-white/20 px-3 py-2 text-sm hover:bg-white/10"
          >
            {selfVoice ? <Volume2 className="size-4" /> : <VolumeX className="size-4" />}
            <span className="hidden sm:inline">{selfVoice ? 'Tự đọc to: bật' : 'Tự đọc to: tắt (dùng trình đọc màn hình)'}</span>
          </button>
          <button
            type="button"
            onClick={() => setAutoListen((value) => !value)}
            aria-pressed={autoListen}
            aria-label={autoListen ? 'Tự nghe sau khi đọc: bật' : 'Tự nghe sau khi đọc: tắt'}
            className="flex items-center gap-1.5 rounded-lg border border-white/20 px-3 py-2 text-sm hover:bg-white/10"
          >
            <Mic className="size-4" aria-hidden />
            <span className="sm:hidden">Tự nghe</span>
            <span className="hidden sm:inline">{autoListen ? 'Tự nghe sau khi đọc: bật' : 'Tự nghe sau khi đọc: tắt'}</span>
          </button>
          <button
            type="button"
            onClick={onClose}
            aria-label="Thoát chế độ giọng nói (phím Escape)"
            className="rounded-lg border border-white/20 p-2 hover:bg-white/10"
          >
            <X className="size-5" />
          </button>
        </div>
      </div>

      <div className="voice-content flex min-h-0 flex-1 flex-col items-center gap-4 overflow-y-auto overscroll-contain px-4 py-4 sm:gap-6 sm:py-6">
        <button
          type="button"
          onClick={() => (phase === 'listening' ? recognitionRef.current?.stop() : listen())}
          disabled={!recognitionSupported}
          aria-label={phase === 'listening' ? 'Đang nghe — nhấn để dừng' : 'Nhấn để nói'}
          className={cn(
            'voice-mic grid size-32 shrink-0 place-items-center rounded-full border-4 transition sm:size-56',
            phase === 'listening'
              ? 'animate-pulse border-amber-300 bg-amber-400 text-slate-950'
              : 'border-emerald-300 bg-emerald-500 text-slate-950 hover:bg-emerald-400',
            !recognitionSupported && 'opacity-40',
          )}
        >
          {recognitionSupported ? <Mic className="size-14 sm:size-20" /> : <MicOff className="size-14 sm:size-20" />}
        </button>
        <p className="w-full break-words text-center text-xl font-semibold sm:text-2xl" aria-hidden>
          {phaseLabel}
        </p>
        {interim && <p className="text-xl text-amber-200">“{interim}”</p>}
        {lastApp && (
          <p className="w-full max-w-3xl break-words text-center text-lg leading-relaxed text-white sm:text-3xl">{lastApp.text}</p>
        )}
        {navigation && (
          <p className="rounded-full bg-emerald-500/20 px-4 py-2 text-lg text-emerald-200">
            Đang dẫn đường tới {navigation.name} · còn {sayMeters(distanceMeters(here, navigation))}
          </p>
        )}
        {!recognitionSupported && (
          <p className="max-w-xl text-center text-base text-amber-200">
            Trình duyệt này chưa hỗ trợ nhận dạng giọng nói. Hãy dùng Chrome hoặc Edge — hoặc gõ lệnh bên dưới.
          </p>
        )}
      </div>

      <div className="shrink-0 border-t border-white/10 px-3 py-3 sm:px-4">
        <form
          className="mx-auto flex max-w-3xl items-center gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            const text = typed.trim();
            if (!text) return;
            setTyped('');
            void handleUtterance(text);
          }}
        >
          <Keyboard className="hidden size-5 shrink-0 text-white/60 sm:block" aria-hidden />
          <input
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            placeholder="Hoặc gõ lệnh: “quán phở”, “số hai”, “dẫn đường”…"
            aria-label="Gõ lệnh thay cho nói"
            className="h-11 min-w-0 flex-1 rounded-lg border border-white/20 bg-white/5 px-3 text-base text-white placeholder:text-white/40"
          />
          <button type="submit" className="h-11 rounded-lg bg-white px-4 font-semibold text-slate-950">
            Gửi
          </button>
        </form>
        {/* Nhật ký hội thoại: trình đọc màn hình đọc mỗi dòng mới (aria-live). */}
        <div role="log" aria-live="polite" aria-label="Nhật ký hội thoại" className="mx-auto mt-2 max-h-16 max-w-3xl overflow-y-auto break-words text-sm text-white/70 sm:max-h-28">
          {lines.map((line, index) => (
            <p key={index}>
              <span className="font-semibold">{line.who === 'user' ? 'Bạn' : 'Nearby'}:</span> {line.text}
            </p>
          ))}
        </div>
      </div>
    </div>
  );
}

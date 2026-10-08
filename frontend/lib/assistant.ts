/**
 * Kiểu dữ liệu + tiện ích cho trợ lý trong khung chatbot: chip gợi ý, tour
 * thuyết minh, hẹn nhóm. Khớp response của backend/app/assistant.py.
 */

export type PlaceRef = {
  poiId: string | null;
  name: string;
  latitude: number;
  longitude: number;
  distanceMeters?: number | null;
};

/** Tìm trực tiếp theo category quanh một toạ độ — không qua LLM (backend
 * `assistant.shop_search` / `home_meal_chip`). */
export type SearchAction = {
  type: 'search';
  title: string;
  category: string | null;
  query: string | null;
  latitude: number;
  longitude: number;
  radius: number;
  count?: number;
};

export type AssistantEvent = {
  name: string;
  date: string;
  daysUntil: number;
  lunar: boolean;
  note: string;
  places: PlaceRef[];
  ask?: string | null;
  search?: SearchAction | null;
};

export type SuggestionAction =
  | { type: 'ask'; prompt: string }
  | { type: 'event'; event: AssistantEvent }
  | SearchAction
  | { type: 'set_home' }
  | { type: 'tour' }
  | { type: 'explore' }
  | { type: 'voice' }
  | { type: 'meetup' };

export type Suggestion = {
  id: string;
  kind: 'event' | 'shop' | 'weather' | 'time' | 'home' | 'tour' | 'explore' | 'voice' | 'meetup';
  icon: string;
  title: string;
  subtitle: string;
  action: SuggestionAction;
};

export type SuggestionsResponse = {
  date: string;
  lunarDate: string | null;
  country: string | null;
  calendarAvailable: boolean;
  suggestions: Suggestion[];
};

export type TourStop = {
  order: number;
  poiId: string;
  name: string;
  category: string;
  contentType: string;
  latitude: number;
  longitude: number;
  teaser: string | null;
  legMeters: number | null;
  legMinutes: number | null;
};

export type TourPlan = {
  status: 'ready' | 'none';
  budgetMinutes?: number;
  stops: TourStop[];
  geometry?: { type: 'LineString'; coordinates: [number, number][] };
  walkMeters?: number;
  walkMinutes?: number;
  dwellMinutes?: number;
  totalMinutes?: number;
  approach?: {
    mode: 'foot' | 'motorbike';
    minutes: number;
    distanceMeters: number;
    approximate?: boolean;
  };
  approximate?: boolean;
};

export type MeetupResult = {
  poiId: string;
  name: string;
  category: string;
  address: string | null;
  rating: number | null;
  latitude: number;
  longitude: number;
  minutes: number[];
  maxMinutes: number;
  totalMinutes: number;
  spreadMinutes: number;
  parking: { name: string | null; distanceMeters: number } | null;
};

export type MeetupPlan = {
  status: 'ready' | 'none';
  mode?: string;
  approximate?: boolean;
  center: { latitude: number; longitude: number };
  results: MeetupResult[];
  baseline?: MeetupResult;
  candidateCount?: number;
};

/** Lớp vẽ tạm lên bản đồ do trợ lý yêu cầu (tuyến tour, người trong nhóm…). */
export type AssistantOverlay = {
  line?: { type: 'LineString'; coordinates: [number, number][] } | null;
  points: {
    id: string;
    latitude: number;
    longitude: number;
    label: string;
    tone: 'stop' | 'person' | 'result';
    title: string;
    poiId?: string;
  }[];
};

export function formatMeters(meters: number | null | undefined): string {
  if (meters == null) return '';
  return meters < 1000 ? `${Math.round(meters)} m` : `${(meters / 1000).toFixed(1)} km`;
}

export function formatMinutes(minutes: number | null | undefined): string {
  if (minutes == null) return '';
  if (minutes < 60) return `${minutes} phút`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours} giờ ${rest} phút` : `${hours} giờ`;
}

export function distanceMeters(
  a: { latitude: number; longitude: number },
  b: { latitude: number; longitude: number },
): number {
  const toRad = (value: number) => (value * Math.PI) / 180;
  const dLat = toRad(b.latitude - a.latitude);
  const dLng = toRad(b.longitude - a.longitude);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(a.latitude)) * Math.cos(toRad(b.latitude)) * Math.sin(dLng / 2) ** 2;
  return 2 * 6_371_000 * Math.asin(Math.sqrt(h));
}

// Mã ngôn ngữ → mã giọng đọc của trình duyệt. Ngôn ngữ không có ở đây vẫn được
// truyền nguyên mã (vd "km"), trình duyệt tự chọn giọng gần nhất nếu có.
export const SPEECH_LANG: Record<string, string> = {
  vi: 'vi-VN',
  en: 'en-US',
  zh: 'zh-CN',
  ja: 'ja-JP',
  ko: 'ko-KR',
  fr: 'fr-FR',
  de: 'de-DE',
  es: 'es-ES',
  ru: 'ru-RU',
  th: 'th-TH',
  id: 'id-ID',
  it: 'it-IT',
  pt: 'pt-BR',
};

/**
 * Phát thuyết minh cho MỘT điểm và trả Promise kết thúc khi đọc xong — để tour
 * xâu chuỗi được nhiều điểm (hook usePoiNarration chỉ có toggle, không báo lúc
 * đọc xong).
 *
 * Thứ tự nguồn: audio giọng thật ĐÃ CACHE (VieNeu-TTS) → chữ thuyết minh +
 * speechSynthesis của trình duyệt. KHÔNG chờ backend sinh audio mới (~2 phút
 * trên CPU) giữa tour.
 */
export class NarrationPlayer {
  private audio: HTMLAudioElement | null = null;
  private objectUrl: string | null = null;
  private abort: AbortController | null = null;
  private finish: (() => void) | null = null;
  private rate = 1;

  constructor(private readonly apiBaseUrl: string) {}

  async play(
    poiId: string,
    language: string,
    onText: (text: string) => void,
    options: { rate?: number } = {},
  ): Promise<'ended' | 'stopped' | 'unavailable'> {
    this.stop();
    this.rate = options.rate ?? 1;
    const controller = new AbortController();
    this.abort = controller;
    const lang = encodeURIComponent(language);
    try {
      const audioRes = await fetch(
        `${this.apiBaseUrl}/api/v1/pois/${poiId}/narration/audio?language=${lang}&cached_only=1`,
        { signal: controller.signal },
      );
      if (audioRes.status === 200) {
        const header = audioRes.headers.get('X-Narration-Text');
        if (header) onText(decodeURIComponent(header));
        const blob = await audioRes.blob();
        if (controller.signal.aborted) return 'stopped';
        return await this.playBlob(blob);
      }
      const textRes = await fetch(
        `${this.apiBaseUrl}/api/v1/pois/${poiId}/narration?language=${lang}`,
        { signal: controller.signal },
      );
      if (!textRes.ok) return 'unavailable';
      const data = (await textRes.json()) as { available?: boolean; narration?: string };
      if (!data.available || !data.narration) return 'unavailable';
      onText(data.narration);
      if (controller.signal.aborted) return 'stopped';
      return await this.speak(data.narration, SPEECH_LANG[language] ?? language);
    } catch {
      return controller.signal.aborted ? 'stopped' : 'unavailable';
    }
  }

  private playBlob(blob: Blob): Promise<'ended' | 'stopped'> {
    return new Promise((resolve) => {
      this.objectUrl = URL.createObjectURL(blob);
      const audio = new Audio(this.objectUrl);
      audio.playbackRate = this.rate;
      this.audio = audio;
      this.finish = () => resolve('stopped');
      audio.onended = () => resolve('ended');
      audio.onerror = () => resolve('stopped');
      audio.play().catch(() => resolve('stopped'));
    });
  }

  private speak(text: string, lang: string): Promise<'ended' | 'stopped' | 'unavailable'> {
    if (typeof window === 'undefined' || !('speechSynthesis' in window)) {
      return Promise.resolve('unavailable');
    }
    return new Promise((resolve) => {
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = lang;
      utterance.rate = this.rate;
      // Chọn đúng giọng của ngôn ngữ nếu máy có — chỉ đặt `lang` thì vài trình
      // duyệt vẫn đọc bằng giọng mặc định (thường là tiếng Anh).
      const prefix = lang.slice(0, 2).toLowerCase();
      const voice = window.speechSynthesis
        .getVoices()
        .find((item) => item.lang.toLowerCase().startsWith(prefix));
      if (voice) utterance.voice = voice;
      this.finish = () => resolve('stopped');
      utterance.onend = () => resolve('ended');
      utterance.onerror = () => resolve('stopped');
      window.speechSynthesis.speak(utterance);
    });
  }

  stop(): void {
    this.abort?.abort();
    this.abort = null;
    if (this.audio) {
      this.audio.onended = null;
      this.audio.pause();
      this.audio = null;
    }
    if (this.objectUrl) {
      URL.revokeObjectURL(this.objectUrl);
      this.objectUrl = null;
    }
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      window.speechSynthesis.cancel();
    }
    const finish = this.finish;
    this.finish = null;
    finish?.();
  }
}

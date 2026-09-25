'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

/** Mã BCP-47 trong danh sách 134 ngôn ngữ của backend (`app/languages.py`). */
export type NarrationLanguage = string;

type NarrationResponse = {
  available: boolean;
  narration: string | null;
  verified: boolean | null;
};

type NarrationStatus = 'idle' | 'loading' | 'ready' | 'unavailable' | 'error';
type SpeechState = 'idle' | 'speaking' | 'paused';

// speechSynthesis nhận BCP-47. Mã của backend đã là BCP-47 ("fr", "zh-CN"),
// chỉ vi/en được gắn vùng cụ thể để trình duyệt chọn đúng giọng hay dùng nhất.
const SPEECH_LANG: Record<string, string> = { vi: 'vi-VN', en: 'en-US' };

// Viết tiếng Việt — bộ dịch giao diện tự dịch sang ngôn ngữ đang chọn.
const VOICE_WARNING =
  'Thiết bị của bạn chưa có giọng đọc cho ngôn ngữ này — đang đọc bằng giọng mặc định.';

/**
 * "Nghe thuyết minh" cho panel chi tiết POI, hỗ trợ đa ngôn ngữ (vi/en).
 *
 * ƯU TIÊN audio THẬT do backend tổng hợp (VieNeu-TTS, chạy CPU, không cần
 * GPU/API key) qua `GET /narration/audio` — thay cho `speechSynthesis` của
 * trình duyệt vốn phụ thuộc HOÀN TOÀN vào giọng đã cài sẵn trên máy người
 * xem (đo được thật: máy Windows thiếu giọng tiếng Việt phải đọc bằng giọng
 * mặc định, nghe không tự nhiên — rủi ro không chấp nhận được cho một buổi
 * demo/bảo vệ luận văn).
 *
 * CHỈ rơi về `speechSynthesis` khi audio thật không dùng được (vd ngôn ngữ
 * chưa có giọng VieNeu-TTS như "en", hoặc lỗi mạng) — không xoá hẳn nhánh
 * cũ, cùng triết lý graceful-degradation đã dùng xuyên suốt project: một
 * lớp giọng đọc lỗi không được làm hỏng cả tính năng thuyết minh.
 *
 * Văn bản hiển thị LUÔN LÀ văn bản đã nhận từ backend, dù đi theo nhánh nào
 * — hook này không tự soạn hay sửa nội dung, chỉ phát âm nguyên văn.
 *
 * Mở POI là TỰ tải chữ thuyết minh (backend đã tạo sẵn và cache, xem
 * `backend/app/narration.py`) và tải trước audio nếu đã có trong cache
 * (`cached_only=1` — không kích hoạt LLM+TTS cho POI chỉ lướt qua), nên bấm
 * "Nghe thuyết minh" là phát ngay. Truyền `poiId = null` cho POI không có
 * `knowledge` để không gọi API thừa.
 */
export function usePoiNarration(
  apiBaseUrl: string,
  poiId: string | null,
  language: NarrationLanguage,
) {
  const [status, setStatus] = useState<NarrationStatus>('idle');
  const [text, setText] = useState<string | null>(null);
  const [verified, setVerified] = useState<boolean | null>(null);
  const [speechState, setSpeechState] = useState<SpeechState>('idle');
  const [voiceWarning, setVoiceWarning] = useState<string | null>(null);

  // Audio THẬT đang phát (nếu có) — `null` nghĩa là đang ở nhánh
  // speechSynthesis hoặc chưa phát gì. `toggle()` dựa vào biến này để biết
  // nên điều khiển đối tượng nào (pause() của <audio> khác hẳn API của
  // speechSynthesis).
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioUrlRef = useRef<string | null>(null);
  // Audio đã tải trước lúc mở panel — `toggle()` phát thẳng cái này, không
  // phải chờ mạng.
  const prefetchedRef = useRef<{
    url: string;
    text: string | null;
    verified: boolean | null;
  } | null>(null);

  const stopAll = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    if (audioUrlRef.current) {
      URL.revokeObjectURL(audioUrlRef.current);
      audioUrlRef.current = null;
    }
    if (prefetchedRef.current) {
      URL.revokeObjectURL(prefetchedRef.current.url);
      prefetchedRef.current = null;
    }
    try {
      window.speechSynthesis?.cancel();
    } catch {
      // API không có trên trình duyệt này — không có gì để huỷ.
    }
  }, []);

  // Đổi POI, đổi ngôn ngữ, hoặc đóng panel thì dừng hẳn giọng đang đọc và
  // quên nội dung cũ — đọc tiếp thuyết minh của quán trước (hoặc bằng ngôn
  // ngữ trước) trong lúc panel đã sang trạng thái khác là sai lệch rất khó
  // nhận ra (tai vẫn nghe, mắt đã đọc chỗ khác).
  useEffect(() => {
    // Reset có chủ đích khi `poiId`/`language` (giá trị đến từ ngoài React)
    // đổi — cùng mẫu với `use-poi-detail.ts`.
    // oxlint-disable-next-line react/react-compiler
    setStatus('idle');
    setText(null);
    setVerified(null);
    setSpeechState('idle');
    setVoiceWarning(null);
    stopAll();
  }, [poiId, language, stopAll]);

  // Mở POI → tải chữ ngay (từ cache, gần như tức thì), rồi tải trước audio
  // nếu backend đã có sẵn. Đổi POI/ngôn ngữ giữa chừng thì huỷ cả hai.
  useEffect(() => {
    if (!poiId) return;
    const controller = new AbortController();
    const query = `language=${language}`;
    const base = `${apiBaseUrl}/api/v1/pois/${poiId}/narration`;

    // oxlint-disable-next-line react/react-compiler
    setStatus('loading');
    void (async () => {
      try {
        const response = await fetch(`${base}?${query}`, { signal: controller.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = (await response.json()) as NarrationResponse;
        if (!data.available || !data.narration) {
          setStatus('unavailable');
          return;
        }
        setText(data.narration);
        setVerified(data.verified);
        setStatus('ready');
      } catch {
        // Lỗi mạng/huỷ: để nút bấm tự thử lại, không báo lỗi khi chưa bấm gì.
        if (!controller.signal.aborted) setStatus('idle');
        return;
      }

      try {
        const response = await fetch(`${base}/audio?${query}&cached_only=1`, {
          signal: controller.signal,
        });
        if (response.status !== 200) return; // 204: chưa có cache — tải khi bấm
        const headerVerified = response.headers.get('X-Narration-Verified');
        const headerText = response.headers.get('X-Narration-Text');
        const blob = await response.blob();
        if (controller.signal.aborted) return;
        prefetchedRef.current = {
          url: URL.createObjectURL(blob),
          text: headerText ? decodeURIComponent(headerText) : null,
          verified: headerVerified === null ? null : headerVerified === 'true',
        };
      } catch {
        // Tải trước thất bại không sao — bấm nghe sẽ tải lại như thường.
      }
    })();
    return () => controller.abort();
  }, [apiBaseUrl, poiId, language]);

  // Huỷ giọng đọc khi rời hẳn trang.
  useEffect(() => stopAll, [stopAll]);

  const fetchNarrationText = useCallback(async (): Promise<string | null> => {
    if (!poiId) return null;
    try {
      const response = await fetch(
        `${apiBaseUrl}/api/v1/pois/${poiId}/narration?language=${language}`,
      );
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = (await response.json()) as NarrationResponse;
      if (!data.available || !data.narration) return null;
      setText(data.narration);
      setVerified(data.verified);
      return data.narration;
    } catch {
      return null;
    }
  }, [apiBaseUrl, poiId, language]);

  const speakWithBrowserVoice = useCallback(
    (content: string) => {
      if (typeof window === 'undefined' || !window.speechSynthesis) {
        setVoiceWarning('Trình duyệt của bạn chưa hỗ trợ đọc giọng nói.');
        setStatus('error');
        return;
      }
      const speechLang = SPEECH_LANG[language] ?? language;
      const voices = window.speechSynthesis.getVoices();
      const wanted = speechLang.toLowerCase();
      const base = wanted.split('-')[0];
      const matchingVoice =
        voices.find((voice) => voice.lang?.toLowerCase().replace('_', '-') === wanted) ??
        voices.find((voice) => voice.lang?.toLowerCase().startsWith(base));
      // `voices.length === 0` nghĩa là danh sách giọng CHƯA nạp xong, không
      // phải "không có giọng phù hợp" — chỉ cảnh báo khi đã có danh sách
      // thật mà không tìm thấy. KHÔNG fallback sang giọng ngôn ngữ khác.
      setVoiceWarning(voices.length > 0 && !matchingVoice ? VOICE_WARNING : null);

      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(content);
      utterance.lang = speechLang;
      if (matchingVoice) utterance.voice = matchingVoice;
      utterance.onstart = () => setSpeechState('speaking');
      utterance.onend = () => setSpeechState('idle');
      utterance.onerror = () => setSpeechState('idle');
      window.speechSynthesis.speak(utterance);
      setStatus('ready');
      setSpeechState('speaking');
    },
    [language],
  );

  const startAudio = useCallback(
    async (url: string, audioText: string | null, audioVerified: boolean | null) => {
      if (audioText) setText(audioText);
      setVerified(audioVerified);
      audioUrlRef.current = url;
      const audio = new Audio(url);
      audioRef.current = audio;
      audio.onplay = () => setSpeechState('speaking');
      audio.onpause = () => {
        // `ended` cũng bắn `pause` ngay trước nó — chỉ coi là "tạm dừng" khi
        // CHƯA phát hết, tránh nút hiện "Tiếp tục" cho một đoạn đã đọc xong.
        if (!audio.ended) setSpeechState('paused');
      };
      // Đọc xong vẫn giữ audio (tua về đầu) — bấm nghe lần nữa phát ngay,
      // không tải lại.
      audio.onended = () => {
        audio.currentTime = 0;
        setSpeechState('idle');
      };
      setStatus('ready');
      await audio.play();
    },
    [],
  );

  /** Trả `true` nếu đã XỬ LÝ XONG lượt này (phát thành công, hoặc xác định
   * chắc chắn "không có thuyết minh") — `false` nghĩa là audio thật không
   * dùng được, bên gọi nên thử nhánh `speechSynthesis`. */
  const playRealAudio = useCallback(async (): Promise<boolean> => {
    if (!poiId) return false;
    try {
      const response = await fetch(
        `${apiBaseUrl}/api/v1/pois/${poiId}/narration/audio?language=${language}`,
      );
      if (response.status === 404) {
        setStatus('unavailable');
        return true;
      }
      if (!response.ok) return false; // 503 (ngôn ngữ chưa có giọng) hoặc lỗi khác

      const headerText = response.headers.get('X-Narration-Text');
      const headerVerified = response.headers.get('X-Narration-Verified');
      const blob = await response.blob();
      await startAudio(
        URL.createObjectURL(blob),
        headerText ? decodeURIComponent(headerText) : null,
        headerVerified === null ? null : headerVerified === 'true',
      );
      return true;
    } catch {
      return false;
    }
  }, [apiBaseUrl, poiId, language, startAudio]);

  const toggle = useCallback(async () => {
    // Đang phát/tạm dừng bằng audio THẬT.
    if (audioRef.current) {
      if (speechState === 'speaking') {
        audioRef.current.pause();
        return;
      }
      // 'paused' hoặc đã đọc xong ('idle') — phát tiếp/phát lại cùng audio.
      void audioRef.current.play();
      return;
    }
    // Đang phát/tạm dừng bằng speechSynthesis (nhánh dự phòng).
    if (!audioRef.current && speechState === 'speaking') {
      window.speechSynthesis?.pause();
      setSpeechState('paused');
      return;
    }
    if (!audioRef.current && speechState === 'paused') {
      window.speechSynthesis?.resume();
      setSpeechState('speaking');
      return;
    }

    // Lượt phát đầu tiên: audio đã tải trước thì phát ngay.
    const prefetched = prefetchedRef.current;
    if (prefetched) {
      prefetchedRef.current = null;
      try {
        await startAudio(prefetched.url, prefetched.text, prefetched.verified);
        return;
      } catch {
        // play() bị chặn/lỗi giải mã — rơi xuống tải lại bên dưới.
      }
    }

    // Chưa có audio sẵn: thử audio thật (backend sinh nếu chưa có cache).
    setStatus('loading');
    const handled = await playRealAudio();
    if (handled) return;

    // Audio thật không dùng được — rơi về speechSynthesis.
    const content = text ?? (await fetchNarrationText());
    if (content) {
      speakWithBrowserVoice(content);
    } else {
      setStatus('unavailable');
    }
  }, [speechState, text, playRealAudio, startAudio, fetchNarrationText, speakWithBrowserVoice]);

  return { status, text, verified, speechState, voiceWarning, toggle };
}

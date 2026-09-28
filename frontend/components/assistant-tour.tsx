'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ArrowLeft,
  Bike,
  Footprints,
  Headphones,
  Languages,
  LoaderCircle,
  MapPin,
  Navigation,
  Play,
  Square,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  NarrationPlayer,
  distanceMeters,
  formatMeters,
  formatMinutes,
  type AssistantOverlay,
  type TourPlan,
  type TourStop,
} from '@/lib/assistant';
import { cn } from '@/lib/utils';

const DURATIONS = [60, 90, 120] as const;
// Hai ngôn ngữ backend đã tạo sẵn thuyết minh lúc khởi động (app/narration.py).
const PREWARMED_LANGUAGES = ['vi', 'en'];

type LanguageOption = { code: string; name: string; nativeName: string };
// Tới gần điểm dừng trong bán kính này thì tự đọc thuyết minh. 60 m: đủ rộng
// cho sai số GPS trong phố nhiều nhà cao tầng, đủ hẹp để không đọc trước khi
// người nghe nhìn thấy công trình.
const ARRIVE_RADIUS_METERS = 60;

/**
 * Hướng dẫn viên AI trong khung chatbot — xem backend/app/assistant.plan_tour.
 *
 * Hai cách nghe:
 * - Đi thật: tới gần điểm nào (GPS) thì tự đọc thuyết minh điểm đó.
 * - "Phát cả tour": bay bản đồ qua lần lượt từng điểm và đọc liên tục — để
 *   nghe thử tại chỗ, không cần đi bộ.
 */
export function AssistantTour({
  apiBaseUrl,
  position,
  language,
  onBack,
  onViewPoi,
  onMapOverlay,
  onFocusLocation,
}: {
  apiBaseUrl: string;
  position: { latitude: number; longitude: number };
  language: string;
  onBack: () => void;
  onViewPoi: (poiId: string) => void;
  onMapOverlay: (overlay: AssistantOverlay | null) => void;
  onFocusLocation: (latitude: number, longitude: number) => void;
}) {
  const [minutes, setMinutes] = useState<number>(90);
  const [plan, setPlan] = useState<TourPlan | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [playingId, setPlayingId] = useState<string | null>(null);
  const [nowText, setNowText] = useState<string | null>(null);
  const [visited, setVisited] = useState<string[]>([]);
  const [autoRun, setAutoRun] = useState(false);
  // Ngôn ngữ thuyết minh của tour — mặc định theo giao diện, đổi riêng được
  // (khách nước ngoài dùng giao diện tiếng Việt vẫn nghe được tiếng mẹ đẻ).
  const [narrationLanguage, setNarrationLanguage] = useState(language);
  const [languages, setLanguages] = useState<LanguageOption[]>([]);
  const [prepared, setPrepared] = useState<{ done: number; total: number } | null>(null);
  // Một trình phát cho cả vòng đời component (khởi tạo lười, không tạo lại mỗi
  // lần render).
  const [player] = useState(() => new NarrationPlayer(apiBaseUrl));
  const autoRunRef = useRef(false);

  const stopAll = useCallback(() => {
    autoRunRef.current = false;
    setAutoRun(false);
    player.stop();
    setPlayingId(null);
  }, [player]);

  // Rời chế độ tour (hoặc đóng hẳn) thì dừng đọc và gỡ lớp vẽ trên bản đồ.
  useEffect(
    () => () => {
      player.stop();
      onMapOverlay(null);
    },
    [onMapOverlay, player],
  );

  const buildPlan = useCallback(async () => {
    stopAll();
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${apiBaseUrl}/api/v1/assistant/tour`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          latitude: position.latitude,
          longitude: position.longitude,
          minutes,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as TourPlan;
      setPlan(data);
      setVisited([]);
      setNowText(null);
      if (data.status === 'ready') {
        onMapOverlay({
          line: data.geometry ?? null,
          points: data.stops.map((stop) => ({
            id: stop.poiId,
            latitude: stop.latitude,
            longitude: stop.longitude,
            label: String(stop.order),
            tone: 'stop',
            title: stop.name,
            poiId: stop.poiId,
          })),
        });
      } else {
        onMapOverlay(null);
      }
    } catch {
      setError('Chưa lên được lộ trình, bạn thử lại sau nhé.');
    } finally {
      setLoading(false);
    }
  }, [apiBaseUrl, minutes, onMapOverlay, position.latitude, position.longitude, stopAll]);

  useEffect(() => {
    const controller = new AbortController();
    fetch(`${apiBaseUrl}/api/v1/languages`, { signal: controller.signal })
      .then((res) => (res.ok ? res.json() : null))
      .then((data: { languages: LanguageOption[] } | null) => {
        if (data?.languages?.length) setLanguages(data.languages);
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, [apiBaseUrl]);

  // Chuẩn bị sẵn chữ thuyết minh cho MỌI điểm của tour ở ngôn ngữ đã chọn.
  // Chỉ vi/en được backend tạo sẵn; ngôn ngữ khác sinh lần đầu mất tới 1-2
  // phút MỖI điểm trên CPU — không chuẩn bị trước thì "Phát cả tour" đứng hình
  // giữa chừng. Tuần tự từng điểm (Ollama xử lý một yêu cầu một lúc).
  useEffect(() => {
    if (!plan || plan.status !== 'ready' || PREWARMED_LANGUAGES.includes(narrationLanguage)) {
      // oxlint-disable-next-line react/react-compiler
      setPrepared(null);
      return;
    }
    const controller = new AbortController();
    const lang = encodeURIComponent(narrationLanguage);
    void (async () => {
      let done = 0;
      setPrepared({ done, total: plan.stops.length });
      for (const stop of plan.stops) {
        try {
          await fetch(`${apiBaseUrl}/api/v1/pois/${stop.poiId}/narration?language=${lang}`, {
            signal: controller.signal,
          });
        } catch {
          if (controller.signal.aborted) return;
        }
        done += 1;
        setPrepared({ done, total: plan.stops.length });
      }
    })();
    return () => controller.abort();
  }, [apiBaseUrl, narrationLanguage, plan]);

  const narrate = useCallback(
    async (stop: TourStop) => {
      setPlayingId(stop.poiId);
      setNowText(null);
      const outcome = await player.play(stop.poiId, narrationLanguage, setNowText);
      if (outcome !== 'stopped') {
        setVisited((prev) => (prev.includes(stop.poiId) ? prev : [...prev, stop.poiId]));
      }
      setPlayingId((current) => (current === stop.poiId ? null : current));
      return outcome;
    },
    [narrationLanguage, player],
  );

  // "Phát cả tour": bay tới từng điểm rồi đọc, hết điểm này sang điểm kế.
  const runAll = useCallback(async () => {
    if (!plan || plan.status !== 'ready') return;
    autoRunRef.current = true;
    setAutoRun(true);
    for (const stop of plan.stops) {
      if (!autoRunRef.current) break;
      onFocusLocation(stop.latitude, stop.longitude);
      const outcome = await narrate(stop);
      if (outcome === 'stopped' || !autoRunRef.current) break;
      await new Promise((resolve) => setTimeout(resolve, 1200));
    }
    autoRunRef.current = false;
    setAutoRun(false);
  }, [narrate, onFocusLocation, plan]);

  // Đi thật: tới gần điểm chưa nghe thì tự đọc.
  useEffect(() => {
    if (!plan || plan.status !== 'ready' || playingId || autoRunRef.current) return;
    const arrived = plan.stops.find(
      (stop) =>
        !visited.includes(stop.poiId) &&
        distanceMeters(position, stop) <= ARRIVE_RADIUS_METERS,
    );
    // Phản ứng với hệ thống bên ngoài (vị trí GPS → phát audio), đúng việc của
    // effect; setState bên trong narrate chỉ phản ánh trạng thái trình phát.
    // oxlint-disable-next-line react/react-compiler
    if (arrived) void narrate(arrived);
  }, [narrate, plan, playingId, position, visited]);

  const ready = plan?.status === 'ready';

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2">
        <Button type="button" size="icon" variant="ghost" onClick={onBack} aria-label="Quay lại trò chuyện">
          <ArrowLeft className="size-4" />
        </Button>
        <Headphones className="size-4 text-primary" aria-hidden />
        <p className="text-sm font-semibold">Hướng dẫn viên AI</p>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3 text-sm">
        <div>
          <p className="text-xs text-muted-foreground">Bạn có bao nhiêu thời gian?</p>
          <div className="mt-1.5 flex gap-1.5">
            {DURATIONS.map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setMinutes(value)}
                className={cn(
                  'rounded-full border px-3 py-1 text-xs font-medium transition',
                  minutes === value
                    ? 'border-primary bg-primary text-primary-foreground'
                    : 'border-border hover:bg-muted',
                )}
              >
                {formatMinutes(value)}
              </button>
            ))}
          </div>
          <Button type="button" className="mt-2 w-full" onClick={() => void buildPlan()} disabled={loading}>
            {loading ? <LoaderCircle className="size-4 animate-spin" /> : <Navigation className="size-4" />}
            {plan ? 'Lên lại lộ trình' : 'Lên lộ trình đi bộ'}
          </Button>
          {error && <p className="mt-1.5 text-xs text-destructive">{error}</p>}
          <label className="mt-2 flex items-center gap-2 text-xs text-muted-foreground" translate="no">
            <Languages className="size-3.5 shrink-0" aria-hidden />
            <span className="shrink-0">Thuyết minh bằng</span>
            <select
              value={narrationLanguage}
              onChange={(event) => {
                stopAll();
                setNarrationLanguage(event.target.value);
              }}
              className="h-7 min-w-0 flex-1 rounded-md border border-input bg-background px-1.5 text-xs text-foreground"
              aria-label="Ngôn ngữ thuyết minh của tour"
            >
              {(languages.length ? languages : [{ code: 'vi', name: 'Vietnamese', nativeName: 'Tiếng Việt' }, { code: 'en', name: 'English', nativeName: 'English' }]).map((item) => (
                <option key={item.code} value={item.code}>
                  {item.nativeName}
                  {item.nativeName !== item.name ? ` · ${item.name}` : ''}
                </option>
              ))}
            </select>
          </label>
          {prepared && prepared.done < prepared.total && (
            <p className="mt-1 flex items-center gap-1 text-[11px] text-muted-foreground">
              <LoaderCircle className="size-3 animate-spin" aria-hidden />
              AI đang chuẩn bị thuyết minh: {prepared.done}/{prepared.total} điểm (lần đầu mỗi ngôn ngữ mất vài phút)
            </p>
          )}
          {narrationLanguage !== 'vi' && (
            <p className="mt-1 text-[11px] text-muted-foreground">
              Giọng đọc máy chủ hiện chỉ có tiếng Việt — ngôn ngữ khác dùng giọng đọc của thiết bị.
            </p>
          )}
        </div>

        {plan?.status === 'none' && (
          <p className="rounded-lg bg-muted px-3 py-2 text-xs text-muted-foreground">
            Quanh bạn (6 km) chưa có địa điểm nào có bài thuyết minh đã kiểm chứng. Tour chỉ đi qua
            những nơi có nguồn đáng tin — không để AI tự kể về chỗ nó không biết.
          </p>
        )}

        {ready && plan && (
          <>
            <div className="rounded-lg border border-emerald-600/20 bg-emerald-50 px-3 py-2 text-xs dark:bg-emerald-950/30">
              <p className="font-semibold text-emerald-900 dark:text-emerald-200">
                {plan.stops.length} điểm · đi bộ {formatMeters(plan.walkMeters)} (~
                {formatMinutes(plan.walkMinutes)}) · tổng ~{formatMinutes(plan.totalMinutes)}
              </p>
              <p className="mt-0.5 text-emerald-800/80 dark:text-emerald-300/80">
                Đã tính {plan.dwellMinutes} phút tham quan mỗi điểm
                {plan.approximate ? ' · quãng đường ước tính (chưa có dữ liệu đường đi bộ)' : ''}.
              </p>
              {plan.approach && (
                <p className="mt-1 flex items-center gap-1 text-emerald-900 dark:text-emerald-200">
                  {plan.approach.mode === 'motorbike' ? (
                    <Bike className="size-3.5" aria-hidden />
                  ) : (
                    <Footprints className="size-3.5" aria-hidden />
                  )}
                  Tới điểm đầu: {formatMeters(plan.approach.distanceMeters)},{' '}
                  {plan.approach.mode === 'motorbike' ? 'xe máy' : 'đi bộ'} ~
                  {formatMinutes(plan.approach.minutes)}
                </p>
              )}
            </div>

            <div className="flex gap-2">
              {autoRun ? (
                <Button type="button" variant="outline" className="flex-1" onClick={stopAll}>
                  <Square className="size-4" /> Dừng
                </Button>
              ) : (
                <Button type="button" className="flex-1" onClick={() => void runAll()}>
                  <Play className="size-4" /> Phát cả tour
                </Button>
              )}
            </div>
            <p className="text-[11px] text-muted-foreground">
              Đi bộ thật thì cứ mở trợ lý: tới cách điểm dừng {ARRIVE_RADIUS_METERS} m là tự thuyết
              minh.
            </p>

            {nowText && (
              <div className="rounded-lg bg-muted px-3 py-2 text-xs leading-relaxed">
                <p className="mb-1 font-semibold text-primary">
                  🎧 {plan.stops.find((stop) => stop.poiId === playingId)?.name ?? 'Đang thuyết minh'}
                </p>
                {nowText}
              </div>
            )}

            <ol className="space-y-1.5">
              {plan.stops.map((stop) => {
                const isPlaying = playingId === stop.poiId;
                const done = visited.includes(stop.poiId);
                return (
                  <li key={stop.poiId}>
                    {stop.legMinutes != null && (
                      <p className="flex items-center gap-1 py-0.5 pl-3 text-[11px] text-muted-foreground">
                        <Footprints className="size-3" aria-hidden />
                        {formatMinutes(stop.legMinutes)} · {formatMeters(stop.legMeters)}
                      </p>
                    )}
                    <div
                      className={cn(
                        'flex items-start gap-2 rounded-lg border px-2.5 py-2',
                        isPlaying ? 'border-primary bg-primary/5' : 'border-border',
                      )}
                    >
                      <span
                        className={cn(
                          'grid size-6 shrink-0 place-items-center rounded-full text-[11px] font-bold',
                          done ? 'bg-emerald-600 text-white' : 'bg-violet-600 text-white',
                        )}
                      >
                        {stop.order}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate font-medium">{stop.name}</p>
                        {stop.teaser && (
                          <p className="line-clamp-2 text-xs text-muted-foreground">{stop.teaser}</p>
                        )}
                        <div className="mt-1 flex gap-1.5">
                          <button
                            type="button"
                            onClick={() => {
                              if (isPlaying) {
                                stopAll();
                              } else {
                                autoRunRef.current = false;
                                setAutoRun(false);
                                onFocusLocation(stop.latitude, stop.longitude);
                                void narrate(stop);
                              }
                            }}
                            className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-semibold text-primary hover:bg-primary/15"
                          >
                            {isPlaying ? <Square className="size-3" /> : <Play className="size-3" />}
                            {isPlaying ? 'Dừng' : 'Nghe'}
                          </button>
                          <button
                            type="button"
                            onClick={() => onViewPoi(stop.poiId)}
                            className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium text-muted-foreground hover:bg-muted"
                          >
                            <MapPin className="size-3" /> Xem
                          </button>
                        </div>
                      </div>
                    </div>
                  </li>
                );
              })}
            </ol>
          </>
        )}
      </div>
    </div>
  );
}

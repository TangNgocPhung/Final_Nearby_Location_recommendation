'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ArrowLeft,
  Bike,
  Footprints,
  Headphones,
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

  const narrate = useCallback(
    async (stop: TourStop) => {
      setPlayingId(stop.poiId);
      setNowText(null);
      const outcome = await player.play(stop.poiId, language, setNowText);
      if (outcome !== 'stopped') {
        setVisited((prev) => (prev.includes(stop.poiId) ? prev : [...prev, stop.poiId]));
      }
      setPlayingId((current) => (current === stop.poiId ? null : current));
      return outcome;
    },
    [language, player],
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

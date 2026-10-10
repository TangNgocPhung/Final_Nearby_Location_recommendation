'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowLeft,
  Camera,
  CheckCircle2,
  Crosshair,
  Headphones,
  LoaderCircle,
  Lock,
  Map as MapIcon,
  MapPin,
  Navigation,
  Square,
  Trophy,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  NarrationPlayer,
  distanceMeters,
  formatMeters,
  type AssistantOverlay,
} from '@/lib/assistant';
import {
  resizeImage,
  type DiscoverResult,
  type ExploreClaim,
  type ExploreOverview,
  type ExplorePlace,
  type ExploreStory,
} from '@/lib/explore';
import { cn } from '@/lib/utils';

type Stage = 'idle' | 'preparing' | 'checking';

/**
 * Săn địa danh Sài Gòn — "Pokémon GO nhưng bắt câu chuyện".
 *
 * Luồng: chọn địa danh → đi tới → chụp ảnh → server xác nhận vị trí + ảnh →
 * mở khoá câu chuyện → nghe thuyết minh → bộ sưu tập. Xem backend/app/explore.py.
 */
export function AssistantExplore({
  apiBaseUrl,
  sessionId,
  position,
  accuracyMeters,
  language,
  onBack,
  onViewPoi,
  onMapOverlay,
  onFocusLocation,
  onPickOnMap,
  onSimulatePosition,
}: {
  apiBaseUrl: string;
  sessionId: string;
  position: { latitude: number; longitude: number };
  /** Sai số GPS (m) khi vị trí đến từ GPS thật; null/undefined với vị trí mô phỏng. */
  accuracyMeters?: number | null;
  language: string;
  onBack: () => void;
  onViewPoi: (poiId: string) => void;
  onMapOverlay: (overlay: AssistantOverlay | null) => void;
  onFocusLocation: (latitude: number, longitude: number) => void;
  onPickOnMap: (callback: ((latitude: number, longitude: number) => void) | null) => void;
  onSimulatePosition?: (latitude: number, longitude: number) => void;
}) {
  const [overview, setOverview] = useState<ExploreOverview | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // Gắn với poiId: kết quả/câu chuyện trả về muộn của địa danh A không được hiện
  // dưới địa danh B mà người chơi vừa chuyển sang trong lúc chờ AI xem ảnh.
  const [storyState, setStoryState] = useState<
    { poiId: string; story: ExploreStory | null; failed: boolean } | null
  >(null);
  const [submittingName, setSubmittingName] = useState<string | null>(null);
  const [stage, setStage] = useState<Stage>('idle');
  const [elapsed, setElapsed] = useState(0);
  const [preview, setPreview] = useState<string | null>(null);
  const [result, setResult] = useState<DiscoverResult | null>(null);
  const [sharePublicly, setSharePublicly] = useState(true);
  const [narrationText, setNarrationText] = useState<string | null>(null);
  const [narrating, setNarrating] = useState(false);
  const [player] = useState(() => new NarrationPlayer(apiBaseUrl));
  const fileRef = useRef<HTMLInputElement>(null);
  const headers = useMemo(() => ({ 'X-Session-ID': sessionId }), [sessionId]);
  // Chỉ tải danh sách khi mở màn hình và sau mỗi lượt khám phá — khoảng cách
  // tới từng địa danh được tính lại tại chỗ khi vị trí đổi (xem `places`), nên
  // `load` đọc vị trí qua ref thay vì chạy lại mỗi lần GPS nhích vài mét.
  const positionRef = useRef(position);
  useEffect(() => {
    positionRef.current = position;
  }, [position]);

  const load = useCallback(async () => {
    try {
      const params = new URLSearchParams({
        lat: String(positionRef.current.latitude),
        lng: String(positionRef.current.longitude),
      });
      const res = await fetch(`${apiBaseUrl}/api/v1/explore?${params}`, { headers });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setOverview((await res.json()) as ExploreOverview);
      setLoadError(false);
    } catch {
      setLoadError(true);
    }
  }, [apiBaseUrl, headers]);

  useEffect(() => {
    // oxlint-disable-next-line react/react-compiler
    void load();
  }, [load]);

  useEffect(
    () => () => {
      player.stop();
      onMapOverlay(null);
    },
    [onMapOverlay, player],
  );

  // Khoảng cách tính lại theo vị trí HIỆN TẠI (GPS di chuyển liên tục).
  const places = useMemo(() => {
    if (!overview) return [];
    return overview.places
      .map((place) => ({ ...place, distanceMeters: distanceMeters(position, place) }))
      .sort((a, b) => a.distanceMeters - b.distanceMeters);
  }, [overview, position]);

  const selected = places.find((place) => place.poiId === selectedId) ?? null;
  const story = selected && storyState?.poiId === selected.poiId ? storyState : null;
  const shownResult = selected && result?.poiId === selected.poiId ? result : null;

  // Bản đồ săn: địa danh chưa khám phá là "?", đã khám phá là "✓".
  useEffect(() => {
    if (!places.length) return;
    onMapOverlay({
      line: null,
      points: places.map((place) => ({
        id: place.poiId,
        latitude: place.latitude,
        longitude: place.longitude,
        label: place.discovered ? '✓' : '?',
        tone: place.discovered ? 'result' : 'stop',
        title: place.discovered ? place.name : `${place.name} · chưa khám phá`,
        poiId: place.poiId,
      })),
    });
  }, [onMapOverlay, places]);

  // Mở một địa danh đã khám phá → tải câu chuyện. Câu chuyện của địa danh khác
  // (state cũ) bị bỏ qua nhờ khoá poiId ở `story` phía trên.
  const [storyAttempt, setStoryAttempt] = useState(0);
  useEffect(() => {
    if (!selected?.discovered) return;
    const poiId = selected.poiId;
    const controller = new AbortController();
    fetch(`${apiBaseUrl}/api/v1/explore/${poiId}/story`, { headers, signal: controller.signal })
      .then((res): Promise<{ locked: boolean; story?: ExploreStory }> => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data) => {
        if (data.locked || !data.story) throw new Error('locked');
        setStoryState({ poiId, story: data.story, failed: false });
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        // Giữ câu chuyện đã có từ phản hồi khám phá nếu lần tải lại này hỏng.
        setStoryState((prev) => (prev?.poiId === poiId && prev.story ? prev : { poiId, story: null, failed: true }));
      });
    return () => controller.abort();
  }, [apiBaseUrl, headers, selected?.discovered, selected?.poiId, storyAttempt]);

  // Đồng hồ chờ AI xem ảnh — model thị giác trên CPU mất vài chục giây, người
  // chơi cần thấy hệ thống vẫn đang làm việc.
  useEffect(() => {
    if (stage !== 'checking') return;
    const started = Date.now();
    const timer = setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [stage]);

  const openPlace = useCallback(
    (place: ExplorePlace) => {
      player.stop();
      setNarrating(false);
      setNarrationText(null);
      setResult(null);
      setPreview(null);
      setSelectedId(place.poiId);
      onFocusLocation(place.latitude, place.longitude);
    },
    [onFocusLocation, player],
  );

  const backToList = useCallback(() => {
    player.stop();
    setNarrating(false);
    setSelectedId(null);
    setResult(null);
    setPreview(null);
  }, [player]);

  const narrate = useCallback(async () => {
    if (!selected) return;
    if (narrating) {
      player.stop();
      setNarrating(false);
      return;
    }
    setNarrating(true);
    setNarrationText(null);
    await player.play(selected.poiId, language, setNarrationText);
    setNarrating(false);
  }, [language, narrating, player, selected]);

  const submitPhoto = async (file: File, target: ExplorePlace) => {
    setResult(null);
    setStage('preparing');
    setSubmittingName(target.name);
    try {
      const outcome = await sendDiscovery({
        apiBaseUrl,
        headers,
        file,
        place: target,
        body: {
          latitude: position.latitude,
          longitude: position.longitude,
          accuracy_meters: accuracyMeters ?? null,
          share_publicly: sharePublicly,
        },
        onResized: (previewUrl) => {
          setPreview(previewUrl);
          setStage('checking');
          setElapsed(0);
        },
      });
      if (outcome.kind === 'failed') {
        setResult({
          status: 'bad_image',
          poiId: target.poiId,
          name: target.name,
          detail: outcome.detail,
          distanceMeters: target.distanceMeters,
          allowedMeters: target.radiusMeters,
        });
        // Máy chủ có thể vẫn xử lý xong sau khi cổng đã ngắt: tải lại để thấy kết quả.
        if (outcome.reload) await load();
        return;
      }
      const data = outcome.data;
      setResult(data);
      if (data.status === 'discovered' || data.status === 'rediscovered') {
        setStoryState({ poiId: data.poiId, story: data.story, failed: false });
        await load();
      }
    } finally {
      setStage('idle');
      setSubmittingName(null);
    }
  };

  const simulateHere = useCallback(() => {
    if (!onSimulatePosition) return;
    onPickOnMap((latitude, longitude) => onSimulatePosition(latitude, longitude));
  }, [onPickOnMap, onSimulatePosition]);

  const percent = overview && overview.total ? Math.round((overview.discovered / overview.total) * 100) : 0;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2">
        <Button
          type="button"
          size="icon"
          variant="ghost"
          onClick={selected ? backToList : onBack}
          aria-label={selected ? 'Về danh sách địa danh' : 'Quay lại trò chuyện'}
        >
          <ArrowLeft className="size-4" />
        </Button>
        <MapIcon className="size-4 text-primary" aria-hidden />
        <p className="flex-1 text-sm font-semibold">Săn địa danh Sài Gòn</p>
        {overview && (
          <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-bold text-primary tabular-nums">
            {overview.discovered}/{overview.total}
          </span>
        )}
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3 text-sm">
        {loadError && (
          <p className="rounded-lg bg-destructive/10 px-3 py-2 text-xs text-destructive">
            Chưa tải được bản đồ săn. Bạn thử mở lại sau nhé.
          </p>
        )}
        {!overview && !loadError && (
          <p className="flex items-center gap-2 py-6 text-muted-foreground">
            <LoaderCircle className="size-4 animate-spin" /> Đang tải bản đồ săn…
          </p>
        )}

        {overview && !selected && (
          <>
            <div className="rounded-xl border border-emerald-600/20 bg-gradient-to-br from-emerald-50 to-amber-50 px-3 py-2.5 dark:from-emerald-950/40 dark:to-amber-950/20">
              <p className="text-xs leading-relaxed text-emerald-950 dark:text-emerald-100">
                Đi tới địa danh, chụp một tấm ảnh để <strong>mở khoá câu chuyện</strong> và nghe AI
                thuyết minh. Ảnh của bạn giúp Nearby có thêm ảnh thật của thành phố.
              </p>
              <div className="mt-2 h-2 overflow-hidden rounded-full bg-emerald-900/10">
                <div className="h-full rounded-full bg-emerald-600 transition-all" style={{ width: `${percent}%` }} />
              </div>
              <p className="mt-1 text-[11px] font-medium text-emerald-900/80 dark:text-emerald-200/80">
                Đã khám phá {overview.discovered}/{overview.total} địa danh
              </p>
            </div>

            <div>
              <p className="mb-1.5 text-xs font-semibold text-muted-foreground">Bộ sưu tập</p>
              <div className="grid grid-cols-2 gap-1.5">
                {overview.collections.map((collection) => (
                  <div
                    key={collection.id}
                    title={collection.description}
                    className={cn(
                      'rounded-lg border px-2 py-1.5',
                      collection.completed
                        ? 'border-amber-500/50 bg-amber-50 dark:bg-amber-950/30'
                        : 'border-border',
                    )}
                  >
                    <p className="flex items-center gap-1 truncate text-xs font-semibold">
                      <span aria-hidden>{collection.icon}</span>
                      <span className="truncate">{collection.title}</span>
                      {collection.completed && <Trophy className="size-3 shrink-0 text-amber-600" aria-label="Đã hoàn thành" />}
                    </p>
                    <p className="text-[11px] text-muted-foreground tabular-nums">
                      {collection.discovered}/{collection.total}
                    </p>
                  </div>
                ))}
              </div>
            </div>

            {onSimulatePosition && (
              <button
                type="button"
                onClick={simulateHere}
                className="flex w-full items-center gap-2 rounded-lg border border-dashed border-border px-3 py-2 text-left text-xs text-muted-foreground hover:bg-muted"
              >
                <Crosshair className="size-4 shrink-0" />
                <span>
                  Không có GPS (máy tính)? <strong className="text-foreground">Chạm bản đồ để đặt vị trí</strong> —
                  vị trí mô phỏng dùng khi trình diễn.
                </span>
              </button>
            )}

            <ul className="space-y-1.5">
              {places.map((place) => {
                const inRange = place.distanceMeters <= place.radiusMeters;
                return (
                  <li key={place.poiId}>
                    <button
                      type="button"
                      onClick={() => openPlace(place)}
                      className={cn(
                        'flex w-full items-center gap-2.5 rounded-lg border px-2.5 py-2 text-left transition hover:bg-muted',
                        inRange && !place.discovered ? 'border-emerald-500 bg-emerald-50/60 dark:bg-emerald-950/20' : 'border-border',
                      )}
                    >
                      {place.photoThumb ? (
                        <img src={place.photoThumb} alt="" className="size-10 shrink-0 rounded-md object-cover" />
                      ) : (
                        <span
                          className={cn(
                            'grid size-10 shrink-0 place-items-center rounded-md',
                            place.discovered ? 'bg-emerald-600 text-white' : 'bg-muted text-muted-foreground',
                          )}
                        >
                          {place.discovered ? <CheckCircle2 className="size-5" /> : <Lock className="size-4" />}
                        </span>
                      )}
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium">{place.name}</span>
                        <span className="block truncate text-[11px] text-muted-foreground">
                          {place.discovered ? '✓ Đã khám phá' : place.teaser}
                        </span>
                      </span>
                      <span className="shrink-0 text-right text-[11px]">
                        {inRange && !place.discovered ? (
                          <span className="font-semibold text-emerald-700 dark:text-emerald-400">Trong tầm!</span>
                        ) : (
                          <span className="text-muted-foreground">{formatMeters(place.distanceMeters)}</span>
                        )}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </>
        )}

        {selected && (
          <div className="space-y-3">
            <div>
              <p className="text-base font-semibold leading-tight">{selected.name}</p>
              <p className="text-xs text-muted-foreground">
                {selected.categoryLabel} · cách {formatMeters(selected.distanceMeters)}
              </p>
              <div className="mt-1.5 flex flex-wrap gap-1">
                {overview?.collections
                  .filter((collection) => selected.collections.includes(collection.id))
                  .map((collection) => (
                    <span key={collection.id} className="rounded-full bg-muted px-2 py-0.5 text-[11px]">
                      {collection.icon} {collection.title}
                    </span>
                  ))}
              </div>
            </div>

            {shownResult && <DiscoverOutcome result={shownResult} />}

            {!selected.discovered && (
              <div className="space-y-2 rounded-xl border border-border p-3">
                <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Lock className="size-3.5" /> {selected.teaser} — tới nơi để mở khoá.
                </p>
                {selected.distanceMeters <= selected.radiusMeters ? (
                  <p className="text-xs font-semibold text-emerald-700 dark:text-emerald-400">
                    ✅ Bạn đang trong tầm khám phá. Chụp một tấm ảnh {selected.name} nhé!
                  </p>
                ) : (
                  <p className="text-xs">
                    Còn cách <strong>{formatMeters(selected.distanceMeters)}</strong> — cần tới trong vòng{' '}
                    {formatMeters(selected.radiusMeters)}.
                  </p>
                )}
                <div className="flex gap-2">
                  <Button type="button" variant="outline" size="sm" className="flex-1" onClick={() => onViewPoi(selected.poiId)}>
                    <Navigation className="size-4" /> Chỉ đường
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    className="flex-1"
                    disabled={stage !== 'idle'}
                    onClick={() => fileRef.current?.click()}
                  >
                    <Camera className="size-4" /> Chụp ảnh khám phá
                  </Button>
                </div>
                <label className="flex items-start gap-2 text-[11px] text-muted-foreground">
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={sharePublicly}
                    onChange={(event) => setSharePublicly(event.target.checked)}
                  />
                  Góp ảnh vào kho ảnh công khai của địa điểm (chỉ khi AI xác nhận đúng nơi). Bỏ chọn nếu ảnh có
                  người thân.
                </label>
              </div>
            )}

            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              capture="environment"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = '';
                if (file && selected) void submitPhoto(file, selected);
              }}
            />

            {stage !== 'idle' && (
              <div className="flex items-center gap-3 rounded-xl bg-muted px-3 py-2.5">
                {preview && (
                  <img src={preview} alt="Ảnh vừa chụp" className="size-14 rounded-md object-cover" />
                )}
                <div className="text-xs">
                  <p className="flex items-center gap-1.5 font-semibold">
                    <LoaderCircle className="size-3.5 animate-spin" />
                    {stage === 'preparing' ? 'Đang xử lý ảnh…' : 'Kiểm tra vị trí · AI đang xem ảnh…'}
                    {submittingName && submittingName !== selected.name ? ` (${submittingName})` : ''}
                  </p>
                  {stage === 'checking' && (
                    <p className="mt-0.5 text-muted-foreground tabular-nums">
                      {elapsed}s — model thị giác chạy ngay trên máy chủ, có thể mất tới 1-2 phút.
                    </p>
                  )}
                </div>
              </div>
            )}

            {selected.discovered && (
              <div className="space-y-2">
                {selected.photoThumb && (
                  <div className="relative">
                    <img src={selected.photoThumb} alt={`Ảnh bạn chụp tại ${selected.name}`} className="h-36 w-full rounded-xl object-cover" />
                    <span className="absolute bottom-1.5 left-1.5 rounded-full bg-black/60 px-2 py-0.5 text-[11px] text-white">
                      {selected.photoStatus === 'verified' ? '✓ Ảnh đã được AI xác minh' : 'Ảnh đang chờ xác minh'}
                    </span>
                  </div>
                )}
                <Button type="button" className="w-full" onClick={() => void narrate()}>
                  {narrating ? <Square className="size-4" /> : <Headphones className="size-4" />}
                  {narrating ? 'Dừng thuyết minh' : 'Nghe AI thuyết minh'}
                </Button>
                {narrationText && (
                  <p className="rounded-lg bg-muted px-3 py-2 text-xs leading-relaxed">{narrationText}</p>
                )}
                {story?.story ? (
                  <StoryView story={story.story} />
                ) : story?.failed ? (
                  <p className="flex items-center justify-between gap-2 rounded-lg bg-destructive/10 px-3 py-2 text-xs text-destructive">
                    Chưa mở được câu chuyện.
                    <button
                      type="button"
                      className="font-semibold underline"
                      onClick={() => {
                        setStoryState(null);
                        setStoryAttempt((value) => value + 1);
                      }}
                    >
                      Thử lại
                    </button>
                  </p>
                ) : (
                  <p className="flex items-center gap-2 text-xs text-muted-foreground">
                    <LoaderCircle className="size-3.5 animate-spin" /> Đang mở câu chuyện…
                  </p>
                )}
                <div className="flex gap-2">
                  <Button type="button" variant="outline" size="sm" className="flex-1" onClick={() => onViewPoi(selected.poiId)}>
                    <MapPin className="size-4" /> Xem địa điểm
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="flex-1"
                    disabled={stage !== 'idle'}
                    onClick={() => fileRef.current?.click()}
                  >
                    <Camera className="size-4" /> Góp thêm ảnh
                  </Button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

type DiscoveryOutcome =
  | { kind: 'ok'; data: DiscoverResult }
  | { kind: 'failed'; detail: string; reload: boolean };

/** Thu nhỏ ảnh rồi gửi lượt khám phá; mọi lỗi đổi thành thông báo đúng nguyên nhân. */
async function sendDiscovery({
  apiBaseUrl,
  headers,
  file,
  place,
  body,
  onResized,
}: {
  apiBaseUrl: string;
  headers: Record<string, string>;
  file: File;
  place: ExplorePlace;
  body: Record<string, unknown>;
  onResized: (previewUrl: string) => void;
}): Promise<DiscoveryOutcome> {
  let prepared: Awaited<ReturnType<typeof resizeImage>>;
  try {
    prepared = await resizeImage(file);
  } catch {
    return { kind: 'failed', reload: false, detail: 'Không đọc được ảnh này — thử chụp lại hoặc chọn ảnh JPEG/PNG khác.' };
  }
  onResized(prepared.previewUrl);
  let res: Response;
  try {
    res = await fetch(`${apiBaseUrl}/api/v1/explore/${place.poiId}/discover`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...headers },
      body: JSON.stringify({ ...body, image_base64: prepared.base64 }),
    });
  } catch {
    return { kind: 'failed', reload: false, detail: 'Không gửi được ảnh — kiểm tra kết nối rồi thử lại.' };
  }
  if (res.ok) return { kind: 'ok', data: (await res.json()) as DiscoverResult };
  if (res.status === 429) {
    return { kind: 'failed', reload: false, detail: 'Bạn thao tác hơi nhanh — chờ khoảng một phút rồi thử lại.' };
  }
  if (res.status === 502 || res.status === 504) {
    return {
      kind: 'failed',
      reload: true,
      detail: 'Máy chủ xem ảnh quá lâu. Lượt khám phá có thể vẫn được ghi nhận — kiểm tra lại danh sách sau ít phút.',
    };
  }
  return { kind: 'failed', reload: false, detail: `Máy chủ gặp lỗi (HTTP ${res.status}) — thử lại sau nhé.` };
}

function DiscoverOutcome({ result }: { result: DiscoverResult }) {
  if (result.status === 'too_far') {
    return (
      <p className="rounded-lg bg-amber-100 px-3 py-2 text-xs text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
        📍 Bạn đang cách {result.name} {formatMeters(result.distanceMeters)} — cần tới trong vòng{' '}
        {formatMeters(result.allowedMeters)} mới khám phá được.
      </p>
    );
  }
  if (result.status === 'bad_image') {
    return <p className="rounded-lg bg-destructive/10 px-3 py-2 text-xs text-destructive">{result.detail}</p>;
  }
  if (result.status === 'photo_rejected') {
    return (
      <p className="rounded-lg bg-amber-100 px-3 py-2 text-xs text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
        🤔 AI thấy trong ảnh: “{result.verification?.seen || 'không rõ'}” — có vẻ chưa phải {result.name}. Bạn chụp rõ
        công trình, cổng hoặc biển tên hơn nhé.
      </p>
    );
  }
  const firstTime = result.status === 'discovered';
  return (
    <div className="space-y-1.5 rounded-xl border border-emerald-500/40 bg-emerald-50 px-3 py-2.5 text-xs dark:bg-emerald-950/30">
      <p className="text-sm font-bold text-emerald-800 dark:text-emerald-200">
        {firstTime ? `🎉 Đã khám phá ${result.name}!` : '📸 Đã thêm ảnh mới'}
      </p>
      <p className="text-emerald-900/80 dark:text-emerald-200/80">
        {result.photo.status === 'verified'
          ? result.photo.isPublic
            ? '✓ AI xác nhận ảnh đúng địa danh — ảnh đã góp vào kho ảnh của Nearby.'
            : '✓ AI xác nhận ảnh đúng địa danh (ảnh chỉ mình bạn xem).'
          : 'Vị trí đã đúng. Ảnh chưa được AI xác nhận nên tạm chưa công khai.'}
        {result.verification?.seen ? ` AI thấy: “${result.verification.seen}”.` : ''}
      </p>
      {firstTime && (
        <p className="font-medium text-emerald-900 dark:text-emerald-100">
          Tiến độ: {result.progress.discovered}/{result.progress.total} địa danh
        </p>
      )}
      {result.completedCollections.map((collection) => (
        <p key={collection.id} className="flex items-center gap-1.5 rounded-lg bg-amber-100 px-2 py-1 font-semibold text-amber-900 dark:bg-amber-900/40 dark:text-amber-100">
          <Trophy className="size-3.5" /> Hoàn thành bộ sưu tập {collection.icon} {collection.title}!
        </p>
      ))}
    </div>
  );
}

function claimKey(item: ExploreClaim): string {
  return `${item.source ?? ''}|${item.title ?? ''}|${item.description}`;
}

function ClaimItem({ item }: { item: ExploreClaim }) {
  return (
    <li>
      {item.title && <span className="font-medium">{item.title}: </span>}
      {item.description}
      {item.source && /^https?:\/\//.test(item.source) && (
        <a
          href={item.source}
          target="_blank"
          rel="noopener noreferrer"
          className="ml-1 text-[11px] text-primary underline"
        >
          nguồn
        </a>
      )}
    </li>
  );
}

function StoryView({ story }: { story: ExploreStory }) {
  return (
    <div className="space-y-2 rounded-xl border border-border p-3 text-xs leading-relaxed">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-primary">
        Câu chuyện {story.contentTypeLabel}
      </p>
      {story.intro && <p>{story.intro}</p>}
      {story.specialty && <p>{story.specialty}</p>}
      {story.historicalContext && (
        <div>
          <p className="font-semibold">Bối cảnh</p>
          <p>{story.historicalContext}</p>
        </div>
      )}
      {story.historicalEvents.length > 0 && (
        <div>
          <p className="font-semibold">Sự kiện</p>
          <ul className="list-disc space-y-0.5 pl-4">
            {story.historicalEvents.map((item) => (
              <ClaimItem key={claimKey(item)} item={item} />
            ))}
          </ul>
        </div>
      )}
      {story.interestingFacts.length > 0 && (
        <div>
          <p className="font-semibold">Điều thú vị</p>
          <ul className="list-disc space-y-0.5 pl-4">
            {story.interestingFacts.map((item) => (
              <ClaimItem key={claimKey(item)} item={item} />
            ))}
          </ul>
        </div>
      )}
      {story.source && <p className="text-[11px] text-muted-foreground">Nguồn: {story.source}</p>}
    </div>
  );
}

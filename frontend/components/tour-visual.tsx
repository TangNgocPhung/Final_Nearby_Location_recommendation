'use client';

import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { ImageOff, MapPin } from 'lucide-react';

import { PhotoCaption, type PoiPhoto, type PoiPhotos } from '@/components/poi-detail-panel';
import {
  StreetViewCaption,
  panoCenterX,
  type StreetImage,
  type StreetViews,
} from '@/components/street-view';
import type { TourStop } from '@/lib/assistant';
import { cn } from '@/lib/utils';

/**
 * Phần "nhìn" của tour thuyết minh: tai nghe giọng đọc thì mắt thấy chính nơi
 * đang được kể — ảnh trình chiếu của điểm dừng, dải tiến độ cả tour và chữ
 * thuyết minh tô sáng theo câu đang đọc.
 *
 * Nguồn ảnh giữ đúng nguyên tắc của panel chi tiết: ưu tiên ảnh CỦA địa điểm
 * (`confidence=place`), không có thì mới tới ảnh đường phố Mapillary nhìn về
 * phía địa điểm — và luôn ghi rõ đó là loại nào. Không có ảnh thì nói thẳng là
 * chưa có, không lấy "ảnh khu vực" chụp con phố bên cạnh ra trình chiếu như
 * thể đó là công trình đang được thuyết minh.
 */

// Mỗi tấm ở lại bao lâu khi trình chiếu (khớp thời lượng hiệu ứng Ken Burns
// trong globals.css).
const SLIDE_MS = 7000;
const MAX_STAGE_PHOTOS = 4;

export type TourImage =
  | { kind: 'photo'; key: string; photo: PoiPhoto }
  | { kind: 'street'; key: string; image: StreetImage; license?: string };

/** `null` = đang tải; mảng rỗng = đã hỏi xong, không có ảnh nào dùng được. */
export type TourVisuals = Record<string, TourImage[] | null>;

async function loadStopImages(
  apiBaseUrl: string,
  poiId: string,
  signal: AbortSignal,
): Promise<TourImage[]> {
  try {
    const res = await fetch(
      `${apiBaseUrl}/api/v1/pois/${poiId}/photos?limit=${MAX_STAGE_PHOTOS}&confidence=place`,
      { signal, cache: 'no-store' },
    );
    if (res.ok) {
      const data = (await res.json()) as PoiPhotos;
      const place = data.photos.filter((photo) => photo.confidence === 'place');
      if (place.length) {
        return place.map((photo) => ({ kind: 'photo', key: photo.id, photo }));
      }
    }
  } catch (error) {
    if (signal.aborted) throw error;
  }
  try {
    const res = await fetch(`${apiBaseUrl}/api/v1/pois/${poiId}/streetview`, { signal });
    if (res.ok) {
      const views = (await res.json()) as StreetViews;
      if (views.status === 'ready') {
        // Ảnh chụp thẳng mặt tiền trước, ảnh 360° sau — cả hai đều có thì
        // trình chiếu được hai góc.
        return [views.facing, views.pano]
          .filter((image): image is StreetImage => image?.thumbUrl != null)
          .map((image) => ({
            kind: 'street',
            key: image.imageId,
            image,
            license: views.license,
          }));
      }
    }
  } catch (error) {
    if (signal.aborted) throw error;
  }
  return [];
}

/**
 * Ảnh cho mọi điểm của tour. Tuần tự từng điểm, điểm đầu trước: `/photos` có
 * thể phải hỏi Wikimedia (bắt giãn nhịp ≥ 1 giây) — bắn song song cả tour là
 * tự chuốc HTTP 429, mà người nghe thì cũng chỉ thấy điểm đầu trước tiên.
 */
export function useTourVisuals(apiBaseUrl: string, stops: TourStop[] | null): TourVisuals {
  const [visuals, setVisuals] = useState<TourVisuals>({});

  useEffect(() => {
    if (!stops?.length) {
      // oxlint-disable-next-line react/react-compiler
      setVisuals({});
      return;
    }
    const controller = new AbortController();
    setVisuals(Object.fromEntries(stops.map((stop) => [stop.poiId, null])));
    void (async () => {
      for (const stop of stops) {
        try {
          const images = await loadStopImages(apiBaseUrl, stop.poiId, controller.signal);
          setVisuals((prev) => ({ ...prev, [stop.poiId]: images }));
        } catch {
          return;
        }
      }
    })();
    return () => controller.abort();
  }, [apiBaseUrl, stops]);

  return visuals;
}

function imageSrc(item: TourImage, thumb = false): string {
  if (item.kind === 'photo') return thumb ? item.photo.thumbUrl : item.photo.url;
  return item.image.thumbUrl ?? '';
}

function imageStyle(item: TourImage): CSSProperties | undefined {
  return item.kind === 'street' && item.image.isPano
    ? { objectPosition: `${panoCenterX(item.image) * 100}% 50%` }
    : undefined;
}

/** Ảnh nhỏ thay cho chấm số thứ tự trong danh sách điểm dừng. */
export function TourThumb({
  images,
  order,
  done,
  active,
}: {
  images: TourImage[] | null | undefined;
  order: number;
  done: boolean;
  active: boolean;
}) {
  const first = images?.[0];
  return (
    <span
      className={cn(
        'relative block size-12 shrink-0 overflow-hidden rounded-lg bg-muted ring-2',
        active ? 'ring-primary' : 'ring-transparent',
      )}
    >
      {first ? (
        <img
          src={imageSrc(first, true)}
          alt=""
          className="size-full object-cover"
          style={imageStyle(first)}
          loading="lazy"
          referrerPolicy="no-referrer"
        />
      ) : images === null ? (
        <span className="block size-full animate-pulse bg-muted-foreground/15" />
      ) : (
        <span className="grid size-full place-items-center bg-gradient-to-br from-emerald-100 to-violet-100 text-violet-700 dark:from-emerald-950 dark:to-violet-950 dark:text-violet-300">
          <MapPin className="size-4" aria-hidden />
        </span>
      )}
      <span
        className={cn(
          'absolute bottom-0.5 left-0.5 grid size-5 place-items-center rounded-full text-[10px] font-bold text-white shadow',
          done ? 'bg-emerald-600' : 'bg-violet-600',
        )}
      >
        {order}
      </span>
    </span>
  );
}

/** Tách bài thuyết minh thành câu, giữ vị trí ký tự để khớp tiến độ đọc. */
function splitSentences(text: string): { text: string; end: number }[] {
  const parts = text.match(/[^.!?…。！？]+[.!?…。！？]*\s*/g) ?? [text];
  let end = 0;
  return parts.map((part) => {
    end += part.length;
    return { text: part, end };
  });
}

function Transcript({ text, progress }: { text: string; progress: number | null }) {
  const sentences = useMemo(() => splitSentences(text), [text]);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const activeRef = useRef<HTMLSpanElement | null>(null);
  const position = progress == null ? -1 : progress * text.length;
  const reached = sentences.findIndex((sentence) => sentence.end > position);
  const activeIndex = progress == null ? -1 : reached === -1 ? sentences.length - 1 : reached;

  // Cuộn câu đang đọc vào giữa khung chữ — chỉ cuộn khung này, không dùng
  // scrollIntoView vì nó kéo cả khung chatbot lẫn trang theo.
  useEffect(() => {
    const container = containerRef.current;
    const active = activeRef.current;
    if (!container || !active) return;
    container.scrollTo({
      top: active.offsetTop - container.clientHeight / 3,
      behavior: 'smooth',
    });
  }, [activeIndex]);

  return (
    <div
      ref={containerRef}
      className="relative max-h-36 overflow-y-auto px-3 py-2 text-[13px] leading-relaxed"
    >
      {sentences.map((sentence, index) => (
        <span
          key={index}
          ref={index === activeIndex ? activeRef : undefined}
          className={cn(
            'rounded transition-colors duration-300',
            activeIndex === -1
              ? 'text-foreground'
              : index === activeIndex
                ? 'bg-primary/10 font-medium text-foreground'
                : index < activeIndex
                  ? 'text-muted-foreground'
                  : 'text-muted-foreground/70',
          )}
        >
          {sentence.text}
        </span>
      ))}
    </div>
  );
}

function SoundBars() {
  return (
    <span className="tour-sound-bars inline-flex h-3 items-end gap-[2px]" aria-hidden>
      <span />
      <span />
      <span />
    </span>
  );
}

/**
 * Sân khấu của tour: ảnh trình chiếu của điểm đang kể (hoặc đang chọn), dải
 * tiến độ cả tour và chữ thuyết minh chạy theo giọng đọc.
 */
export function TourStage({
  stops,
  stop,
  images,
  visited,
  playing,
  text,
  progress,
  onSelect,
}: {
  stops: TourStop[];
  stop: TourStop;
  images: TourImage[] | null | undefined;
  visited: string[];
  playing: boolean;
  text: string | null;
  progress: number | null;
  onSelect: (stop: TourStop) => void;
}) {
  const [slide, setSlide] = useState({ poiId: stop.poiId, index: 0 });
  const count = images?.length ?? 0;
  // Đổi điểm thì quay về tấm đầu — so poiId ngay lúc render thay vì reset
  // trong effect (tránh một khung hình hiện nhầm tấm thứ n của điểm cũ).
  const index = slide.poiId === stop.poiId && slide.index < count ? slide.index : 0;

  useEffect(() => {
    if (count < 2) return;
    const timer = setInterval(
      () =>
        setSlide((prev) => ({
          poiId: stop.poiId,
          index: ((prev.poiId === stop.poiId ? prev.index : 0) + 1) % count,
        })),
      SLIDE_MS,
    );
    return () => clearInterval(timer);
  }, [count, stop.poiId]);

  const current = images?.[index];

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card shadow-sm">
      <div className="relative aspect-[16/10] w-full overflow-hidden bg-muted">
        {images?.map((item, itemIndex) => (
          <img
            key={`${stop.poiId}-${item.key}`}
            src={imageSrc(item)}
            alt={itemIndex === index ? `Ảnh ${stop.name}` : ''}
            referrerPolicy="no-referrer"
            className={cn(
              'absolute inset-0 size-full object-cover transition-opacity duration-1000',
              itemIndex === index ? 'opacity-100' : 'opacity-0',
              itemIndex === index && playing && 'tour-ken-burns',
            )}
            style={imageStyle(item)}
          />
        ))}
        {images === null && <div className="absolute inset-0 animate-pulse bg-muted-foreground/15" />}
        {images && images.length === 0 && (
          <div className="absolute inset-0 grid place-items-center bg-gradient-to-br from-emerald-100 via-teal-50 to-violet-100 text-center text-violet-800 dark:from-emerald-950 dark:via-slate-900 dark:to-violet-950 dark:text-violet-200">
            <div className="px-6">
              <ImageOff className="mx-auto mb-1 size-6 opacity-60" aria-hidden />
              <p className="text-xs">Chưa có ảnh của chính địa điểm này</p>
            </div>
          </div>
        )}

        {current && (
          <span
            className={cn(
              'absolute left-2 top-2 rounded-full px-2 py-0.5 text-[10px] font-semibold text-white shadow-sm',
              current.kind === 'photo' ? 'bg-emerald-700/90' : 'bg-sky-600/95',
            )}
          >
            {current.kind === 'photo' ? 'Ảnh địa điểm' : 'Ảnh đường phố'}
          </span>
        )}
        {playing && (
          <span className="absolute right-2 top-2 inline-flex items-center gap-1.5 rounded-full bg-black/60 px-2 py-0.5 text-[10px] font-semibold text-white">
            <SoundBars /> Đang thuyết minh
          </span>
        )}

        <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/75 via-black/35 to-transparent px-3 pb-2.5 pt-10 text-white">
          <p className="text-[11px] font-medium uppercase tracking-wide text-white/80">
            Điểm {stop.order}/{stops.length}
          </p>
          <p className="line-clamp-2 text-base font-semibold leading-snug drop-shadow">{stop.name}</p>
        </div>

        {count > 1 && (
          <div className="absolute bottom-2.5 right-3 flex gap-1">
            {images?.map((item, itemIndex) => (
              <button
                key={item.key}
                type="button"
                onClick={() => setSlide({ poiId: stop.poiId, index: itemIndex })}
                aria-label={`Ảnh ${itemIndex + 1}`}
                className={cn(
                  'size-1.5 rounded-full transition',
                  itemIndex === index ? 'w-4 bg-white' : 'bg-white/50 hover:bg-white/80',
                )}
              />
            ))}
          </div>
        )}
      </div>

      {current &&
        (current.kind === 'photo' ? (
          <PhotoCaption photo={current.photo} className="px-3 pt-1.5" />
        ) : (
          <StreetViewCaption image={current.image} license={current.license} className="px-3 pt-1.5" />
        ))}

      {/* Dải tiến độ cả tour: đã nghe / đang ở / chưa tới. Bấm để chuyển điểm. */}
      <div className="flex gap-1 px-3 pt-2">
        {stops.map((item) => {
          const isCurrent = item.poiId === stop.poiId;
          const done = visited.includes(item.poiId);
          return (
            <button
              key={item.poiId}
              type="button"
              onClick={() => onSelect(item)}
              title={`${item.order}. ${item.name}`}
              aria-label={`Điểm ${item.order}: ${item.name}`}
              aria-current={isCurrent ? 'step' : undefined}
              className={cn(
                'relative h-1.5 flex-1 overflow-hidden rounded-full transition',
                done ? 'bg-emerald-500' : 'bg-muted-foreground/20 hover:bg-muted-foreground/35',
              )}
            >
              {isCurrent && (
                <span
                  className="absolute inset-y-0 left-0 rounded-full bg-primary transition-[width] duration-500"
                  style={{ width: `${Math.round((playing ? (progress ?? 0) : done ? 1 : 0) * 100)}%` }}
                />
              )}
            </button>
          );
        })}
      </div>

      {text ? (
        <Transcript text={text} progress={playing ? progress : null} />
      ) : (
        stop.teaser && (
          <p className="px-3 py-2 text-xs leading-relaxed text-muted-foreground">{stop.teaser}</p>
        )
      )}
    </div>
  );
}

'use client';

import { useEffect, useRef, useState } from 'react';
import { ExternalLink, LoaderCircle, Rotate3d, X } from 'lucide-react';

import { cn } from '@/lib/utils';

/**
 * Ảnh đường phố Mapillary cho panel chi tiết — xem backend/app/streetview.py.
 *
 * Hai loại ảnh, backend chọn theo hai tiêu chí khác nhau:
 * - `facing`: ảnh thường mà máy quay NHÌN VỀ PHÍA địa điểm — thường là ảnh
 *   chụp thẳng mặt tiền từ camera gắn hông xe. Dùng làm ảnh tĩnh.
 * - `pano`: ảnh 360° gần nhất. Bấm "Xoay 360°" thì mở MapillaryJS, quay sẵn về
 *   phía địa điểm; kéo để xoay, bấm mũi tên để đi dọc con đường.
 *
 * Đây vẫn là ảnh ĐƯỜNG PHỐ do người khác chụp, có thể đã vài năm tuổi — nên
 * luôn ghi rõ ngày chụp và khoảng cách, cùng nguyên tắc với nhãn "Ảnh khu vực".
 */

export type StreetImage = {
  imageId: string;
  isPano: boolean;
  capturedAt: string | null;
  distanceMeters: number;
  /** hướng (độ, 0 = Bắc) từ chỗ chụp tới địa điểm */
  bearingToPoi: number;
  /** hướng máy quay đã hiệu chỉnh; với ảnh 360° là hướng của TÂM ảnh */
  compassAngle: number | null;
  creator: string | null;
  thumbUrl: string | null;
  sourceUrl: string;
};

export type StreetViews = {
  poiId: string;
  status: 'ready' | 'empty' | 'unavailable';
  /** client token của Mapillary — loại token sinh ra để nằm ở trình duyệt */
  accessToken?: string;
  license?: string;
  pano: StreetImage | null;
  facing: StreetImage | null;
};

/** Ảnh đường phố của một POI. `null` khi đang tải hoặc không hỏi được. */
export function useStreetViews(
  apiBaseUrl: string,
  poiId: string | null,
): { views: StreetViews | null; loading: boolean } {
  // Lưu kèm poiId để kết quả của POI cũ không bao giờ hiện ở POI mới trong lúc
  // request mới đang chạy.
  const [result, setResult] = useState<{
    poiId: string;
    views: StreetViews | null;
  } | null>(null);

  useEffect(() => {
    if (!poiId) return;
    const controller = new AbortController();
    fetch(`${apiBaseUrl}/api/v1/pois/${poiId}/streetview`, {
      signal: controller.signal,
    })
      .then((res) => (res.ok ? (res.json() as Promise<StreetViews>) : null))
      .then((views) => setResult({ poiId, views }))
      .catch((error: unknown) => {
        if ((error as { name?: string })?.name !== 'AbortError') {
          setResult({ poiId, views: null });
        }
      });
    return () => controller.abort();
  }, [apiBaseUrl, poiId]);

  if (!poiId) return { views: null, loading: false };
  if (result?.poiId !== poiId) return { views: null, loading: true };
  return { views: result.views, loading: false };
}

/** Toạ độ x (0..1) trên ảnh 360° equirectangular ứng với hướng tới địa điểm. */
export function panoCenterX(image: StreetImage): number {
  if (image.compassAngle == null) return 0.5;
  const x = (image.bearingToPoi - image.compassAngle) / 360 + 0.5;
  return ((x % 1) + 1) % 1;
}

function formatCaptured(iso: string | null): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return `tháng ${date.getMonth() + 1}/${date.getFullYear()}`;
}

export function StreetViewCaption({
  image,
  license,
  className,
}: {
  image: StreetImage;
  license?: string;
  className?: string;
}) {
  const captured = formatCaptured(image.capturedAt);
  return (
    <div className={cn('space-y-0.5 text-[11px] leading-snug', className)}>
      <p className="font-medium text-sky-700 dark:text-sky-400">
        {image.isPano ? 'Ảnh đường phố 360°' : 'Ảnh đường phố'}
        {captured ? ` · chụp ${captured}` : ''}
        {` · cách ${Math.round(image.distanceMeters)} m`}
      </p>
      {/* Ảnh Mapillary theo CC BY-SA — ghi công là điều kiện của giấy phép. */}
      <p className="text-muted-foreground">
        {license ?? 'CC BY-SA 4.0'}
        {image.creator ? ` · ${image.creator}` : ''}
        {' · '}
        <a
          href={image.sourceUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-0.5 underline underline-offset-2 hover:text-foreground"
        >
          Mapillary
          <ExternalLink className="size-3" aria-hidden />
        </a>
      </p>
    </div>
  );
}

/**
 * Khung ảnh đường phố: ảnh tĩnh (ưu tiên ảnh chụp thẳng mặt tiền) + nút mở
 * trình xem 360°. Chỉ render khi `views.status === 'ready'`.
 */
export function StreetView({
  views,
  poiName,
}: {
  views: StreetViews;
  poiName: string;
}) {
  const still = views.facing ?? views.pano;
  const interactive = views.pano ?? views.facing;
  const [viewerOpen, setViewerOpen] = useState(false);
  const [viewerState, setViewerState] = useState<'loading' | 'ready' | 'failed'>(
    'loading',
  );
  const containerRef = useRef<HTMLDivElement | null>(null);

  // Đổi POI thì đóng trình xem của POI cũ.
  useEffect(() => {
    // Reset có chủ đích khi đổi POI.
    // oxlint-disable-next-line react/react-compiler
    setViewerOpen(false);
  }, [views.poiId]);

  useEffect(() => {
    if (!viewerOpen || !interactive || !views.accessToken) return;
    const container = containerRef.current;
    if (!container) return;
    let cancelled = false;
    let viewer: { remove(): void } | null = null;
    // oxlint-disable-next-line react/react-compiler
    setViewerState('loading');

    // Nạp MapillaryJS (kèm three.js, vài trăm KB) chỉ khi người dùng bấm xem —
    // đa số lượt mở panel không bao giờ cần tới nó.
    import('mapillary-js')
      .then(async ({ Viewer, isSupported }) => {
        if (cancelled) return;
        if (!isSupported()) {
          setViewerState('failed');
          return;
        }
        const instance = new Viewer({
          accessToken: views.accessToken!,
          container,
          component: { cover: false },
        });
        viewer = instance;
        await instance.moveTo(interactive.imageId);
        if (cancelled) return;
        // Ảnh 360° mở ra quay đúng về phía địa điểm, không phải về hướng xe chạy.
        if (interactive.isPano) {
          instance.setCenter([panoCenterX(interactive), 0.5]);
        }
        setViewerState('ready');
      })
      .catch(() => {
        if (!cancelled) setViewerState('failed');
      });

    return () => {
      cancelled = true;
      viewer?.remove();
    };
  }, [viewerOpen, interactive, views.accessToken]);

  if (!still || !interactive) return null;
  const shown = viewerOpen ? interactive : still;

  return (
    <div>
      <div className="relative aspect-[16/10] w-full overflow-hidden bg-muted">
        {viewerOpen ? (
          <>
            <div ref={containerRef} className="size-full" />
            {viewerState === 'loading' && (
              <div className="pointer-events-none absolute inset-0 grid place-items-center bg-black/30 text-white">
                <LoaderCircle className="size-6 animate-spin" aria-label="Đang tải ảnh 360°" />
              </div>
            )}
            {viewerState === 'failed' && (
              <p className="absolute inset-x-0 bottom-0 bg-black/60 px-3 py-1.5 text-[11px] text-white">
                Trình duyệt không mở được trình xem 360° (cần WebGL).
              </p>
            )}
            <button
              type="button"
              onClick={() => setViewerOpen(false)}
              aria-label="Đóng trình xem 360°"
              className="absolute left-3 top-14 z-10 inline-flex items-center gap-1 rounded-full bg-black/65 px-2.5 py-1 text-[11px] font-semibold text-white shadow-sm hover:bg-black/80"
            >
              <X className="size-3.5" aria-hidden />
              Đóng 360°
            </button>
          </>
        ) : (
          <>
            {still.thumbUrl ? (
              <img
                src={still.thumbUrl}
                alt={`Ảnh đường phố trước ${poiName}`}
                className="size-full object-cover"
                style={
                  still.isPano
                    ? { objectPosition: `${panoCenterX(still) * 100}% 50%` }
                    : undefined
                }
                loading="lazy"
              />
            ) : (
              <div className="size-full" />
            )}
            <span className="absolute left-3 top-14 rounded-full bg-sky-600/95 px-2 py-0.5 text-[11px] font-semibold text-white shadow-sm">
              Ảnh đường phố
            </span>
            <button
              type="button"
              onClick={() => setViewerOpen(true)}
              aria-label={`Xem ${interactive.isPano ? '360°' : 'ảnh đường phố'} quanh ${poiName}`}
              className="absolute bottom-3 left-1/2 inline-flex -translate-x-1/2 items-center gap-1.5 rounded-full bg-white/95 px-3.5 py-1.5 text-sm font-semibold text-emerald-900 shadow-md ring-1 ring-black/5 transition hover:bg-white dark:bg-card/95 dark:text-emerald-200"
            >
              <Rotate3d className="size-4" aria-hidden />
              {interactive.isPano ? 'Xoay 360°' : 'Đi dọc con đường'}
            </button>
          </>
        )}
      </div>
      <StreetViewCaption
        image={shown}
        license={views.license}
        className="px-4 pt-2"
      />
    </div>
  );
}

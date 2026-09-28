'use client';

import { useEffect, useState } from 'react';
import { BadgeCheck, ChevronDown, ExternalLink, TriangleAlert } from 'lucide-react';

import { cn } from '@/lib/utils';

/**
 * Huy hiệu "Đã xác minh bằng ảnh" — AI đọc biển hiệu trong ảnh đường phố và so
 * với tên địa điểm (backend/app/storefront.py). Chỉ hiện hai kết luận có bằng
 * chứng: `verified` và `mismatch`. "Không đọc được biển" KHÔNG phải bằng chứng
 * quán đã đóng, nên các trạng thái còn lại không hiện gì.
 */

type Verification = {
  poiId: string;
  status: 'verified' | 'mismatch' | 'unreadable' | 'no_imagery' | 'unchecked';
  score?: number | null;
  matchedText?: string | null;
  checkedAt?: string;
  model?: string | null;
  imagesRead?: number;
  evidence?: {
    imageId: string;
    capturedAt: string | null;
    isPano: boolean;
    centerX: number | null;
    distanceMeters: number | null;
    texts: string[];
    thumbUrl: string | null;
    sourceUrl: string;
  } | null;
};

function monthYear(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? null : `${date.getMonth() + 1}/${date.getFullYear()}`;
}

export function VerificationBadge({ apiBaseUrl, poiId }: { apiBaseUrl: string; poiId: string }) {
  const [data, setData] = useState<Verification | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetch(`${apiBaseUrl}/api/v1/pois/${poiId}/verification`, { signal: controller.signal })
      .then((res) => (res.ok ? (res.json() as Promise<Verification>) : null))
      .then((value) => {
        setData(value);
        setOpen(false);
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, [apiBaseUrl, poiId]);

  if (!data || data.poiId !== poiId || (data.status !== 'verified' && data.status !== 'mismatch')) {
    return null;
  }
  const verified = data.status === 'verified';
  const when = monthYear(data.evidence?.capturedAt);
  const evidence = data.evidence;

  return (
    <div className="w-full">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className={cn(
          'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold',
          verified
            ? 'bg-emerald-600/10 text-emerald-700 dark:text-emerald-400'
            : 'bg-amber-500/15 text-amber-700 dark:text-amber-400',
        )}
      >
        {verified ? <BadgeCheck className="size-3.5" /> : <TriangleAlert className="size-3.5" />}
        {verified
          ? `Đã xác minh bằng ảnh${when ? ` tháng ${when}` : ''}`
          : 'Biển hiệu có thể đã đổi'}
        <ChevronDown className={cn('size-3 transition-transform', open && 'rotate-180')} />
      </button>

      {open && (
        <div className="mt-2 overflow-hidden rounded-lg border border-border text-xs">
          {evidence?.thumbUrl && (
            <img
              src={evidence.thumbUrl}
              alt="Ảnh đường phố dùng làm bằng chứng"
              className="aspect-[16/9] w-full object-cover"
              style={
                evidence.isPano && evidence.centerX != null
                  ? { objectPosition: `${evidence.centerX * 100}% 45%` }
                  : undefined
              }
              loading="lazy"
            />
          )}
          <div className="space-y-1 px-3 py-2">
            <p>
              {verified ? 'AI đọc được trên biển hiệu: ' : 'Ảnh mới hơn chỉ thấy biển: '}
              <b>“{data.matchedText}”</b>
              {verified
                ? ' — khớp với tên địa điểm.'
                : ' — không khớp tên, trong khi ảnh cũ hơn từng thấy đúng tên. Có thể đã đổi chủ hoặc đóng cửa.'}
            </p>
            <p className="text-muted-foreground">
              Ảnh Mapillary{when ? ` chụp tháng ${when}` : ''}
              {evidence?.distanceMeters != null ? ` · cách ${Math.round(evidence.distanceMeters)} m` : ''}
              {evidence && (
                <>
                  {' · '}
                  <a
                    href={evidence.sourceUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-0.5 underline underline-offset-2 hover:text-foreground"
                  >
                    Xem ảnh gốc <ExternalLink className="size-3" />
                  </a>
                </>
              )}
            </p>
            <p className="text-[11px] text-muted-foreground">
              Kiểm tự động bằng AI đọc chữ ({data.model ?? 'model thị giác'}, {data.imagesRead ?? 0} ảnh) — có
              thể sai, ảnh gốc ở trên để bạn tự đối chiếu.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

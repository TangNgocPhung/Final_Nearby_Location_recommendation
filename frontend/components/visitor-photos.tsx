'use client';

import { useEffect, useState } from 'react';
import { Camera } from 'lucide-react';

type VisitorPhoto = {
  id: string;
  url: string;
  thumbUrl: string;
  createdAt: string;
  source: string;
};

/**
 * Ảnh người chơi "Săn địa danh" chụp TẠI CHỖ (backend/app/explore.py) — chỉ ảnh
 * đã được AI xác minh đúng địa điểm và người chụp đồng ý công khai. Đây là
 * nguồn ảnh "của chính địa điểm" mà OSM/Wikimedia gần như không có.
 *
 * Không có ảnh nào thì không hiện gì: phần lớn POI chưa có, một khối trống
 * "chưa có ảnh người chơi" trên mọi trang chỉ là nhiễu.
 */
export function VisitorPhotos({ apiBaseUrl, poiId }: { apiBaseUrl: string; poiId: string }) {
  const [photos, setPhotos] = useState<VisitorPhoto[]>([]);
  const [open, setOpen] = useState<VisitorPhoto | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetch(`${apiBaseUrl}/api/v1/pois/${poiId}/visitor-photos`, { signal: controller.signal })
      .then((res): Promise<{ photos: VisitorPhoto[] }> | null => (res.ok ? res.json() : null))
      .then((data) => setPhotos(data?.photos ?? []))
      .catch(() => setPhotos([]));
    return () => controller.abort();
  }, [apiBaseUrl, poiId]);

  if (!photos.length) return null;

  return (
    <div className="px-4 pt-3">
      <p className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold text-muted-foreground">
        <Camera className="size-3.5" aria-hidden />
        Ảnh người chơi chụp tại chỗ · {photos.length}
      </p>
      <div className="flex gap-1.5 overflow-x-auto pb-1">
        {photos.map((photo) => (
          <button
            key={photo.id}
            type="button"
            onClick={() => setOpen(photo)}
            className="shrink-0 overflow-hidden rounded-lg"
            aria-label={`Xem ảnh người chơi chụp ngày ${new Date(photo.createdAt).toLocaleDateString('vi-VN')}`}
          >
            <img src={`${apiBaseUrl}${photo.thumbUrl}`} alt="" className="h-20 w-28 object-cover" loading="lazy" />
          </button>
        ))}
      </div>
      <p className="text-[11px] text-muted-foreground">
        Chụp qua “Săn địa danh” · đã được AI kiểm tra đúng địa điểm
      </p>
      {open && (
        <button
          type="button"
          onClick={() => setOpen(null)}
          className="fixed inset-0 z-[70] grid place-items-center bg-black/85 p-4"
          aria-label="Đóng ảnh"
        >
          <img src={`${apiBaseUrl}${open.url}`} alt="Ảnh người chơi chụp tại địa điểm" className="max-h-[85vh] max-w-full rounded-lg" />
          <span className="mt-2 text-xs text-white/80">
            {open.source} · {new Date(open.createdAt).toLocaleDateString('vi-VN')}
          </span>
        </button>
      )}
    </div>
  );
}

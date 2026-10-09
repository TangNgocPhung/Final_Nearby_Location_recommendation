'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import maplibregl, { type Map as MapLibreMap } from 'maplibre-gl';
import { Bike, Clock, Footprints, LoaderCircle, MapPin, Store, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { formatStreetAddress, type StreetAddress } from '@/lib/address';
import { cn, formatMeters } from '@/lib/utils';

type Mode = 'foot' | 'motorbike';

type ConvenienceStore = {
  id: string;
  name: string;
  address: string | null;
  streetAddress: StreetAddress | null;
  district: string | null;
  latitude: number;
  longitude: number;
  distanceMeters: number;
  brandCode: string;
  brand: string | null;
  hours: { raw: string | null; openNow: boolean | null; closesInMinutes: number | null; alwaysOpen: boolean };
  driveMinutes: number | null;
  driveMeters: number | null;
};

type ConvenienceResponse = {
  mode: Mode;
  approximate: boolean;
  candidates: number;
  radius: number;
  results: ConvenienceStore[];
};

const MODE_OPTIONS: { value: Mode; label: string; icon: typeof Bike }[] = [
  { value: 'foot', label: 'Đi bộ', icon: Footprints },
  { value: 'motorbike', label: 'Xe máy', icon: Bike },
];

// Khớp `convenience.BRAND_FILTERS` ở backend.
const BRAND_OPTIONS: { value: string; label: string }[] = [
  { value: 'any', label: 'Mọi cửa hàng' },
  { value: 'chain', label: 'Chuỗi tiện lợi' },
  { value: 'circle_k', label: 'Circle K' },
  { value: 'familymart', label: 'FamilyMart' },
  { value: 'gs25', label: 'GS25' },
  { value: 'seven_eleven', label: '7-Eleven' },
  { value: 'ministop', label: 'Ministop' },
  { value: 'winmart', label: 'WinMart+' },
  { value: 'bach_hoa_xanh', label: 'Bách Hóa Xanh' },
  { value: 'coop_food', label: 'Co.op Food' },
  { value: 'other', label: 'Tạp hóa, cửa hàng nhỏ' },
];

function storeAddress(store: ConvenienceStore): { text: string; approx: boolean } | null {
  if (store.address) return { text: store.address, approx: false };
  if (store.streetAddress) return { text: formatStreetAddress(store.streetAddress), approx: true };
  return null;
}

function hoursLabel(hours: ConvenienceStore['hours']): string {
  if (hours.alwaysOpen) return 'Mở 24/7';
  if (hours.openNow === true) return 'Đang mở';
  if (hours.openNow === false) return 'Đang đóng';
  return 'Chưa rõ giờ';
}

/**
 * Tìm cửa hàng tiện lợi — xem backend/app/convenience.py. Mặc định xếp theo
 * thời gian ĐI BỘ theo đường thật (cửa hàng thường ở ngay quanh người dùng);
 * chọn "Xe máy" thì xếp theo thời gian chạy xe.
 */
export function ConvenienceFinder({
  apiBaseUrl,
  mapRef,
  userPosition,
  onOpenDetail,
  onClose,
}: {
  apiBaseUrl: string;
  mapRef: React.RefObject<MapLibreMap | null>;
  userPosition: { latitude: number; longitude: number };
  onOpenDetail: (poiId: string) => void;
  onClose: () => void;
}) {
  const [mode, setMode] = useState<Mode>('foot');
  const [brand, setBrand] = useState('any');
  const [openNow, setOpenNow] = useState(false);
  const [response, setResponse] = useState<ConvenienceResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const markersRef = useRef<maplibregl.Marker[]>([]);

  const clearMarkers = useCallback(() => {
    for (const marker of markersRef.current) marker.remove();
    markersRef.current = [];
  }, []);

  useEffect(() => clearMarkers, [clearMarkers]);

  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({
      lat: String(userPosition.latitude),
      lng: String(userPosition.longitude),
      mode,
      brand,
      open_now: String(openNow),
    });
    // oxlint-disable-next-line react/react-compiler
    setLoading(true);
    setError(null);
    fetch(`${apiBaseUrl}/api/v1/convenience/search?${params}`, { signal: controller.signal })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json() as Promise<ConvenienceResponse>;
      })
      .then((data) => {
        setResponse(data);
        setLoading(false);
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setError('Chưa tìm được cửa hàng tiện lợi, bạn thử lại sau nhé.');
        setLoading(false);
      });
    return () => controller.abort();
  }, [apiBaseUrl, brand, mode, openNow, userPosition.latitude, userPosition.longitude]);

  // Marker đánh số riêng cho kết quả, dọn khi đóng khung.
  useEffect(() => {
    const map = mapRef.current;
    clearMarkers();
    if (!map || !response?.results.length) return;
    const bounds = new maplibregl.LngLatBounds();
    bounds.extend([userPosition.longitude, userPosition.latitude]);
    response.results.forEach((store, index) => {
      const element = document.createElement('button');
      element.type = 'button';
      element.className =
        'grid size-7 place-items-center rounded-full border-2 border-white bg-blue-600 text-[11px] font-bold text-white shadow-md';
      element.textContent = String(index + 1);
      element.title = store.name;
      element.addEventListener('click', () => onOpenDetail(store.id));
      markersRef.current.push(
        new maplibregl.Marker({ element }).setLngLat([store.longitude, store.latitude]).addTo(map),
      );
      if (index < 5) bounds.extend([store.longitude, store.latitude]);
    });
    map.fitBounds(bounds, { padding: 60, maxZoom: 16, duration: 600 });
  }, [clearMarkers, mapRef, onOpenDetail, response, userPosition.latitude, userPosition.longitude]);

  return (
    <Card className="shrink-0 rounded-2xl border-blue-900/10 shadow-[0_12px_40px_rgb(14_38_68/8%)] dark:border-white/10">
      <CardHeader className="flex flex-row items-start justify-between gap-2 space-y-0 pb-2">
        <div>
          <CardTitle className="flex items-center gap-2 text-base">
            <Store className="size-5 text-blue-600" aria-hidden /> Cửa hàng tiện lợi
          </CardTitle>
          <CardDescription className="text-xs">
            Xếp theo thời gian {mode === 'foot' ? 'đi bộ' : 'chạy xe'} tới cửa hàng
          </CardDescription>
        </div>
        <Button type="button" size="icon" variant="ghost" onClick={onClose} aria-label="Đóng tìm cửa hàng tiện lợi">
          <X className="size-4" />
        </Button>
      </CardHeader>
      <CardContent className="space-y-2.5">
        <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Cách di chuyển">
          {MODE_OPTIONS.map(({ value, label, icon: Icon }) => (
            <button
              key={value}
              type="button"
              // Chip dáng nút nhưng giữ ngữ nghĩa radio group — xem charging-finder.tsx.
              // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role
              role="radio"
              aria-checked={mode === value}
              onClick={() => setMode(value)}
              className={cn(
                'flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-medium transition',
                mode === value ? 'border-blue-600 bg-blue-600 text-white' : 'border-border hover:bg-muted',
              )}
            >
              <Icon className="size-3.5" /> {label}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <select
            value={brand}
            onChange={(event) => setBrand(event.target.value)}
            className="h-8 rounded-md border border-input bg-background px-2 text-xs"
            aria-label="Chuỗi cửa hàng"
          >
            {BRAND_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <label className="flex items-center gap-1.5">
            <input type="checkbox" checked={openNow} onChange={(event) => setOpenNow(event.target.checked)} />
            Đang mở cửa
          </label>
        </div>

        {loading && (
          <p className="flex items-center gap-2 py-2 text-xs text-muted-foreground">
            <LoaderCircle className="size-4 animate-spin" /> Đang tìm cửa hàng tiện lợi…
          </p>
        )}
        {error && <p className="text-xs text-destructive">{error}</p>}

        {response && !loading && (
          <>
            {response.results.length === 0 ? (
              <p className="rounded-lg bg-muted px-3 py-2 text-xs text-muted-foreground">
                Chưa có cửa hàng nào phù hợp trong {response.radius / 1000} km — bạn thử bỏ bớt bộ lọc.
              </p>
            ) : (
              <ol className="max-h-80 space-y-1.5 overflow-y-auto pr-1">
                {response.results.map((store, index) => {
                  const address = storeAddress(store);
                  return (
                    <li key={store.id}>
                      <button
                        type="button"
                        onClick={() => onOpenDetail(store.id)}
                        className="flex w-full items-start gap-2 rounded-lg border border-border px-2.5 py-2 text-left text-xs transition hover:bg-muted"
                      >
                        <span className="grid size-6 shrink-0 place-items-center rounded-full bg-blue-600 text-[11px] font-bold text-white">
                          {index + 1}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-medium">{store.name}</span>
                          <span className="block truncate text-muted-foreground">
                            {store.brand ?? 'Tạp hóa / cửa hàng nhỏ'}
                            {address ? ` · ${address.approx ? '~' : ''}${address.text}` : ''}
                          </span>
                          <span className="mt-0.5 flex items-center gap-0.5 text-muted-foreground">
                            <Clock className="size-3" />
                            {hoursLabel(store.hours)}
                          </span>
                        </span>
                        <span className="shrink-0 text-right">
                          {store.driveMinutes != null ? (
                            <span className="block text-sm font-semibold">{store.driveMinutes} phút</span>
                          ) : (
                            <span className="block text-[11px] text-muted-foreground">Không có đường</span>
                          )}
                          <span className="block text-[11px] text-muted-foreground">
                            {formatMeters(store.driveMeters ?? store.distanceMeters)}
                          </span>
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ol>
            )}
            <p className="flex items-start gap-1 text-[11px] text-muted-foreground">
              <MapPin className="mt-0.5 size-3 shrink-0" />
              {response.approximate
                ? 'Thời gian là ƯỚC TÍNH từ khoảng cách (máy chủ định tuyến đang tắt).'
                : `Thời gian ${response.mode === 'foot' ? 'đi bộ' : 'chạy xe máy'} theo đường thật (OSRM).`}{' '}
              Đa số cửa hàng chưa ghi giờ mở trên bản đồ mở. Địa chỉ có dấu “~” là tên đường ước lượng.
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}

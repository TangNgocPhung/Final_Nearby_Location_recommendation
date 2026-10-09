'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import maplibregl, { type Map as MapLibreMap } from 'maplibre-gl';
import { Accessibility, Baby, Bike, Clock, Footprints, LoaderCircle, MapPin, Toilet, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { formatStreetAddress, type StreetAddress } from '@/lib/address';
import { cn, formatMeters } from '@/lib/utils';

type Mode = 'foot' | 'motorbike';
type Source = 'all' | 'public';
type Kind = 'public' | 'fuel' | 'mall' | 'venue';

type ToiletPlace = {
  id: string;
  name: string;
  address: string | null;
  streetAddress: StreetAddress | null;
  district: string | null;
  latitude: number;
  longitude: number;
  distanceMeters: number;
  kind: Kind;
  kindLabel: string;
  customersOnly: boolean;
  fee: boolean | null;
  wheelchair: 'yes' | 'limited' | 'no' | null;
  changingTable: boolean;
  hours: { raw: string | null; openNow: boolean | null; closesInMinutes: number | null };
  driveMinutes: number | null;
  driveMeters: number | null;
};

type ToiletResponse = {
  mode: Mode;
  approximate: boolean;
  candidates: number;
  publicCount: number;
  radius: number;
  results: ToiletPlace[];
};

const MODE_OPTIONS: { value: Mode; label: string; icon: typeof Bike }[] = [
  { value: 'foot', label: 'Đi bộ', icon: Footprints },
  { value: 'motorbike', label: 'Xe máy', icon: Bike },
];

// WC công cộng nổi bật hơn hẳn các nguồn "có WC cho khách" — người dùng cần
// biết ngay chỗ nào chắc chắn vào được.
const KIND_MARKER: Record<Kind, string> = {
  public: 'bg-teal-600',
  fuel: 'bg-slate-500',
  mall: 'bg-slate-500',
  venue: 'bg-slate-500',
};

function placeAddress(place: ToiletPlace): { text: string; approx: boolean } | null {
  if (place.address) return { text: place.address, approx: false };
  if (place.streetAddress) return { text: formatStreetAddress(place.streetAddress), approx: true };
  return null;
}

/**
 * Tìm nhà vệ sinh — xem backend/app/toilets.py. WC công cộng trên bản đồ mở ở
 * TP.HCM rất thưa, nên kết quả gồm cả cây xăng, trung tâm thương mại và quán có
 * WC cho khách; mỗi dòng ghi rõ nguồn để người dùng không bị bất ngờ.
 */
export function ToiletFinder({
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
  const [source, setSource] = useState<Source>('all');
  const [freeOnly, setFreeOnly] = useState(false);
  const [wheelchair, setWheelchair] = useState(false);
  const [response, setResponse] = useState<ToiletResponse | null>(null);
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
      source,
      free_only: String(freeOnly),
      wheelchair: String(wheelchair),
    });
    // oxlint-disable-next-line react/react-compiler
    setLoading(true);
    setError(null);
    fetch(`${apiBaseUrl}/api/v1/toilets/search?${params}`, { signal: controller.signal })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json() as Promise<ToiletResponse>;
      })
      .then((data) => {
        setResponse(data);
        setLoading(false);
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setError('Chưa tìm được nhà vệ sinh, bạn thử lại sau nhé.');
        setLoading(false);
      });
    return () => controller.abort();
  }, [apiBaseUrl, freeOnly, mode, source, userPosition.latitude, userPosition.longitude, wheelchair]);

  // Marker đánh số riêng cho kết quả, dọn khi đóng khung.
  useEffect(() => {
    const map = mapRef.current;
    clearMarkers();
    if (!map || !response?.results.length) return;
    const bounds = new maplibregl.LngLatBounds();
    bounds.extend([userPosition.longitude, userPosition.latitude]);
    response.results.forEach((place, index) => {
      const element = document.createElement('button');
      element.type = 'button';
      element.className = cn(
        'grid size-7 place-items-center rounded-full border-2 border-white text-[11px] font-bold text-white shadow-md',
        KIND_MARKER[place.kind],
      );
      element.textContent = String(index + 1);
      element.title = `${place.name} · ${place.kindLabel}`;
      element.addEventListener('click', () => onOpenDetail(place.id));
      markersRef.current.push(
        new maplibregl.Marker({ element }).setLngLat([place.longitude, place.latitude]).addTo(map),
      );
      if (index < 5) bounds.extend([place.longitude, place.latitude]);
    });
    map.fitBounds(bounds, { padding: 60, maxZoom: 16, duration: 600 });
  }, [clearMarkers, mapRef, onOpenDetail, response, userPosition.latitude, userPosition.longitude]);

  return (
    <Card className="shrink-0 rounded-2xl border-teal-900/10 shadow-[0_12px_40px_rgb(14_68_64/8%)] dark:border-white/10">
      <CardHeader className="flex flex-row items-start justify-between gap-2 space-y-0 pb-2">
        <div>
          <CardTitle className="flex items-center gap-2 text-base">
            <Toilet className="size-5 text-teal-600" aria-hidden /> Nhà vệ sinh
          </CardTitle>
          <CardDescription className="text-xs">
            Xếp theo thời gian {mode === 'foot' ? 'đi bộ' : 'chạy xe'} tới nơi
          </CardDescription>
        </div>
        <Button type="button" size="icon" variant="ghost" onClick={onClose} aria-label="Đóng tìm nhà vệ sinh">
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
                mode === value ? 'border-teal-600 bg-teal-600 text-white' : 'border-border hover:bg-muted',
              )}
            >
              <Icon className="size-3.5" /> {label}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-xs">
          <select
            value={source}
            onChange={(event) => setSource(event.target.value as Source)}
            className="h-8 rounded-md border border-input bg-background px-2 text-xs"
            aria-label="Nguồn nhà vệ sinh"
          >
            <option value="all">WC công cộng + cây xăng, TTTM</option>
            <option value="public">Chỉ WC công cộng</option>
          </select>
          <label className="flex items-center gap-1.5">
            <input type="checkbox" checked={freeOnly} onChange={(event) => setFreeOnly(event.target.checked)} />
            Miễn phí
          </label>
          <label className="flex items-center gap-1.5">
            <input type="checkbox" checked={wheelchair} onChange={(event) => setWheelchair(event.target.checked)} />
            Xe lăn vào được
          </label>
        </div>

        {loading && (
          <p className="flex items-center gap-2 py-2 text-xs text-muted-foreground">
            <LoaderCircle className="size-4 animate-spin" /> Đang tìm nhà vệ sinh…
          </p>
        )}
        {error && <p className="text-xs text-destructive">{error}</p>}

        {response && !loading && (
          <>
            {response.results.length === 0 ? (
              <p className="rounded-lg bg-muted px-3 py-2 text-xs text-muted-foreground">
                Chưa có nhà vệ sinh nào phù hợp trong {response.radius / 1000} km
                {source === 'public' ? ' — WC công cộng trên bản đồ mở còn rất thưa, bạn thử thêm cây xăng, TTTM.' : '.'}
              </p>
            ) : (
              <ol className="max-h-80 space-y-1.5 overflow-y-auto pr-1">
                {response.results.map((place, index) => {
                  const address = placeAddress(place);
                  return (
                    <li key={place.id}>
                      <button
                        type="button"
                        onClick={() => onOpenDetail(place.id)}
                        className="flex w-full items-start gap-2 rounded-lg border border-border px-2.5 py-2 text-left text-xs transition hover:bg-muted"
                      >
                        <span
                          className={cn(
                            'grid size-6 shrink-0 place-items-center rounded-full text-[11px] font-bold text-white',
                            KIND_MARKER[place.kind],
                          )}
                        >
                          {index + 1}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-medium">{place.name}</span>
                          <span className="block truncate text-muted-foreground">
                            <span className={cn(place.kind === 'public' && 'font-medium text-teal-700 dark:text-teal-300')}>
                              {place.kindLabel}
                            </span>
                            {address ? ` · ${address.approx ? '~' : ''}${address.text}` : ''}
                          </span>
                          <span className="mt-0.5 flex flex-wrap items-center gap-x-2 text-muted-foreground">
                            {place.fee === false && <span>Miễn phí</span>}
                            {place.fee === true && <span>Có thu phí</span>}
                            {place.customersOnly && <span>Dành cho khách</span>}
                            {(place.wheelchair === 'yes' || place.wheelchair === 'limited') && (
                              <span className="flex items-center gap-0.5">
                                <Accessibility className="size-3" />
                                {place.wheelchair === 'yes' ? 'Xe lăn' : 'Xe lăn (hạn chế)'}
                              </span>
                            )}
                            {place.changingTable && (
                              <span className="flex items-center gap-0.5">
                                <Baby className="size-3" /> Bàn thay tã
                              </span>
                            )}
                            {place.hours.openNow != null && (
                              <span className="flex items-center gap-0.5">
                                <Clock className="size-3" />
                                {place.hours.openNow ? 'Đang mở' : 'Đang đóng'}
                              </span>
                            )}
                          </span>
                        </span>
                        <span className="shrink-0 text-right">
                          {place.driveMinutes != null ? (
                            <span className="block text-sm font-semibold">{place.driveMinutes} phút</span>
                          ) : (
                            <span className="block text-[11px] text-muted-foreground">Không có đường</span>
                          )}
                          <span className="block text-[11px] text-muted-foreground">
                            {formatMeters(place.driveMeters ?? place.distanceMeters)}
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
              WC công cộng trên bản đồ mở còn thưa ({response.publicCount} điểm trong {response.radius / 1000} km) —
              cây xăng, TTTM thường có WC cho khách nhưng chưa xác minh từng nơi.
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}

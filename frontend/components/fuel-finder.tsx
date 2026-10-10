'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import maplibregl, { type Map as MapLibreMap } from 'maplibre-gl';
import { Bike, Car, Clock, Fuel, LoaderCircle, MapPin, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { formatStreetAddress, type StreetAddress } from '@/lib/address';
import { cn, formatMeters } from '@/lib/utils';

type Vehicle = 'motorbike' | 'car';
type Brand = 'any' | 'petrolimex' | 'pvoil' | 'saigon_petro' | 'comeco' | 'other';

type Station = {
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
  fuels: string[];
  compressedAir: boolean;
  hours: { raw: string | null; openNow: boolean | null; closesInMinutes: number | null };
  driveMinutes: number | null;
  driveMeters: number | null;
};

type FuelResponse = {
  vehicle: Vehicle;
  approximate: boolean;
  candidates: number;
  radius: number;
  results: Station[];
};

const VEHICLE_OPTIONS: { value: Vehicle; label: string; icon: typeof Bike }[] = [
  { value: 'motorbike', label: 'Xe máy', icon: Bike },
  { value: 'car', label: 'Ô tô', icon: Car },
];

const BRAND_OPTIONS: { value: Brand; label: string }[] = [
  { value: 'any', label: 'Mọi hãng' },
  { value: 'petrolimex', label: 'Petrolimex' },
  { value: 'pvoil', label: 'PVOIL' },
  { value: 'saigon_petro', label: 'Saigon Petro' },
  { value: 'comeco', label: 'Comeco' },
  { value: 'other', label: 'Hãng khác' },
];

function stationAddress(station: Station): { text: string; approx: boolean } | null {
  if (station.address) return { text: station.address, approx: false };
  if (station.streetAddress) return { text: formatStreetAddress(station.streetAddress), approx: true };
  return null;
}

/**
 * Tìm trạm xăng — xem backend/app/fuel.py. Giống "Trạm sạc xe điện": người tìm
 * cây xăng CHẠY XE tới đó, nên danh sách xếp theo thời gian chạy xe theo đường
 * thật (OSRM), không theo đường chim bay như bộ lọc danh mục "Cây xăng".
 */
export function FuelFinder({
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
  const [vehicle, setVehicle] = useState<Vehicle>('motorbike');
  const [brand, setBrand] = useState<Brand>('any');
  const [openNow, setOpenNow] = useState(false);
  const [response, setResponse] = useState<FuelResponse | null>(null);
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
      vehicle,
      brand,
      open_now: String(openNow),
    });
    // oxlint-disable-next-line react/react-compiler
    setLoading(true);
    setError(null);
    fetch(`${apiBaseUrl}/api/v1/fuel/search?${params}`, { signal: controller.signal })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json() as Promise<FuelResponse>;
      })
      .then((data) => {
        setResponse(data);
        setLoading(false);
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setError('Chưa tìm được trạm xăng, bạn thử lại sau nhé.');
        setLoading(false);
      });
    return () => controller.abort();
  }, [apiBaseUrl, brand, openNow, userPosition.latitude, userPosition.longitude, vehicle]);

  // Marker đánh số riêng cho kết quả, dọn khi đóng khung.
  useEffect(() => {
    const map = mapRef.current;
    clearMarkers();
    if (!map || !response?.results.length) return;
    const bounds = new maplibregl.LngLatBounds();
    bounds.extend([userPosition.longitude, userPosition.latitude]);
    response.results.forEach((station, index) => {
      const element = document.createElement('button');
      element.type = 'button';
      element.className =
        'grid size-7 place-items-center rounded-full border-2 border-white bg-amber-600 text-[11px] font-bold text-white shadow-md';
      element.textContent = index < 9 ? String(index + 1) : '⛽';
      element.title = station.name;
      element.addEventListener('click', () => onOpenDetail(station.id));
      markersRef.current.push(
        new maplibregl.Marker({ element }).setLngLat([station.longitude, station.latitude]).addTo(map),
      );
      if (index < 5) bounds.extend([station.longitude, station.latitude]);
    });
    map.fitBounds(bounds, { padding: 60, maxZoom: 15, duration: 600 });
  }, [clearMarkers, mapRef, onOpenDetail, response, userPosition.latitude, userPosition.longitude]);

  return (
    <Card className="shrink-0 rounded-2xl border-amber-900/10 shadow-[0_12px_40px_rgb(68_48_14/8%)] dark:border-white/10">
      <CardHeader className="flex flex-row items-start justify-between gap-2 space-y-0 pb-2">
        <div>
          <CardTitle className="flex items-center gap-2 text-base">
            <Fuel className="size-5 text-amber-600" aria-hidden /> Trạm xăng
          </CardTitle>
          <CardDescription className="text-xs">Xếp theo thời gian chạy xe tới trạm</CardDescription>
        </div>
        <Button type="button" size="icon" variant="ghost" onClick={onClose} aria-label="Đóng tìm trạm xăng">
          <X className="size-4" />
        </Button>
      </CardHeader>
      <CardContent className="space-y-2.5">
        <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Loại xe">
          {VEHICLE_OPTIONS.map(({ value, label, icon: Icon }) => (
            <button
              key={value}
              type="button"
              // Chip dáng nút nhưng giữ ngữ nghĩa radio group — xem charging-finder.tsx.
              // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role
              role="radio"
              aria-checked={vehicle === value}
              onClick={() => setVehicle(value)}
              className={cn(
                'flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-medium transition',
                vehicle === value ? 'border-amber-600 bg-amber-600 text-white' : 'border-border hover:bg-muted',
              )}
            >
              <Icon className="size-3.5" /> {label}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <select
            value={brand}
            onChange={(event) => setBrand(event.target.value as Brand)}
            className="h-8 max-w-full rounded-md border border-input bg-background px-2 text-xs"
            aria-label="Hãng xăng dầu"
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
            <LoaderCircle className="size-4 animate-spin" /> Đang tìm trạm xăng…
          </p>
        )}
        {error && <p className="text-xs text-destructive">{error}</p>}

        {response && !loading && (
          <>
            {response.results.length === 0 ? (
              <p className="rounded-lg bg-muted px-3 py-2 text-xs text-muted-foreground">
                Chưa có trạm xăng nào phù hợp trong {response.radius / 1000} km — bạn thử bỏ bớt bộ lọc.
              </p>
            ) : (
              <ol className="max-h-80 space-y-1.5 overflow-y-auto pr-1">
                {response.results.map((station, index) => {
                  const address = stationAddress(station);
                  return (
                    <li key={station.id}>
                      <button
                        type="button"
                        onClick={() => onOpenDetail(station.id)}
                        className="flex w-full items-start gap-2 rounded-lg border border-border px-2.5 py-2 text-left text-xs transition hover:bg-muted"
                      >
                        <span className="grid size-6 shrink-0 place-items-center rounded-full bg-amber-600 text-[11px] font-bold text-white">
                          {index + 1}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-medium">{station.name}</span>
                          <span className="block truncate text-muted-foreground">
                            {station.brand ?? 'Chưa rõ hãng'}
                            {address ? ` · ${address.approx ? '~' : ''}${address.text}` : ''}
                          </span>
                          <span className="mt-0.5 flex flex-wrap gap-x-2 text-muted-foreground">
                            {station.fuels.length > 0 && <span>{station.fuels.join(', ')}</span>}
                            {station.compressedAir && <span>Có bơm hơi</span>}
                            <span className="flex items-center gap-0.5">
                              <Clock className="size-3" />
                              {station.hours.openNow === true
                                ? 'Đang mở'
                                : station.hours.openNow === false
                                  ? 'Đang đóng'
                                  : 'Chưa rõ giờ'}
                            </span>
                          </span>
                        </span>
                        <span className="shrink-0 text-right">
                          {station.driveMinutes != null ? (
                            <span className="block text-sm font-semibold">{station.driveMinutes} phút</span>
                          ) : (
                            <span className="block text-[11px] text-muted-foreground">Không có đường</span>
                          )}
                          <span className="block text-[11px] text-muted-foreground">
                            {formatMeters(station.driveMeters ?? station.distanceMeters)}
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
                : `Thời gian chạy ${response.vehicle === 'car' ? 'ô tô' : 'xe máy'} theo đường thật (OSRM), chưa tính kẹt xe.`}{' '}
              Địa chỉ có dấu “~” là tên đường ước lượng theo bản đồ — dữ liệu mở chưa có số nhà.
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}

'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import maplibregl, { type Map as MapLibreMap } from 'maplibre-gl';
import {
  Bike,
  Car,
  CircleParking,
  Clock,
  Footprints,
  LoaderCircle,
  MapPin,
  PlugZap,
  X,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  DURATION_OPTIONS,
  TIER_STYLES,
  VEHICLE_LABELS,
  formatHours,
  formatEstimatedCost,
  formatPrice,
  type ParkingResult,
  type ParkingSearchResponse,
  type Vehicle,
} from '@/lib/parking';
import { cn, formatMeters } from '@/lib/utils';

type Place = { name: string; latitude: number; longitude: number };

/** Yêu cầu tìm chỗ gửi xe từ nơi khác trong trang (nút "Tìm chỗ gửi xe gần
 * đây" ở panel chi tiết) — `nonce` đổi là tìm lại, kể cả cùng điểm đến. */
export type ParkingRequest = Place & { nonce: number };

const VEHICLE_ICONS: Record<Vehicle, typeof Bike> = {
  motorbike: Bike,
  car: Car,
  bicycle: Bike,
  ev: PlugZap,
};
const VEHICLE_ORDER: Vehicle[] = ['motorbike', 'car', 'ev'];
// Trạm sạc thưa hơn bãi xe rất nhiều (25 trạm cho cả TP.HCM trên OSM, đo
// 2026-09-25) — bán kính 1 km gần như luôn ra 0 kết quả.
const SEARCH_RADIUS: Record<Vehicle, number> = { motorbike: 1000, car: 1000, bicycle: 1000, ev: 5000 };
const MARKER_COLORS: Record<ParkingResult['price']['tier'], string> = {
  community: '#059669',
  openstreetmap: '#0284c7',
  published: '#0284c7',
  regulated: '#7c3aed',
  reference: '#d97706',
  unknown: '#64748b',
};

/**
 * Tìm chỗ gửi xe theo LOẠI XE + THỜI GIAN GỬI + ĐIỂM ĐẾN — xem
 * backend/app/parking.py. Kết quả tự vẽ marker riêng (màu theo mức tin cậy
 * của giá) thay vì trộn vào danh sách "Địa điểm gần bạn", vì bãi xe gần như
 * không có đánh giá sao và sẽ bị bộ lọc "Đánh giá tối thiểu" ẩn hết.
 */
export function ParkingFinder({
  apiBaseUrl,
  mapRef,
  userPosition,
  selectedPlace,
  request,
  onOpenDetail,
  onClose,
}: {
  apiBaseUrl: string;
  mapRef: React.RefObject<MapLibreMap | null>;
  userPosition: { latitude: number; longitude: number };
  /** địa điểm đang mở trong panel chi tiết — gợi ý làm điểm đến */
  selectedPlace: Place | null;
  request: ParkingRequest | null;
  onOpenDetail: (poiId: string) => void;
  /** đóng khung — trang cha gỡ component, marker kết quả tự dọn theo */
  onClose?: () => void;
}) {
  const [vehicle, setVehicle] = useState<Vehicle>('motorbike');
  const [minutes, setMinutes] = useState(120);
  const [destination, setDestination] = useState<Place | null>(null);
  const [response, setResponse] = useState<ParkingSearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const markersRef = useRef<maplibregl.Marker[]>([]);
  // Lần tìm đang hiển thị — để tìm lại khi vị trí người dùng đổi. Kết quả tính
  // khoảng cách từ vị trí LÚC BẤM TÌM; GPS về sau (hoặc nhảy vài km khi Windows
  // định vị bằng Wi-Fi) mà không tìm lại thì danh sách ghi "0,8 km" trong khi
  // panel chi tiết — đo từ vị trí mới — ghi "5,0 km" cho cùng một trạm.
  const lastQueryRef = useRef<{ target: Place | null; vehicle: Vehicle; minutes: number } | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const clearMarkers = useCallback(() => {
    for (const marker of markersRef.current) marker.remove();
    markersRef.current = [];
  }, []);

  const search = useCallback(
    async (target: Place | null, forVehicle: Vehicle, forMinutes: number) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      lastQueryRef.current = { target, vehicle: forVehicle, minutes: forMinutes };
      setLoading(true);
      setError(null);
      const params = new URLSearchParams({
        lat: String(userPosition.latitude),
        lng: String(userPosition.longitude),
        vehicle: forVehicle,
        minutes: String(forMinutes),
        radius: String(SEARCH_RADIUS[forVehicle]),
      });
      if (target) {
        params.set('dest_lat', String(target.latitude));
        params.set('dest_lng', String(target.longitude));
      }
      try {
        const res = await fetch(`${apiBaseUrl}/api/v1/parking/search?${params}`, {
          signal: controller.signal,
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as ParkingSearchResponse;
        if (controller.signal.aborted) return;
        setResponse(data);
      } catch (caught) {
        if ((caught as Error)?.name === 'AbortError') return;
        setResponse(null);
        setError('Không tìm được chỗ gửi xe, bạn thử lại sau nhé.');
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    },
    [apiBaseUrl, userPosition.latitude, userPosition.longitude],
  );

  // `search` chỉ đổi danh tính khi vị trí người dùng đổi → tìm lại lần đang
  // hiển thị (nếu có) cho khoảng cách khớp với panel chi tiết.
  useEffect(() => {
    const last = lastQueryRef.current;
    if (!last) return;
    void search(last.target, last.vehicle, last.minutes);
  }, [search]);

  useEffect(() => () => abortRef.current?.abort(), []);

  // Yêu cầu từ panel chi tiết: đặt điểm đến rồi tìm ngay.
  useEffect(() => {
    if (!request) return;
    const target = { name: request.name, latitude: request.latitude, longitude: request.longitude };
    // oxlint-disable-next-line react/react-compiler
    setDestination(target);
    void search(target, vehicle, minutes);
    // Chỉ chạy khi có yêu cầu mới (nonce), không chạy lại khi đổi loại xe.
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [request?.nonce]);

  // Vẽ marker cho kết quả; gỡ hết khi đóng kết quả hoặc rời trang.
  useEffect(() => {
    clearMarkers();
    const map = mapRef.current;
    if (!map || !response) return;
    for (const result of response.results) {
      const dot = document.createElement('button');
      dot.type = 'button';
      dot.className =
        'grid size-7 place-items-center rounded-full border-2 border-white text-[11px] font-bold text-white shadow-md';
      dot.style.background = MARKER_COLORS[result.price.tier];
      dot.textContent = result.kind === 'charging_station' ? '⚡' : 'P';
      dot.setAttribute('aria-label', result.name);
      dot.addEventListener('click', () => onOpenDetail(result.id));
      markersRef.current.push(
        new maplibregl.Marker({ element: dot }).setLngLat([result.longitude, result.latitude]).addTo(map),
      );
    }
    return clearMarkers;
  }, [response, mapRef, clearMarkers, onOpenDetail]);

  const pickResult = (result: ParkingResult) => {
    mapRef.current?.flyTo({ center: [result.longitude, result.latitude], zoom: 17, essential: true });
    onOpenDetail(result.id);
  };

  const target = destination ?? null;

  return (
    <Card className="shrink-0 border-0 shadow-[0_12px_40px_rgb(14_68_48/8%)] ring-emerald-950/10">
      <CardHeader className="px-5 pt-4 pb-2">
        <CardTitle className="flex items-center gap-2 text-base font-bold">
          <CircleParking className="size-5 text-primary" />
          Tìm chỗ gửi xe
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              aria-label="Đóng tìm chỗ gửi xe"
              className="ml-auto grid size-7 place-items-center rounded-full text-muted-foreground transition hover:bg-muted hover:text-foreground"
            >
              <X className="size-4" aria-hidden />
            </button>
          )}
        </CardTitle>
        <CardDescription>Theo loại xe, thời gian gửi và nơi bạn muốn tới.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 px-5 pb-4">
        <div className="flex flex-wrap gap-1.5">
          {VEHICLE_ORDER.map((item) => {
            const Icon = VEHICLE_ICONS[item];
            return (
              <button
                key={item}
                type="button"
                aria-pressed={vehicle === item}
                onClick={() => setVehicle(item)}
                className={cn(
                  'flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm font-medium transition-colors',
                  vehicle === item
                    ? 'border-primary bg-primary text-primary-foreground'
                    : 'border-border bg-background hover:bg-muted',
                )}
              >
                <Icon className="size-4" />
                {VEHICLE_LABELS[item]}
              </button>
            );
          })}
        </div>

        <div className="flex flex-wrap items-center gap-2 text-sm">
          <label className="flex items-center gap-1.5">
            <Clock className="size-4 text-muted-foreground" />
            <span className="text-muted-foreground">Gửi</span>
            <select
              value={minutes}
              onChange={(event) => setMinutes(Number(event.target.value))}
              className="h-8 max-w-full rounded-md border border-input bg-background px-2 text-sm"
            >
              {DURATION_OPTIONS.map((option) => (
                <option key={option.minutes} value={option.minutes}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="flex flex-wrap items-center gap-1.5 text-sm">
          <MapPin className="size-4 text-muted-foreground" />
          <span className="text-muted-foreground">Gần:</span>
          {target ? (
            <span className="flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 font-medium">
              {target.name}
              <button
                type="button"
                aria-label="Bỏ điểm đến"
                onClick={() => setDestination(null)}
                className="text-muted-foreground hover:text-foreground"
              >
                <X className="size-3.5" />
              </button>
            </span>
          ) : (
            <span className="font-medium">Vị trí của tôi</span>
          )}
          {selectedPlace && selectedPlace.name !== target?.name && (
            <button
              type="button"
              onClick={() => setDestination(selectedPlace)}
              className="rounded-full border border-dashed border-border px-2 py-0.5 text-xs hover:bg-muted"
            >
              + {selectedPlace.name}
            </button>
          )}
        </div>

        <Button className="w-full" onClick={() => void search(target, vehicle, minutes)} disabled={loading}>
          {loading ? <LoaderCircle className="size-4 animate-spin" /> : <CircleParking className="size-4" />}
          Tìm chỗ gửi {VEHICLE_LABELS[vehicle].toLowerCase()}
        </Button>

        {error && <p className="text-sm text-destructive">{error}</p>}

        {response && (
          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>
                {response.results.length} chỗ phù hợp
                {response.excludedClosed > 0 && ` · đã ẩn ${response.excludedClosed} chỗ đóng cửa lúc bạn gửi`}
              </span>
              <button
                type="button"
                onClick={() => {
                  lastQueryRef.current = null;
                  setResponse(null);
                }}
                className="hover:text-foreground"
              >
                Đóng
              </button>
            </div>
            <ol className="max-h-80 space-y-2 overflow-y-auto pr-1">
              {response.results.map((result, index) => (
                <li key={result.id}>
                  <button
                    type="button"
                    onClick={() => pickResult(result)}
                    className="w-full rounded-xl border border-border bg-background p-3 text-left transition-colors hover:border-primary/50 hover:bg-muted/40"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <p className="font-semibold leading-tight">
                        <span className="mr-1 text-muted-foreground">{index + 1}.</span>
                        {result.name}
                      </p>
                      <span className="flex shrink-0 items-center gap-1 text-xs text-muted-foreground">
                        {result.kind === 'charging_station' ? (
                          // Tới trạm sạc là lái xe tới, không đi bộ.
                          <>
                            <MapPin className="size-3.5" />
                            {formatMeters(result.walkMeters)}
                          </>
                        ) : (
                          <>
                            <Footprints className="size-3.5" />
                            {result.walkMinutes} phút · {result.walkMeters} m
                          </>
                        )}
                      </span>
                    </div>
                    <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs">
                      <span
                        className={cn(
                          'rounded-full px-2 py-0.5 font-medium',
                          TIER_STYLES[result.price.tier].className,
                        )}
                        title={TIER_STYLES[result.price.tier].label}
                      >
                        {formatPrice(result.price)}
                      </span>
                      {formatEstimatedCost(result.price) && (
                        <span className="text-muted-foreground">
                          ≈ {formatEstimatedCost(result.price)} cho lần gửi này
                        </span>
                      )}
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {TIER_STYLES[result.price.tier].label}
                      {result.price.reports ? ` · ${result.price.reports} lượt báo` : ''}
                      {' · '}
                      {formatHours(result.hours)}
                      {result.hours.raw && result.hours.raw !== '24/7' ? ` (${result.hours.raw})` : ''}
                      {result.vehicleSupport === 'unknown' && ` · chưa chắc nhận ${VEHICLE_LABELS[vehicle].toLowerCase()}`}
                      {result.capacity ? ` · ${result.capacity} chỗ` : ''}
                    </p>
                    {result.sockets.length > 0 && (
                      <p className="mt-1 text-xs text-muted-foreground">
                        ⚡{' '}
                        {result.sockets
                          .map((s) => `${s.type}${s.count ? ` ×${s.count}` : ''}${s.powerKw ? ` ${s.powerKw} kW` : ''}`)
                          .join(', ')}
                      </p>
                    )}
                  </button>
                </li>
              ))}
            </ol>
            {response.results.length === 0 && (
              <p className="text-sm text-muted-foreground">
                Chưa có dữ liệu {vehicle === 'ev' ? 'trạm sạc' : 'chỗ gửi xe'} trong bán kính{' '}
                {SEARCH_RADIUS[vehicle] / 1000} km quanh điểm này.
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

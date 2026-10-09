'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import maplibregl, { type Map as MapLibreMap } from 'maplibre-gl';
import { Bike, Car, Clock, LoaderCircle, MapPin, PlugZap, Zap, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { formatPrice, type ParkingResult } from '@/lib/parking';
import { cn, formatMeters } from '@/lib/utils';

type EvVehicle = 'any' | 'motorbike' | 'car';
type Network = 'any' | 'vinfast' | 'other';

type Station = ParkingResult & {
  driveMinutes: number | null;
  driveMeters: number | null;
  network: string | null;
};

type ChargingResponse = {
  vehicle: EvVehicle;
  mode: 'motorbike' | 'car';
  approximate: boolean;
  candidates: number;
  results: Station[];
};

const VEHICLE_OPTIONS: { value: EvVehicle; label: string; icon: typeof Bike }[] = [
  { value: 'motorbike', label: 'Xe máy điện', icon: Bike },
  { value: 'car', label: 'Ô tô điện', icon: Car },
  { value: 'any', label: 'Mọi loại', icon: PlugZap },
];

const NETWORK_OPTIONS: { value: Network; label: string }[] = [
  { value: 'any', label: 'Mọi mạng sạc' },
  { value: 'vinfast', label: 'VinFast / V-Green' },
  { value: 'other', label: 'Mạng khác' },
];

const SUPPORT_LABEL: Record<string, string> = { yes: 'có', no: 'không', unknown: 'chưa rõ' };

/**
 * Tìm trạm sạc xe điện — xem backend/app/charging.py. Khác "Tìm chỗ gửi xe":
 * người tìm trạm sạc CHẠY XE tới trạm, nên danh sách xếp theo thời gian chạy xe
 * theo đường thật (OSRM), không theo quãng đi bộ.
 */
export function ChargingFinder({
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
  const [vehicle, setVehicle] = useState<EvVehicle>('motorbike');
  const [network, setNetwork] = useState<Network>('any');
  const [openNow, setOpenNow] = useState(false);
  const [response, setResponse] = useState<ChargingResponse | null>(null);
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
      network,
      open_now: String(openNow),
    });
    // oxlint-disable-next-line react/react-compiler
    setLoading(true);
    setError(null);
    fetch(`${apiBaseUrl}/api/v1/charging/search?${params}`, { signal: controller.signal })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json() as Promise<ChargingResponse>;
      })
      .then((data) => {
        setResponse(data);
        setLoading(false);
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setError('Chưa tìm được trạm sạc, bạn thử lại sau nhé.');
        setLoading(false);
      });
    return () => controller.abort();
  }, [apiBaseUrl, network, openNow, userPosition.latitude, userPosition.longitude, vehicle]);

  // Marker ⚡ riêng cho kết quả, dọn khi đóng khung.
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
        'grid size-7 place-items-center rounded-full border-2 border-white bg-sky-600 text-[11px] font-bold text-white shadow-md';
      element.textContent = index < 9 ? String(index + 1) : '⚡';
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
    <Card className="shrink-0 rounded-2xl border-sky-900/10 shadow-[0_12px_40px_rgb(14_48_68/8%)] dark:border-white/10">
      <CardHeader className="flex flex-row items-start justify-between gap-2 space-y-0 pb-2">
        <div>
          <CardTitle className="flex items-center gap-2 text-base">
            <Zap className="size-5 text-sky-600" aria-hidden /> Trạm sạc xe điện
          </CardTitle>
          <CardDescription className="text-xs">Xếp theo thời gian chạy xe tới trạm</CardDescription>
        </div>
        <Button type="button" size="icon" variant="ghost" onClick={onClose} aria-label="Đóng tìm trạm sạc">
          <X className="size-4" />
        </Button>
      </CardHeader>
      <CardContent className="space-y-2.5">
        <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Loại xe">
          {VEHICLE_OPTIONS.map(({ value, label, icon: Icon }) => (
            <button
              key={value}
              type="button"
              // Chip dáng nút nhưng giữ ngữ nghĩa radio group (role="radiogroup" ở trên
              // + aria-checked); <input type="radio"> sẽ phá layout chip.
              // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role
              role="radio"
              aria-checked={vehicle === value}
              onClick={() => setVehicle(value)}
              className={cn(
                'flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-medium transition',
                vehicle === value ? 'border-sky-600 bg-sky-600 text-white' : 'border-border hover:bg-muted',
              )}
            >
              <Icon className="size-3.5" /> {label}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <select
            value={network}
            onChange={(event) => setNetwork(event.target.value as Network)}
            className="h-8 rounded-md border border-input bg-background px-2 text-xs"
            aria-label="Mạng sạc"
          >
            {NETWORK_OPTIONS.map((option) => (
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
            <LoaderCircle className="size-4 animate-spin" /> Đang tìm trạm sạc…
          </p>
        )}
        {error && <p className="text-xs text-destructive">{error}</p>}

        {response && !loading && (
          <>
            {response.results.length === 0 ? (
              <p className="rounded-lg bg-muted px-3 py-2 text-xs text-muted-foreground">
                Chưa có trạm sạc nào phù hợp trong 10 km. Dữ liệu trạm sạc mở ở TP.HCM còn thưa — bạn thử bỏ
                bớt bộ lọc.
              </p>
            ) : (
              <ol className="max-h-80 space-y-1.5 overflow-y-auto pr-1">
                {response.results.map((station, index) => (
                  <li key={station.id}>
                    <button
                      type="button"
                      onClick={() => onOpenDetail(station.id)}
                      className="flex w-full items-start gap-2 rounded-lg border border-border px-2.5 py-2 text-left text-xs transition hover:bg-muted"
                    >
                      <span className="grid size-6 shrink-0 place-items-center rounded-full bg-sky-600 text-[11px] font-bold text-white">
                        {index + 1}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium">{station.name}</span>
                        <span className="block truncate text-muted-foreground">
                          {station.network ?? 'Chưa rõ mạng sạc'}
                          {station.address ? ` · ${station.address}` : ''}
                        </span>
                        <span className="mt-0.5 flex flex-wrap gap-x-2 text-muted-foreground">
                          <span>
                            Xe máy: {SUPPORT_LABEL[station.vehicles.motorbike] ?? 'chưa rõ'} · Ô tô:{' '}
                            {SUPPORT_LABEL[station.vehicles.car] ?? 'chưa rõ'}
                          </span>
                          {station.sockets && station.sockets.length > 0 && (
                            <span>
                              Cổng:{' '}
                              {station.sockets
                                .map((socket) => `${socket.type}${socket.powerKw ? ` ${socket.powerKw} kW` : ''}`)
                                .join(', ')}
                            </span>
                          )}
                          <span className="flex items-center gap-0.5">
                            <Clock className="size-3" />
                            {station.hours.openNow === true
                              ? 'Đang mở'
                              : station.hours.openNow === false
                                ? 'Đang đóng'
                                : 'Chưa rõ giờ'}
                          </span>
                          {station.price.tier !== 'unknown' && <span>{formatPrice(station.price)}</span>}
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
                ))}
              </ol>
            )}
            <p className="flex items-start gap-1 text-[11px] text-muted-foreground">
              <MapPin className="mt-0.5 size-3 shrink-0" />
              {response.approximate
                ? 'Thời gian là ƯỚC TÍNH từ khoảng cách (máy chủ định tuyến đang tắt).'
                : `Thời gian chạy ${response.mode === 'car' ? 'ô tô' : 'xe máy'} theo đường thật (OSRM), chưa tính kẹt xe.`}{' '}
              Loại xe/cổng sạc “chưa rõ” nghĩa là dữ liệu mở chưa ghi, không phải trạm không hỗ trợ.
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}

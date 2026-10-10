'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import maplibregl, { type GeoJSONSource, type Map as MapLibreMap, type MapLayerMouseEvent } from 'maplibre-gl';
import {
  ArrowLeft,
  ArrowRight,
  Bus,
  Clock,
  Footprints,
  LoaderCircle,
  MapPin,
  Repeat,
  Route,
  Search,
  Ticket,
  Timer,
  Umbrella,
  X,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { formatStreetAddress, type StreetAddress } from '@/lib/address';
import { cn, formatMeters } from '@/lib/utils';

type ServiceHours = {
  raw: string | null;
  firstTrip: string | null;
  lastTrip: string | null;
  runningNow: boolean | null;
  endsInMinutes: number | null;
  startsInMinutes: number | null;
};

type BusLine = {
  key: string;
  ref: string;
  name: string;
  network: string | null;
  operator: string | null;
  colour: string | null;
  charge: number | null;
  interval: { minMinutes: number; maxMinutes: number } | null;
  hours: ServiceHours;
  roundtrip: boolean;
  directions: { id: string; origin: string | null; destination: string | null }[];
};

type RouteStop = {
  id: string;
  name: string;
  latitude: number;
  longitude: number;
  shelter: boolean | null;
  boardingOnly: boolean;
  alightingOnly: boolean;
  distanceMeters: number | null;
  minutesFromStart: number | null;
  /** Giờ xe qua trạm theo giờ chạy của lượt — không phải vị trí xe thật. */
  service: ServiceHours | null;
};

type Direction = {
  id: string;
  name: string;
  origin: string | null;
  destination: string | null;
  via: string | null;
  lengthMeters: number | null;
  tripMinutes: number | null;
  tripMinutesSource: 'osm' | 'estimate' | 'unknown';
  streets: string[];
  path: GeoJSON.MultiLineString | null;
  stops: RouteStop[];
};

type RouteDetail = Omit<BusLine, 'directions'> & {
  selectedId: string;
  averageSpeedKmh: number;
  directions: Direction[];
};

type BusStop = {
  id: string;
  name: string;
  streetAddress: StreetAddress | null;
  latitude: number;
  longitude: number;
  distanceMeters: number;
  shelter: boolean | null;
  routes: {
    routeId: string;
    ref: string;
    destination: string | null;
    colour: string | null;
    interval: BusLine['interval'];
    service: ServiceHours | null;
  }[];
  driveMinutes: number | null;
  driveMeters: number | null;
};

type StopsResponse = { query: string; radius: number | null; approximate: boolean; results: BusStop[] };

const HCMC_NETWORK = 'Xe buýt Thành phố Hồ Chí Minh';
const DEFAULT_COLOUR = '#2563eb';
const ROUTE_SOURCE = 'bus-route';
const STOPS_SOURCE = 'bus-route-stops';
const ROUTE_LAYERS = ['bus-route-casing', 'bus-route-line', 'bus-route-stops', 'bus-route-stops-focus'] as const;

/** Màu tuyến từ thẻ `colour` của OSM ("#1601d3", "#7cfc00", có khi "white"):
 *  chỉ nhận mã hex, và chọn chữ đen/trắng theo độ sáng để số tuyến luôn đọc được. */
function lineColour(colour: string | null): { background: string; color: string } {
  const hex = colour && /^#[0-9a-f]{6}$/i.test(colour) ? colour : DEFAULT_COLOUR;
  const [r, g, b] = [1, 3, 5].map((index) => Number.parseInt(hex.slice(index, index + 2), 16));
  const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  // Màu quá sáng (trắng, vàng chanh) vẽ trên nền bản đồ cũng khó thấy.
  return { background: luminance > 0.85 ? DEFAULT_COLOUR : hex, color: luminance > 0.6 && luminance <= 0.85 ? '#0f172a' : '#ffffff' };
}

function formatMinutes(minutes: number): string {
  if (minutes < 60) return `${minutes} phút`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours} giờ ${rest} phút` : `${hours} giờ`;
}

function formatCharge(charge: number | null): string | null {
  return charge == null ? null : `${charge.toLocaleString('vi-VN')}đ`;
}

function formatInterval(interval: BusLine['interval']): string | null {
  if (!interval) return null;
  return interval.minMinutes === interval.maxMinutes
    ? `${interval.minMinutes} phút/chuyến`
    : `${interval.minMinutes}–${interval.maxMinutes} phút/chuyến`;
}

function serviceLabel(hours: ServiceHours): { text: string; running: boolean | null } | null {
  if (hours.runningNow == null) return null;
  if (hours.runningNow) {
    return {
      running: true,
      text:
        hours.endsInMinutes != null && hours.endsInMinutes <= 90
          ? `Đang chạy · chuyến cuối sau ${formatMinutes(hours.endsInMinutes)}`
          : 'Đang chạy',
    };
  }
  return {
    running: false,
    text:
      hours.startsInMinutes != null
        ? `Hết chuyến · chạy lại sau ${formatMinutes(hours.startsInMinutes)}`
        : 'Hết chuyến',
  };
}

/** Trạng thái xe qua MỘT trạm (giờ chuyến đầu/cuối đã cộng thời gian từ bến
 *  đầu tới trạm). Chỉ suy từ giờ chạy + giãn cách — không biết xe đang ở đâu. */
function stopServiceLabel(
  service: ServiceHours | null,
  interval: BusLine['interval'],
): { text: string; short: string | null; running: boolean } | null {
  if (!service || service.runningNow == null) return null;
  if (service.runningNow) {
    const every = formatInterval(interval);
    if (service.endsInMinutes != null && service.endsInMinutes <= 90 && service.lastTrip) {
      return {
        running: true,
        short: `cuối ~${service.lastTrip}`,
        text: `Chuyến cuối qua trạm khoảng ${service.lastTrip} (còn ~${formatMinutes(service.endsInMinutes)})`,
      };
    }
    return {
      running: true,
      short: null,
      text: [every ? `Xe qua trạm khoảng ${every}` : 'Đang có xe qua trạm', service.lastTrip && `chuyến cuối ~${service.lastTrip}`]
        .filter(Boolean)
        .join(' · '),
    };
  }
  return {
    running: false,
    short: 'hết chuyến',
    text: service.firstTrip
      ? `Hết chuyến qua trạm · chuyến đầu khoảng ${service.firstTrip}${
          service.startsInMinutes != null ? ` (sau ${formatMinutes(service.startsInMinutes)})` : ''
        }`
      : 'Hết chuyến qua trạm',
  };
}

function haversineMeters(a: { latitude: number; longitude: number }, b: { latitude: number; longitude: number }) {
  const toRad = (value: number) => (value * Math.PI) / 180;
  const dLat = toRad(b.latitude - a.latitude);
  const dLng = toRad(b.longitude - a.longitude);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.latitude)) * Math.cos(toRad(b.latitude)) * Math.sin(dLng / 2) ** 2;
  return 6_371_000 * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
}

function RouteBadge({ refLabel, colour, size = 'md' }: { refLabel: string; colour: string | null; size?: 'sm' | 'md' | 'lg' }) {
  return (
    <span
      style={lineColour(colour)}
      className={cn(
        'inline-grid shrink-0 place-items-center rounded-lg font-bold tabular-nums',
        size === 'sm' && 'h-5 min-w-7 rounded-md px-1 text-[11px]',
        size === 'md' && 'h-8 min-w-10 px-1.5 text-sm',
        size === 'lg' && 'h-11 min-w-14 px-2 text-lg',
      )}
    >
      {refLabel}
    </span>
  );
}

function fitRoute(map: MapLibreMap, direction: Direction) {
  const bounds = new maplibregl.LngLatBounds();
  for (const line of direction.path?.coordinates ?? []) for (const point of line) bounds.extend(point as [number, number]);
  for (const stop of direction.stops) bounds.extend([stop.longitude, stop.latitude]);
  if (!bounds.isEmpty()) map.fitBounds(bounds, { padding: 50, maxZoom: 15, duration: 700 });
}

function useDebounced<T>(value: T, delay = 250): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timer);
  }, [delay, value]);
  return debounced;
}

/**
 * Xe buýt — tra tuyến và tìm trạm gần, như ứng dụng MultiGo/BusMap. Xem
 * backend/app/bus.py. Bấm một tuyến (vd "14") ra giờ chạy, giãn cách, giá vé,
 * quãng đường, thời gian chuyến, danh sách trạm theo thứ tự và lộ trình vẽ
 * trên bản đồ. Không có vị trí xe thời gian thực — chỉ giãn cách chuyến.
 */
export function BusFinder({
  apiBaseUrl,
  mapRef,
  userPosition,
  onShowMap,
  onClose,
}: {
  apiBaseUrl: string;
  mapRef: React.RefObject<MapLibreMap | null>;
  userPosition: { latitude: number; longitude: number };
  /** Điện thoại: khung tìm và bản đồ là hai màn riêng — nút "Xem lộ trình
   *  trên bản đồ" chuyển sang màn bản đồ. */
  onShowMap?: () => void;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<'lines' | 'stops'>('lines');
  const [lineQuery, setLineQuery] = useState('');
  const [stopQuery, setStopQuery] = useState('');
  const debouncedLineQuery = useDebounced(lineQuery.trim());
  const debouncedStopQuery = useDebounced(stopQuery.trim());
  const [lines, setLines] = useState<BusLine[] | null>(null);
  const [stops, setStops] = useState<StopsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Chi tiết tuyến đang mở: id của MỘT lượt, cùng trạm cần làm nổi (khi mở từ
  // danh sách trạm gần).
  const [opened, setOpened] = useState<{ routeId: string; focusStopId: string | null } | null>(null);
  const [detail, setDetail] = useState<RouteDetail | null>(null);
  const [directionId, setDirectionId] = useState<string | null>(null);
  const [detailTab, setDetailTab] = useState<'stops' | 'streets'>('stops');
  const [focusStopId, setFocusStopId] = useState<string | null>(null);
  const stopListRef = useRef<HTMLOListElement | null>(null);
  const markersRef = useRef<maplibregl.Marker[]>([]);

  const clearMarkers = useCallback(() => {
    for (const marker of markersRef.current) marker.remove();
    markersRef.current = [];
  }, []);

  const clearRouteLayers = useCallback(() => {
    const map = mapRef.current;
    if (!map) return;
    for (const id of ROUTE_LAYERS) if (map.getLayer(id)) map.removeLayer(id);
    for (const id of [ROUTE_SOURCE, STOPS_SOURCE]) if (map.getSource(id)) map.removeSource(id);
  }, [mapRef]);

  useEffect(
    () => () => {
      clearMarkers();
      clearRouteLayers();
    },
    [clearMarkers, clearRouteLayers],
  );

  // --- Danh sách tuyến ------------------------------------------------------
  useEffect(() => {
    if (tab !== 'lines' || opened) return;
    const controller = new AbortController();
    const params = new URLSearchParams({ q: debouncedLineQuery, limit: debouncedLineQuery ? '60' : '250' });
    // oxlint-disable-next-line react/react-compiler
    setLoading(true);
    setError(null);
    fetch(`${apiBaseUrl}/api/v1/bus/lines?${params}`, { signal: controller.signal })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json() as Promise<{ lines: BusLine[] }>;
      })
      .then((data) => {
        setLines(data.lines);
        setLoading(false);
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setError('Chưa tải được danh sách tuyến, bạn thử lại sau nhé.');
        setLoading(false);
      });
    return () => controller.abort();
  }, [apiBaseUrl, debouncedLineQuery, opened, tab]);

  // --- Trạm gần / tìm trạm theo tên -----------------------------------------
  useEffect(() => {
    if (tab !== 'stops' || opened) return;
    const controller = new AbortController();
    const params = new URLSearchParams({
      lat: String(userPosition.latitude),
      lng: String(userPosition.longitude),
      q: debouncedStopQuery,
    });
    // oxlint-disable-next-line react/react-compiler
    setLoading(true);
    setError(null);
    fetch(`${apiBaseUrl}/api/v1/bus/stops?${params}`, { signal: controller.signal })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json() as Promise<StopsResponse>;
      })
      .then((data) => {
        setStops(data);
        setLoading(false);
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setError('Chưa tìm được trạm xe buýt, bạn thử lại sau nhé.');
        setLoading(false);
      });
    return () => controller.abort();
  }, [apiBaseUrl, debouncedStopQuery, opened, tab, userPosition.latitude, userPosition.longitude]);

  // Marker đánh số cho trạm gần (chỉ khi KHÔNG mở chi tiết tuyến).
  useEffect(() => {
    const map = mapRef.current;
    clearMarkers();
    if (!map || opened || tab !== 'stops' || !stops?.results.length) return;
    const bounds = new maplibregl.LngLatBounds();
    if (!stops.query) bounds.extend([userPosition.longitude, userPosition.latitude]);
    stops.results.forEach((stop, index) => {
      const element = document.createElement('div');
      element.className =
        'grid size-7 place-items-center rounded-full border-2 border-white bg-blue-600 text-[11px] font-bold text-white shadow-md';
      element.textContent = String(index + 1);
      element.title = `${stop.name} · ${stop.routes.map((route) => route.ref).join(', ')}`;
      markersRef.current.push(new maplibregl.Marker({ element }).setLngLat([stop.longitude, stop.latitude]).addTo(map));
      if (index < 6) bounds.extend([stop.longitude, stop.latitude]);
    });
    map.fitBounds(bounds, { padding: 60, maxZoom: 17, duration: 600 });
  }, [clearMarkers, mapRef, opened, stops, tab, userPosition.latitude, userPosition.longitude]);

  // --- Chi tiết tuyến -------------------------------------------------------
  useEffect(() => {
    if (!opened) return;
    const controller = new AbortController();
    // oxlint-disable-next-line react/react-compiler
    setLoading(true);
    setError(null);
    setDetail(null);
    fetch(`${apiBaseUrl}/api/v1/bus/routes/${opened.routeId}`, { signal: controller.signal })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json() as Promise<RouteDetail>;
      })
      .then((data) => {
        setDetail(data);
        setDirectionId(data.selectedId);
        setFocusStopId(opened.focusStopId);
        setDetailTab('stops');
        setLoading(false);
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setError('Chưa tải được thông tin tuyến, bạn thử lại sau nhé.');
        setLoading(false);
      });
    return () => controller.abort();
  }, [apiBaseUrl, opened]);

  const direction = useMemo(
    () => detail?.directions.find((item) => item.id === directionId) ?? detail?.directions[0] ?? null,
    [detail, directionId],
  );

  // Trạm trên lượt này gần người dùng nhất — "lên xe ở đâu".
  const nearestStop = useMemo(() => {
    if (!direction?.stops.length) return null;
    let best: { stop: RouteStop; meters: number } | null = null;
    for (const stop of direction.stops) {
      const meters = haversineMeters(userPosition, stop);
      if (!best || meters < best.meters) best = { stop, meters };
    }
    return best;
  }, [direction, userPosition]);

  // Vẽ lộ trình + trạm của lượt đang xem.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !direction || !detail) {
      clearRouteLayers();
      return;
    }
    clearMarkers();
    const colour = lineColour(detail.colour).background;
    const routeData: GeoJSON.Feature | GeoJSON.FeatureCollection = direction.path
      ? { type: 'Feature', geometry: direction.path, properties: {} }
      : { type: 'FeatureCollection', features: [] };
    const stopsData: GeoJSON.FeatureCollection = {
      type: 'FeatureCollection',
      features: direction.stops.map((stop, index) => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [stop.longitude, stop.latitude] },
        properties: { id: stop.id, name: stop.name, terminal: index === 0 || index === direction.stops.length - 1 },
      })),
    };
    try {
      if (map.getSource(ROUTE_SOURCE)) {
        (map.getSource(ROUTE_SOURCE) as GeoJSONSource).setData(routeData);
        (map.getSource(STOPS_SOURCE) as GeoJSONSource).setData(stopsData);
      } else {
        map.addSource(ROUTE_SOURCE, { type: 'geojson', data: routeData });
        map.addSource(STOPS_SOURCE, { type: 'geojson', data: stopsData });
        map.addLayer({
          id: 'bus-route-casing',
          type: 'line',
          source: ROUTE_SOURCE,
          layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: { 'line-color': '#ffffff', 'line-width': 9, 'line-opacity': 0.9 },
        });
        map.addLayer({
          id: 'bus-route-line',
          type: 'line',
          source: ROUTE_SOURCE,
          layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: { 'line-color': colour, 'line-width': 5 },
        });
        map.addLayer({
          id: 'bus-route-stops',
          type: 'circle',
          source: STOPS_SOURCE,
          paint: {
            'circle-radius': ['case', ['get', 'terminal'], 7, 4.5],
            'circle-color': '#ffffff',
            'circle-stroke-color': colour,
            'circle-stroke-width': ['case', ['get', 'terminal'], 4, 2.5],
          },
        });
        map.addLayer({
          id: 'bus-route-stops-focus',
          type: 'circle',
          source: STOPS_SOURCE,
          filter: ['==', ['get', 'id'], ''],
          paint: { 'circle-radius': 9, 'circle-color': '#f97316', 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 3 },
        });
      }
      map.setPaintProperty('bus-route-line', 'line-color', colour);
      map.setPaintProperty('bus-route-stops', 'circle-stroke-color', colour);
    } catch {
      // Style bản đồ chưa sẵn sàng — danh sách trạm vẫn dùng được.
      return;
    }
    fitRoute(map, direction);
  }, [clearMarkers, clearRouteLayers, detail, direction, mapRef]);

  const showOnMap = () => {
    onShowMap?.();
    // Bản đồ vừa hiện lại sau khi bị ẩn (điện thoại): khung cũ có kích thước 0,
    // phải đo lại rồi mới khung tuyến được.
    window.setTimeout(() => {
      const map = mapRef.current;
      if (!map || !direction) return;
      map.resize();
      fitRoute(map, direction);
    }, 80);
  };

  // Bấm chấm trạm trên bản đồ → làm nổi trạm đó trong danh sách.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !detail) return;
    const onClick = (event: MapLayerMouseEvent) => {
      const id = event.features?.[0]?.properties?.id;
      if (typeof id === 'string') {
        setDetailTab('stops');
        setFocusStopId(id);
      }
    };
    const setPointer = () => (map.getCanvas().style.cursor = 'pointer');
    const resetPointer = () => (map.getCanvas().style.cursor = '');
    map.on('click', 'bus-route-stops', onClick);
    map.on('mouseenter', 'bus-route-stops', setPointer);
    map.on('mouseleave', 'bus-route-stops', resetPointer);
    return () => {
      map.off('click', 'bus-route-stops', onClick);
      map.off('mouseenter', 'bus-route-stops', setPointer);
      map.off('mouseleave', 'bus-route-stops', resetPointer);
    };
  }, [detail, mapRef]);

  // Trạm đang chọn: chấm cam trên bản đồ + cuộn tới dòng của nó.
  useEffect(() => {
    const map = mapRef.current;
    if (map?.getLayer('bus-route-stops-focus')) {
      map.setFilter('bus-route-stops-focus', ['==', ['get', 'id'], focusStopId ?? '']);
    }
    if (!focusStopId) return;
    stopListRef.current
      ?.querySelector(`[data-stop-id="${focusStopId}"]`)
      ?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, [direction, focusStopId, mapRef]);

  const focusStop = (stop: RouteStop) => {
    setFocusStopId(stop.id);
    mapRef.current?.flyTo({ center: [stop.longitude, stop.latitude], zoom: Math.max(mapRef.current.getZoom(), 16) });
  };

  const closeDetail = () => {
    setOpened(null);
    setDetail(null);
    setFocusStopId(null);
    clearRouteLayers();
  };

  const service = detail ? serviceLabel(detail.hours) : null;
  // Trạm đang chọn (bấm từ "Trạm gần" hoặc trong danh sách), không thì trạm gần bạn nhất.
  const boardingStop = direction?.stops.find((stop) => stop.id === focusStopId) ?? nearestStop?.stop ?? null;
  const boardingService = boardingStop && detail ? stopServiceLabel(boardingStop.service, detail.interval) : null;

  return (
    <Card className="shrink-0 rounded-2xl border-blue-900/10 shadow-[0_12px_40px_rgb(30_58_138/8%)] dark:border-white/10">
      <CardHeader className="flex flex-row items-start justify-between gap-2 space-y-0 pb-2">
        <div className="flex min-w-0 items-start gap-2">
          {opened && (
            <Button type="button" size="icon" variant="ghost" onClick={closeDetail} aria-label="Quay lại danh sách" className="-ml-2 shrink-0">
              <ArrowLeft className="size-4" />
            </Button>
          )}
          <div className="min-w-0">
            <CardTitle className="flex items-center gap-2 text-base">
              <Bus className="size-5 text-blue-600" aria-hidden /> Xe buýt
            </CardTitle>
            <CardDescription className="text-xs">
              {opened ? 'Giờ chạy, lộ trình và các trạm dừng' : 'Tra tuyến, tìm trạm gần bạn'}
            </CardDescription>
          </div>
        </div>
        <Button type="button" size="icon" variant="ghost" onClick={onClose} aria-label="Đóng xe buýt">
          <X className="size-4" />
        </Button>
      </CardHeader>

      <CardContent className="space-y-2.5">
        {!opened && (
          <>
            <div className="grid grid-cols-2 gap-1 rounded-xl bg-muted p-1" role="tablist" aria-label="Xe buýt">
              {(
                [
                  ['lines', 'Tra cứu tuyến', Route],
                  ['stops', 'Trạm gần bạn', MapPin],
                ] as const
              ).map(([value, label, Icon]) => (
                <button
                  key={value}
                  type="button"
                  role="tab"
                  aria-selected={tab === value}
                  onClick={() => setTab(value)}
                  className={cn(
                    'flex items-center justify-center gap-1.5 rounded-lg px-2 py-1.5 text-xs font-semibold transition',
                    tab === value ? 'bg-background text-blue-700 shadow-sm dark:text-blue-300' : 'text-muted-foreground hover:text-foreground',
                  )}
                >
                  <Icon className="size-3.5" /> {label}
                </button>
              ))}
            </div>
            <label className="relative block">
              <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
              <span className="sr-only">{tab === 'lines' ? 'Tìm tuyến' : 'Tìm trạm'}</span>
              <Input
                value={tab === 'lines' ? lineQuery : stopQuery}
                onChange={(event) => (tab === 'lines' ? setLineQuery(event.target.value) : setStopQuery(event.target.value))}
                placeholder={tab === 'lines' ? 'Số tuyến, bến hoặc tên đường (vd 14, Miền Tây)' : 'Tên trạm (vd Thảo Cầm Viên) — để trống: trạm gần bạn'}
                className="h-9 pl-8"
              />
            </label>
          </>
        )}

        {loading && (
          <p className="flex items-center gap-2 py-2 text-xs text-muted-foreground">
            <LoaderCircle className="size-4 animate-spin" /> Đang tải…
          </p>
        )}
        {error && <p className="text-xs text-destructive">{error}</p>}

        {/* ---------- Danh sách tuyến ---------- */}
        {!opened && tab === 'lines' && lines && !loading && (
          lines.length === 0 ? (
            <p className="rounded-lg bg-muted px-3 py-2 text-xs text-muted-foreground">
              Không có tuyến nào khớp “{debouncedLineQuery}”.
            </p>
          ) : (
            <ul className="max-h-[26rem] space-y-1.5 overflow-y-auto pr-1">
              {lines.map((line) => (
                <li key={line.key}>
                  <button
                    type="button"
                    onClick={() => setOpened({ routeId: line.directions[0].id, focusStopId: null })}
                    className="flex w-full items-center gap-2.5 rounded-lg border border-border px-2.5 py-2 text-left text-xs transition hover:bg-muted"
                  >
                    <RouteBadge refLabel={line.ref} colour={line.colour} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">{line.name}</span>
                      <span className="block truncate text-muted-foreground">
                        {[
                          line.hours.firstTrip && line.hours.lastTrip ? `${line.hours.firstTrip}–${line.hours.lastTrip}` : null,
                          formatInterval(line.interval),
                          formatCharge(line.charge),
                        ]
                          .filter(Boolean)
                          .join(' · ')}
                      </span>
                      {line.network && line.network !== HCMC_NETWORK && (
                        <span className="block truncate text-[11px] text-amber-700 dark:text-amber-300">{line.network}</span>
                      )}
                    </span>
                    <ArrowRight className="size-4 shrink-0 text-muted-foreground" />
                  </button>
                </li>
              ))}
            </ul>
          )
        )}

        {/* ---------- Trạm gần / tìm trạm ---------- */}
        {!opened && tab === 'stops' && stops && !loading && (
          <>
            {stops.results.length === 0 ? (
              <p className="rounded-lg bg-muted px-3 py-2 text-xs text-muted-foreground">
                {stops.query
                  ? `Không có trạm nào tên “${stops.query}”.`
                  : `Không có trạm xe buýt nào trong ${formatMeters(stops.radius ?? 0)} quanh bạn.`}
              </p>
            ) : (
              <ol className="max-h-[26rem] space-y-1.5 overflow-y-auto pr-1">
                {stops.results.map((stop, index) => (
                  <li key={stop.id} className="rounded-lg border border-border px-2.5 py-2 text-xs">
                    <button
                      type="button"
                      onClick={() => mapRef.current?.flyTo({ center: [stop.longitude, stop.latitude], zoom: 17 })}
                      className="flex w-full items-start gap-2 text-left"
                    >
                      <span className="grid size-6 shrink-0 place-items-center rounded-full bg-blue-600 text-[11px] font-bold text-white">
                        {index + 1}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium">{stop.name}</span>
                        <span className="flex items-center gap-1 truncate text-muted-foreground">
                          {stop.shelter && <Umbrella className="size-3 shrink-0" aria-label="Có mái che" />}
                          {stop.streetAddress ? `~${formatStreetAddress(stop.streetAddress)}` : ''}
                        </span>
                      </span>
                      <span className="shrink-0 text-right">
                        {stop.driveMinutes != null && (
                          <span className="flex items-center justify-end gap-0.5 text-sm font-semibold">
                            <Footprints className="size-3.5" /> {stop.driveMinutes} phút
                          </span>
                        )}
                        <span className="block text-[11px] text-muted-foreground">
                          {formatMeters(stop.driveMeters ?? stop.distanceMeters)}
                        </span>
                      </span>
                    </button>
                    {stop.routes.length > 0 && (
                      <div className="mt-1.5 flex flex-wrap gap-1 pl-8">
                        {stop.routes.map((route) => {
                          const atStop = stopServiceLabel(route.service, route.interval);
                          return (
                            <button
                              key={route.routeId}
                              type="button"
                              onClick={() => setOpened({ routeId: route.routeId, focusStopId: stop.id })}
                              title={[
                                route.destination ? `Tuyến ${route.ref} → ${route.destination}` : `Tuyến ${route.ref}`,
                                atStop?.text,
                              ]
                                .filter(Boolean)
                                .join('\n')}
                              className={cn(
                                'flex items-center gap-1 rounded-md border border-border py-0.5 pr-1.5 pl-0.5 transition hover:bg-muted',
                                atStop?.running === false && 'opacity-60',
                              )}
                            >
                              <RouteBadge refLabel={route.ref} colour={route.colour} size="sm" />
                              <span className="max-w-32 truncate text-[11px] text-muted-foreground">
                                → {route.destination ?? '…'}
                              </span>
                              {atStop?.short && (
                                <span
                                  className={cn(
                                    'shrink-0 text-[10px] font-medium',
                                    atStop.running ? 'text-amber-700 dark:text-amber-300' : 'text-muted-foreground',
                                  )}
                                >
                                  · {atStop.short}
                                </span>
                              )}
                            </button>
                          );
                        })}
                      </div>
                    )}
                  </li>
                ))}
              </ol>
            )}
            <p className="flex items-start gap-1 text-[11px] text-muted-foreground">
              <MapPin className="mt-0.5 size-3 shrink-0" />
              {stops.query
                ? 'Xếp theo khoảng cách đường chim bay từ bạn.'
                : stops.approximate
                  ? 'Thời gian đi bộ là ƯỚC TÍNH (máy chủ định tuyến đang tắt).'
                  : 'Thời gian đi bộ theo đường thật (OSRM).'}{' '}
              Bấm số tuyến để xem lộ trình.
            </p>
          </>
        )}

        {/* ---------- Chi tiết tuyến ---------- */}
        {opened && detail && direction && !loading && (
          <div className="space-y-2.5">
            <div className="flex items-start gap-2.5">
              <RouteBadge refLabel={detail.ref} colour={detail.colour} size="lg" />
              <div className="min-w-0">
                <p className="text-sm leading-snug font-semibold">{detail.name}</p>
                {detail.operator && <p className="truncate text-[11px] text-muted-foreground">{detail.operator}</p>}
                {detail.network && detail.network !== HCMC_NETWORK && (
                  <p className="text-[11px] text-amber-700 dark:text-amber-300">{detail.network}</p>
                )}
              </div>
            </div>

            <div className="grid grid-cols-3 gap-1.5 text-center text-xs">
              <div className="rounded-lg bg-muted px-1.5 py-2">
                <Clock className="mx-auto mb-0.5 size-4 text-blue-600" />
                <p className="font-semibold tabular-nums">
                  {detail.hours.firstTrip && detail.hours.lastTrip
                    ? `${detail.hours.firstTrip}–${detail.hours.lastTrip}`
                    : (detail.hours.raw ?? 'Chưa rõ')}
                </p>
                <p className="text-[10px] text-muted-foreground">Giờ hoạt động</p>
              </div>
              <div className="rounded-lg bg-muted px-1.5 py-2">
                <Repeat className="mx-auto mb-0.5 size-4 text-blue-600" />
                <p className="font-semibold">{formatInterval(detail.interval) ?? 'Chưa rõ'}</p>
                <p className="text-[10px] text-muted-foreground">Giãn cách</p>
              </div>
              <div className="rounded-lg bg-muted px-1.5 py-2">
                <Ticket className="mx-auto mb-0.5 size-4 text-blue-600" />
                <p className="font-semibold">{formatCharge(detail.charge) ?? 'Chưa rõ'}</p>
                <p className="text-[10px] text-muted-foreground">Giá vé/lượt</p>
              </div>
            </div>
            {service && (
              <p
                className={cn(
                  'rounded-lg px-2.5 py-1.5 text-xs font-medium',
                  service.running
                    ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300'
                    : 'bg-amber-50 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300',
                )}
              >
                {service.text}
              </p>
            )}

            {detail.directions.length > 1 && (
              <div className="grid gap-1 rounded-xl bg-muted p-1" style={{ gridTemplateColumns: `repeat(${detail.directions.length}, minmax(0, 1fr))` }} role="tablist" aria-label="Chiều đi">
                {detail.directions.map((item, index) => (
                  <button
                    key={item.id}
                    type="button"
                    role="tab"
                    aria-selected={item.id === direction.id}
                    onClick={() => {
                      setDirectionId(item.id);
                      setFocusStopId(null);
                    }}
                    className={cn(
                      'min-w-0 rounded-lg px-2 py-1.5 text-left text-xs transition',
                      item.id === direction.id ? 'bg-background shadow-sm' : 'text-muted-foreground hover:text-foreground',
                    )}
                  >
                    <span className="block font-semibold">{index === 0 ? 'Lượt đi' : index === 1 ? 'Lượt về' : `Lượt ${index + 1}`}</span>
                    <span className="block truncate text-[11px]">→ {item.destination ?? item.name}</span>
                  </button>
                ))}
              </div>
            )}

            <div className="grid grid-cols-3 gap-1.5 text-center text-xs">
              <div className="rounded-lg border border-border px-1.5 py-1.5">
                <p className="text-sm font-bold">{direction.lengthMeters ? formatMeters(direction.lengthMeters) : '—'}</p>
                <p className="text-[10px] text-muted-foreground">Quãng đường</p>
              </div>
              <div className="rounded-lg border border-border px-1.5 py-1.5">
                <p className="flex items-center justify-center gap-0.5 text-sm font-bold">
                  <Timer className="size-3.5" />
                  {direction.tripMinutes ? `${direction.tripMinutesSource === 'estimate' ? '~' : ''}${formatMinutes(direction.tripMinutes)}` : '—'}
                </p>
                <p className="text-[10px] text-muted-foreground">
                  {direction.tripMinutesSource === 'estimate' ? 'Ước tính/chuyến' : 'Thời gian chuyến'}
                </p>
              </div>
              <div className="rounded-lg border border-border px-1.5 py-1.5">
                <p className="text-sm font-bold">{direction.stops.length}</p>
                <p className="text-[10px] text-muted-foreground">Trạm dừng</p>
              </div>
            </div>

            {onShowMap && (
              <Button type="button" variant="outline" size="sm" onClick={showOnMap} className="w-full lg:hidden">
                <Route className="size-4" /> Xem lộ trình trên bản đồ
              </Button>
            )}

            {nearestStop && (
              <button
                type="button"
                onClick={() => focusStop(nearestStop.stop)}
                className="flex w-full items-center gap-2 rounded-lg bg-blue-50 px-2.5 py-1.5 text-left text-xs text-blue-800 transition hover:bg-blue-100 dark:bg-blue-500/15 dark:text-blue-200"
              >
                <Footprints className="size-4 shrink-0" />
                <span className="min-w-0 flex-1 truncate">
                  Trạm gần bạn nhất: <b>{nearestStop.stop.name}</b>
                </span>
                <span className="shrink-0 font-semibold">{formatMeters(nearestStop.meters)}</span>
              </button>
            )}

            {boardingStop && boardingService && (
              <p
                className={cn(
                  'flex items-start gap-1.5 rounded-lg px-2.5 py-1.5 text-xs',
                  boardingService.running
                    ? 'bg-emerald-50 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-200'
                    : 'bg-amber-50 text-amber-800 dark:bg-amber-500/15 dark:text-amber-200',
                )}
              >
                <Clock className="mt-0.5 size-3.5 shrink-0" />
                <span className="min-w-0">
                  Tại <b>{boardingStop.name}</b>: {boardingService.text}
                </span>
              </p>
            )}

            <div className="flex gap-3 border-b border-border text-xs" role="tablist" aria-label="Chi tiết lượt">
              {(
                [
                  ['stops', `Trạm dừng (${direction.stops.length})`],
                  ['streets', 'Lộ trình'],
                ] as const
              ).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  role="tab"
                  aria-selected={detailTab === value}
                  onClick={() => setDetailTab(value)}
                  className={cn(
                    '-mb-px border-b-2 px-0.5 pb-1.5 font-semibold transition',
                    detailTab === value ? 'border-blue-600 text-blue-700 dark:text-blue-300' : 'border-transparent text-muted-foreground',
                  )}
                >
                  {label}
                </button>
              ))}
            </div>

            {detailTab === 'stops' ? (
              <ol ref={stopListRef} className="max-h-80 overflow-y-auto pr-1">
                {direction.stops.map((stop, index) => {
                  const terminal = index === 0 || index === direction.stops.length - 1;
                  const focused = stop.id === focusStopId;
                  return (
                    <li key={`${stop.id}-${index}`} data-stop-id={stop.id} className="relative pl-6">
                      {/* Đường dọc nối các trạm, như sơ đồ tuyến. */}
                      <span
                        aria-hidden
                        className={cn('absolute left-[9px] w-0.5', index === 0 ? 'top-1/2' : 'top-0', index === direction.stops.length - 1 ? 'h-1/2' : 'bottom-0')}
                        style={{ background: lineColour(detail.colour).background }}
                      />
                      <span
                        aria-hidden
                        className={cn(
                          'absolute top-1/2 left-[4px] -translate-y-1/2 rounded-full border-2 bg-background',
                          terminal ? 'size-3.5 left-[3px]' : 'size-3',
                          focused && 'border-orange-500 bg-orange-500',
                        )}
                        style={focused ? undefined : { borderColor: lineColour(detail.colour).background }}
                      />
                      <button
                        type="button"
                        onClick={() => focusStop(stop)}
                        className={cn(
                          'flex w-full items-center gap-2 rounded-md px-1.5 py-1.5 text-left text-xs transition hover:bg-muted',
                          focused && 'bg-orange-50 dark:bg-orange-500/15',
                        )}
                      >
                        <span className="min-w-0 flex-1">
                          <span className={cn('block truncate', terminal ? 'font-semibold' : 'font-medium')}>{stop.name}</span>
                          {(stop.boardingOnly || stop.alightingOnly || stop.shelter) && (
                            <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
                              {stop.boardingOnly && 'Chỉ lên xe'}
                              {stop.alightingOnly && 'Chỉ xuống xe'}
                              {stop.shelter && (
                                <>
                                  <Umbrella className="size-3" /> Mái che
                                </>
                              )}
                            </span>
                          )}
                        </span>
                        <span className="shrink-0 text-right text-[11px] text-muted-foreground tabular-nums">
                          {stop.distanceMeters != null && <span className="block">{formatMeters(stop.distanceMeters)}</span>}
                          {stop.minutesFromStart != null && index > 0 && <span className="block">~{stop.minutesFromStart} phút</span>}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ol>
            ) : (
              <p className="max-h-80 overflow-y-auto rounded-lg bg-muted px-3 py-2 text-xs leading-relaxed">
                {[direction.origin, ...direction.streets, direction.destination].filter(Boolean).map((name, index, all) => (
                  <span key={`${name}-${index}`}>
                    <span className={cn((index === 0 || index === all.length - 1) && 'font-semibold')}>{name}</span>
                    {index < all.length - 1 && <span className="text-muted-foreground"> – </span>}
                  </span>
                ))}
              </p>
            )}

            <p className="flex items-start gap-1 text-[11px] text-muted-foreground">
              <MapPin className="mt-0.5 size-3 shrink-0" />
              Dữ liệu tuyến từ OpenStreetMap. Chưa có vị trí xe theo thời gian thực — giờ xe qua trạm tính từ giờ chạy và
              giãn cách chuyến.
              {direction.tripMinutesSource === 'estimate' &&
                ` Thời gian ước tính theo vận tốc trung bình ${detail.averageSpeedKmh} km/h; giờ cao điểm có thể lâu hơn.`}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

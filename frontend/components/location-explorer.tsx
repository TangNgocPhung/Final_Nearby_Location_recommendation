'use client';

import { useCallback, useEffect, useEffectEvent, useMemo, useRef, useState } from 'react';
import maplibregl, {
  type GeoJSONSource,
  type Map as MapLibreMap,
  type Marker,
} from 'maplibre-gl';
import {
  Activity,
  ArrowLeft,
  ArrowUp,
  ArrowUpLeft,
  ArrowUpRight,
  Baby,
  BatteryCharging,
  Bell,
  BellRing,
  Bike,
  Bookmark,
  BookmarkCheck,
  Building2,
  Bus,
  Cake,
  Camera,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  CornerUpLeft,
  CornerUpRight,
  Church,
  CircleParking,
  Clock,
  Coffee,
  Compass,
  CreditCard,
  DatabaseZap,
  Droplets,
  EllipsisVertical,
  Dumbbell,
  FerrisWheel,
  Film,
  Flag,
  Flame,
  Flower,
  Flower2,
  Footprints,
  Fuel,
  Gem,
  Glasses,
  GraduationCap,
  Home,
  Hotel,
  CircleQuestionMark,
  Info,
  Landmark,
  Languages,
  LayoutGrid,
  LoaderCircle,
  List,
  LocateFixed,
  type LucideIcon,
  Mailbox,
  Map as MapIcon,
  MapPin,
  Merge,
  MessageCircle,
  Mic,
  ScanEye,
  CloudFog,
  Trash2,
  Trophy,
  WifiOff,
  Moon,
  Navigation,
  PanelLeftClose,
  PanelLeftOpen,
  PartyPopper,
  PawPrint,
  Plane,
  Radio,
  RotateCw,
  Route,
  Scissors,
  Search,
  Shield,
  ShieldCheck,
  ShoppingBag,
  SlidersHorizontal,
  Smile,
  Sparkles,
  Split,
  SprayCan,
  Star,
  Stethoscope,
  Store,
  Sun,
  Toilet,
  TrainFront,
  Trees,
  Undo2,
  UtensilsCrossed,
  Volleyball,
  WashingMachine,
  Wrench,
  X,
  Zap,
} from 'lucide-react';

import { AboutDialog, useAboutDialog } from '@/components/about-dialog';
import { GuideDialog, useGuideDialog } from '@/components/guide-dialog';
import { ChatWidget } from '@/components/chat-widget';
import { VoiceMode } from '@/components/voice-mode';
import { VoiceSearch } from '@/components/voice-search';
import { ArExplorer } from '@/components/ar-explorer';
import { BusFinder } from '@/components/bus-finder';
import { ChargingFinder } from '@/components/charging-finder';
import { ConvenienceFinder } from '@/components/convenience-finder';
import { FuelFinder } from '@/components/fuel-finder';
import { ToiletFinder } from '@/components/toilet-finder';
import { ParkingFinder, type ParkingRequest } from '@/components/parking-finder';
import { useLandmarkAlerts, useNearbyLandmarks } from '@/hooks/use-nearby-landmarks';
import { useProximityNotifications } from '@/hooks/use-proximity';
import { NearbyLandmarksCard } from '@/components/nearby-landmarks-card';
import { usePoiDetail } from '@/hooks/use-poi-detail';
import { fogGeometry, useExploration } from '@/hooks/use-exploration';
import {
  PoiDetailPanel,
  type PoiRouteSummary,
} from '@/components/poi-detail-panel';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { useTheme } from '@/hooks/use-theme';
import { useAutoTranslate } from '@/hooks/use-auto-translate';
import { getTelemetry, type TelemetryState } from '@/lib/telemetry';
import { authHeaders, useAuth } from '@/lib/auth';
import { AccountMenu } from '@/components/account-menu';
import type { AssistantOverlay } from '@/lib/assistant';
import { cn, formatMeters } from '@/lib/utils';
import { formatStreetAddress, type StreetAddress } from '@/lib/address';

type Poi = {
  id: string;
  name: string;
  description: string;
  category: string;
  categoryLabel: string;
  address: string;
  latitude: number;
  longitude: number;
  // Backend tra NULL khi chua ai danh gia (99% POI nhap tu OpenStreetMap).
  // NULL khac 0: "chua biet" khong phai "diem kem" — xem migration 0008.
  rating: number | null;
  reviewCount: number;
  popularityScore: number;
  distanceMeters?: number;
  reason?: string;
  /** Chỉ /recommendations: địa điểm nằm ở ô H3 người dùng chưa từng đi qua. */
  unexplored?: boolean;
  openNow?: boolean | null;
  closesInMinutes?: number | null;
  opensInMinutes?: number | null;
  etaMinutes?: { walk: number; motorbike: number; car: number } | null;
  /** Thứ hạng 0-based do server gán SAU diversify. Optional vì POI mẫu,
   *  trending và recommendations dùng chung kiểu này và không có thứ hạng. */
  rank?: number;
  // Tín hiệu backend đã trả về từ trước nhưng chưa có gì hiển thị. Tất cả đều
  // optional vì type Poi dùng chung cho cả POI mẫu, /trending và /recommendations.
  weather?: WeatherInfo | null;
  weatherFactor?: number;
  traffic?: {
    factor: number;
    isPeakHour: boolean;
    densityPenalty: number;
    source: string;
  } | null;
  trendingScope?: 'hex' | 'global' | 'empty';
  liveNearbyUsers?: number;
  retrievalChannels?: string[];
};

type Position = { latitude: number; longitude: number };

type GeoFilterInfo =
  | {
      geoChannelMode: 'both' | 'h3' | 'geo_distance';
      h3Resolution?: number;
      h3RingK?: number;
      h3CellCount?: number;
      h3Origin?: string;
      h3Skipped?: string;
      h3Outline?: GeoJSON.Polygon | GeoJSON.MultiPolygon;
    }
  | { geoFilter: 'postgis' }
  | null;

type ContextualSearchResponse = {
  requestId: string;
  query: string;
  /** 'opensearch' = truy xuất đa kênh; 'postgis' = đã rơi về đường dự phòng. */
  retrievalBackend: 'opensearch' | 'postgis';
  geoFilter?: GeoFilterInfo;
  ranker?: string;
  searchCenter: Position & { source: 'parsed-location' | 'device-location' };
  parsedLocation: {
    matched: boolean;
    locationText?: string | null;
    bestMatch?: { canonicalName: string; confidence: number } | null;
  };
  results: Poi[];
};

type CategoryOption = {
  category: string;
  categoryLabel: string;
  count: number;
};
/** Một địa điểm trong danh sách "Đã lưu" (GET /api/v1/saved). */
type SavedPlace = {
  id: string;
  poiId: string | null;
  kind: 'saved' | 'home' | 'work';
  label: string;
  address: string;
  latitude: number;
  longitude: number;
};

type TrendingQuery = { query: string; score: number };
type TrendingResponse = {
  redisConnected: boolean;
  pois: Poi[];
  queries: TrendingQuery[];
};
type RecommendationsResponse = {
  personalized: boolean;
  preferredCategories: string[];
  results: Poi[];
};

/** Một gợi ý gõ-tới-đâu từ GET /api/v1/pois/suggest — nhẹ hơn Poi nhiều vì
 *  chưa qua ranking/context, chỉ đủ để hiển thị trong dropdown và bay tới. */
type PoiSuggestion = {
  id: string;
  name: string;
  categoryLabel: string;
  address: string;
  latitude: number;
  longitude: number;
  distanceMeters: number | null;
};

const DEFAULT_POSITION: Position = {
  latitude: 10.7757,
  longitude: 106.7009,
};
const MAX_USABLE_ACCURACY_METERS = 5_000;
const LAST_LOCATION_STORAGE_KEY = 'nearby-last-location';
const LAST_LOCATION_MAX_AGE_MS = 6 * 60 * 60 * 1000;

const SAMPLE_POIS: Poi[] = [
  {
    id: 'poi-001',
    name: 'Cà phê Bến Nghé',
    description: 'Cà phê rang xay, không gian yên tĩnh để làm việc.',
    category: 'cafe',
    categoryLabel: 'Cà phê',
    address: '22 Lý Tự Trọng, Quận 1',
    latitude: 10.7784,
    longitude: 106.7018,
    rating: 4.7,
    reviewCount: 286,
    popularityScore: 0.91,
  },
  {
    id: 'poi-002',
    name: 'Phở Nhà Mình',
    description: 'Phở bò truyền thống, phục vụ từ sáng sớm.',
    category: 'restaurant',
    categoryLabel: 'Ăn uống',
    address: '38 Pasteur, Quận 1',
    latitude: 10.7748,
    longitude: 106.6996,
    rating: 4.6,
    reviewCount: 412,
    popularityScore: 0.95,
  },
  {
    id: 'poi-003',
    name: 'Bảo tàng Thành phố',
    description: 'Không gian lịch sử và kiến trúc giữa trung tâm Sài Gòn.',
    category: 'museum',
    categoryLabel: 'Văn hóa',
    address: '65 Lý Tự Trọng, Quận 1',
    latitude: 10.7763,
    longitude: 106.6994,
    rating: 4.5,
    reviewCount: 732,
    popularityScore: 0.88,
  },
  {
    id: 'poi-004',
    name: 'Vườn xanh Tao Đàn',
    description: 'Khoảng xanh rộng, phù hợp đi bộ và nghỉ trưa.',
    category: 'park',
    categoryLabel: 'Công viên',
    address: 'Trương Định, Quận 1',
    latitude: 10.7742,
    longitude: 106.6937,
    rating: 4.6,
    reviewCount: 968,
    popularityScore: 0.9,
  },
  {
    id: 'poi-005',
    name: 'Bếp Chợ Lớn',
    description: 'Món Việt hiện đại, phù hợp nhóm bạn và gia đình.',
    category: 'restaurant',
    categoryLabel: 'Ăn uống',
    address: '112 Nguyễn Huệ, Quận 1',
    latitude: 10.7735,
    longitude: 106.7045,
    rating: 4.4,
    reviewCount: 197,
    popularityScore: 0.79,
  },
  {
    id: 'poi-006',
    name: 'The Reading Room',
    description: 'Hiệu sách nhỏ kết hợp cà phê và khu đọc tại chỗ.',
    category: 'bookstore',
    categoryLabel: 'Mua sắm',
    address: '14 Đồng Khởi, Quận 1',
    latitude: 10.7769,
    longitude: 106.7059,
    rating: 4.8,
    reviewCount: 154,
    popularityScore: 0.86,
  },
];

const API_BASE_URL = (() => {
  const configured = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8081';
  if (typeof window === 'undefined' || !configured) return configured;
  const apiUrl = new URL(configured, window.location.origin);
  // A phone must reach the computer's API, rather than its own localhost.
  if (['localhost', '127.0.0.1', '[::1]'].includes(apiUrl.hostname)) {
    apiUrl.hostname = window.location.hostname;
  }
  return apiUrl.href.replace(/\/$/, '');
})();
const SELECTED_POINT_COLOR = '#0f8a62';
// POI thật mang UUID từ database; POI mẫu hard-code mang id dạng 'poi-001'.
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Nền bản đồ. `demotiles` của MapLibre chỉ có đường biên quốc gia — marker POI
// nổi trên nền trắng trống, vô nghĩa với một ứng dụng tìm địa điểm đô thị.
// Mặc định dùng raster OpenStreetMap: không cần API key, có đường phố TP.HCM,
// và kèm sẵn attribution ODbL mà giấy phép share-alike bắt buộc phải hiển thị.
// Đặt VITE_MAP_STYLE_URL để chuyển sang style vector (MapTiler, Stadia, hoặc
// tileserver-gl tự dựng) khi cần chất lượng hiển thị cao hơn.
//
// Vì sao VITE_ chứ không phải NEXT_PUBLIC_: bản `vinext` (beta) dùng trong dự
// án này KHÔNG inline biến NEXT_PUBLIC_* vào bundle chạy trên trình duyệt ở
// chế độ dev — nó chỉ tồn tại phía server, nên `process.env.NEXT_PUBLIC_*`
// đọc ra undefined ngay trong `new maplibregl.Map(...)`. Vite thì thay
// `import.meta.env.VITE_*` bằng giá trị thật lúc transform, cho cả hai phía.
// Vẫn đọc NEXT_PUBLIC_ sau đó để không phá cấu hình cũ nếu framework sửa.
//
// KHÔNG gán cứng API key ở đây: repo này công khai trên GitHub, và một key
// nằm trong lịch sử git thì không xoá đi được nữa — phải revoke. Thiếu biến
// môi trường thì lùi về raster OpenStreetMap (không cần key), đúng như thiết
// kế ban đầu; bản đồ xấu hơn nhưng không ai phải lộ key để nó chạy.
//
// Chuỗi rỗng phải lùi về raster: compose luôn truyền biến này xuống (mặc định
// rỗng), mà `style: ''` làm MapLibre chết ngay lúc khởi tạo. Dùng `||` chứ
// không `??` vì `??` chỉ bắt undefined/null, không bắt chuỗi rỗng.
const VITE_ENV = (
  import.meta as unknown as {
    env?: Record<string, string | undefined>;
  }
).env;
const MAP_STYLE_URL =
  VITE_ENV?.VITE_MAP_STYLE_URL?.trim() ||
  process.env.NEXT_PUBLIC_MAP_STYLE_URL?.trim() ||
  '';
// `as const` trên version/type để TypeScript giữ literal 8 và 'raster' thay vì
// nới thành number/string — style spec của MapLibre yêu cầu đúng literal.
const OSM_RASTER_STYLE = {
  version: 8 as const,
  sources: {
    osm: {
      type: 'raster' as const,
      // KHÔNG dùng tile.openstreetmap.org: DNS ở Việt Nam (kiểm chứng trên máy
      // dev 14/09/2026) trả 127.0.0.1 / ::1 cho tên miền này, trong khi
      // Cloudflare DoH trả đúng IP Fastly — tức là chặn ở tầng phân giải tên,
      // không phải mạng hỏng. Hậu quả: mọi tile ERR_CONNECTION_REFUSED,
      // canvas MapLibre rỗng và lớp `.map-fallback` (nền CSS giả trong
      // globals.css) lộ ra. Người dùng đọc màn hình đó là "bản đồ vẽ xấu" chứ
      // không đoán được là bản đồ không tải nổi, nên đây là lỗi im lặng.
      //
      // tile.openstreetmap.de phục vụ cùng dữ liệu OSM, cùng cách render, không
      // cần key, và phân giải bình thường từ đây (200 OK, image/png). Vẫn giữ
      // raster ở nhánh dự phòng này: nó chỉ chạy khi KHÔNG có MAP_STYLE_URL, và
      // raster không cần glyphs/sprite nên ít thứ hỏng hơn khi mạng đã khó.
      tiles: ['https://tile.openstreetmap.de/{z}/{x}/{y}.png'],
      tileSize: 256,
      // Giữ 19: đã thử tay z18 và z19 trên máy chủ này, cả hai trả 200 PNG.
      maxzoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors (ODbL) &middot; tiles <a href="https://www.openstreetmap.de/">openstreetmap.de</a>',
    },
  },
  // Style raster không có sẵn font. Thiếu `glyphs`, lớp `cluster-count` (dùng
  // text-field để in số POI trong cụm) trượt kiểm tra style và bị MapLibre bỏ qua,
  // nên cụm hiện ra là vòng tròn xanh trống không có số. Font server demo của
  // MapLibre phục vụ sẵn Noto Sans Regular, không cần key.
  glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
  layers: [{ id: 'osm', type: 'raster' as const, source: 'osm' }],
};
// Màu chấm POI có nhãn lạ, không nằm trong CATEGORY_COLORS.
const DEFAULT_POINT_COLOR = '#64748b';
// Màu pin của POI đang chọn — đỏ quen mắt kiểu ghim Google Maps, tách hẳn khỏi
// bảng cam/xanh của các chấm POI để nhìn phát biết ngay "đây là chỗ vừa bấm".
const SELECTED_PIN_COLOR = '#ea4335';

type WeatherInfo = {
  isWet: boolean;
  isHeavyRain: boolean;
  temperatureC?: number | null;
  precipitationMm?: number | null;
  weatherCode?: number | null;
};

/** Câu mô tả thời tiết. Không bao giờ trả chuỗi rỗng — ô trống đọc như hỏng. */
function weatherLabel(w: WeatherInfo) {
  const temp =
    typeof w.temperatureC === 'number'
      ? ` ${Math.round(w.temperatureC)}°C`
      : '';
  if (w.isHeavyRain) return `Mưa to${temp}`;
  if (w.isWet) return `Đang mưa${temp}`;
  return `Trời khô${temp}`;
}

type RouteStep = {
  text: string;
  distanceMeters: number;
  durationSeconds: number;
  name: string | null;
  // Loại rẽ của OSRM (`turn`/`depart`/`arrive`/`roundabout`…) và hướng
  // (`left`/`slight right`/`uturn`…). Tuyến cũ trong cache có thể thiếu.
  maneuver?: { type: string | null; modifier: string | null } | null;
};

type StepVisual = { icon: LucideIcon; tone: string; label: string };

// Màu theo NGHĨA của bước: xanh lá xuất phát, đỏ tới nơi, xanh dương rẽ trái,
// tím rẽ phải, cam vòng xoay/quay đầu — liếc là biết sắp rẽ hướng nào.
const STEP_TONES = {
  depart: 'bg-emerald-500 text-white shadow-emerald-500/30',
  arrive: 'bg-rose-500 text-white shadow-rose-500/30',
  left: 'bg-sky-500 text-white shadow-sky-500/30',
  right: 'bg-violet-500 text-white shadow-violet-500/30',
  straight: 'bg-slate-500 text-white shadow-slate-500/30',
  special: 'bg-amber-500 text-white shadow-amber-500/30',
} as const;

/** Icon + màu cho một bước chỉ đường. Ưu tiên `maneuver` của backend; tuyến
 * cũ không có trường đó thì đọc lại từ câu tiếng Việt do `_maneuver_text` sinh. */
function stepVisual(step: RouteStep): StepVisual {
  let type = step.maneuver?.type ?? '';
  let modifier = step.maneuver?.modifier ?? '';
  if (!type) {
    const text = step.text.toLowerCase();
    if (text.startsWith('bắt đầu')) type = 'depart';
    else if (text.startsWith('tới nơi')) type = 'arrive';
    else if (text.includes('vòng xoay')) type = 'roundabout';
    else if (text.startsWith('nhập làn')) type = 'merge';
    else if (text.startsWith('tại ngã ba')) type = 'fork';
    else type = 'turn';
    if (text.includes('quay đầu')) modifier = 'uturn';
    else if (text.includes('gắt sang trái')) modifier = 'sharp left';
    else if (text.includes('gắt sang phải')) modifier = 'sharp right';
    else if (text.includes('chếch sang trái')) modifier = 'slight left';
    else if (text.includes('chếch sang phải')) modifier = 'slight right';
    else if (text.includes('rẽ trái')) modifier = 'left';
    else if (text.includes('rẽ phải')) modifier = 'right';
  }

  if (type === 'depart') return { icon: Navigation, tone: STEP_TONES.depart, label: 'Xuất phát' };
  if (type === 'arrive') return { icon: Flag, tone: STEP_TONES.arrive, label: 'Tới nơi' };
  if (type === 'roundabout' || type === 'rotary') {
    return { icon: RotateCw, tone: STEP_TONES.special, label: 'Vòng xoay' };
  }
  if (modifier === 'uturn') return { icon: Undo2, tone: STEP_TONES.special, label: 'Quay đầu' };
  const side = modifier.includes('right') ? STEP_TONES.right : STEP_TONES.left;
  if (type === 'merge') return { icon: Merge, tone: side, label: 'Nhập làn' };
  if (type === 'fork') return { icon: Split, tone: side, label: 'Ngã ba' };
  if (modifier === 'slight left') {
    return { icon: ArrowUpLeft, tone: STEP_TONES.left, label: 'Chếch trái' };
  }
  if (modifier === 'slight right') {
    return { icon: ArrowUpRight, tone: STEP_TONES.right, label: 'Chếch phải' };
  }
  if (modifier === 'left' || modifier === 'sharp left') {
    return { icon: CornerUpLeft, tone: STEP_TONES.left, label: 'Rẽ trái' };
  }
  if (modifier === 'right' || modifier === 'sharp right') {
    return { icon: CornerUpRight, tone: STEP_TONES.right, label: 'Rẽ phải' };
  }
  return { icon: ArrowUp, tone: STEP_TONES.straight, label: 'Đi thẳng' };
}

type TransportMode = 'car' | 'motorbike' | 'foot';

type DirectionsResponse = {
  poiId: string;
  poiName: string;
  reason?: 'osrm-unavailable' | 'no-route';
  destination?: {
    address?: string | null;
    streetAddress?: StreetAddress | null;
  };
  route: {
    geometry: GeoJSON.LineString;
    distanceMeters: number;
    durationMinutes: number;
    durationSeconds: number;
    steps: RouteStep[];
    cached: boolean;
    mode: TransportMode;
    approximate: boolean;
  } | null;
};

type RoutePlan = {
  poiId: string;
  poiName: string;
  // Địa chỉ điểm đến: `address` là dữ liệu thật, `streetAddress` là tên đường
  // sát điểm đó (ước lượng) khi POI không có địa chỉ.
  destinationAddress: string | null;
  destinationStreet: StreetAddress | null;
  geometry: GeoJSON.LineString;
  distanceMeters: number;
  durationMinutes: number;
  durationSeconds: number;
  steps: RouteStep[];
  cached: boolean;
  mode: TransportMode;
  approximate: boolean;
};

const TRANSPORT_MODES: { value: TransportMode; label: string; icon: string }[] =
  [
    { value: 'motorbike', label: 'Xe máy', icon: '🏍️' },
    { value: 'car', label: 'Ô tô', icon: '🚗' },
    { value: 'foot', label: 'Đi bộ', icon: '🚶' },
  ];

function distanceInMeters(from: Position, to: Position) {
  const radius = 6_371_000;
  const toRadians = (value: number) => (value * Math.PI) / 180;
  const latitudeDelta = toRadians(to.latitude - from.latitude);
  const longitudeDelta = toRadians(to.longitude - from.longitude);
  const fromLatitude = toRadians(from.latitude);
  const toLatitude = toRadians(to.latitude);
  const haversine =
    Math.sin(latitudeDelta / 2) ** 2 +
    Math.cos(fromLatitude) *
      Math.cos(toLatitude) *
      Math.sin(longitudeDelta / 2) ** 2;
  return (
    radius * 2 * Math.atan2(Math.sqrt(haversine), Math.sqrt(1 - haversine))
  );
}

function enrichSamplePois(
  position: Position,
  query: string,
  radius: number,
  category: string | null,
) {
  const normalizedQuery = query.trim().toLocaleLowerCase('vi');
  return SAMPLE_POIS.map((poi) => ({
    ...poi,
    distanceMeters: distanceInMeters(position, {
      latitude: poi.latitude,
      longitude: poi.longitude,
    }),
  }))
    .filter((poi) => {
      const haystack =
        `${poi.name} ${poi.description} ${poi.categoryLabel}`.toLocaleLowerCase(
          'vi',
        );
      return (
        poi.distanceMeters <= radius &&
        (!normalizedQuery || haystack.includes(normalizedQuery)) &&
        (!category || poi.category === category)
      );
    })
    .sort((left, right) =>
      (left.distanceMeters ?? 0) === (right.distanceMeters ?? 0)
        ? (right.rating ?? -1) - (left.rating ?? -1)
        : (left.distanceMeters ?? 0) - (right.distanceMeters ?? 0),
    );
}

function poisToFeatureCollection(
  pois: Poi[],
): GeoJSON.FeatureCollection<GeoJSON.Point> {
  return {
    type: 'FeatureCollection',
    features: pois.map((poi) => ({
      type: 'Feature',
      properties: {
        id: poi.id,
        color: categoryColor(poi.categoryLabel),
        icon: `${POI_ICON_PREFIX}${poi.categoryLabel}`,
      },
      geometry: { type: 'Point', coordinates: [poi.longitude, poi.latitude] },
    })),
  };
}

function pointColorExpression(
  selectedPoiId: string | null,
): maplibregl.ExpressionSpecification {
  return [
    'case',
    ['==', ['get', 'id'], selectedPoiId ?? ''],
    SELECTED_POINT_COLOR,
    ['get', 'color'],
  ];
}

// Mức zoom tối đa khi khung bản đồ theo tuyến đường — xem effect vẽ tuyến.
const ROUTE_MAX_ZOOM = 16;

function lineBounds(coordinates: number[][]) {
  const bounds = new maplibregl.LngLatBounds();
  for (const point of coordinates) {
    bounds.extend(point as [number, number]);
  }
  return bounds;
}

// Khoảng đệm khi khung tuyến đường: chừa chỗ cho các lớp phủ đang che bản đồ,
// nếu không tuyến vẽ sát mép sẽ nằm dưới lớp phủ. Thẻ chỉ đường đầy đủ rộng
// 360px ở góc trái dưới (sm+) hoặc chiếm đáy bản đồ (điện thoại); thu gọn thì
// chỉ còn một dải mỏng. Bảng debug (nếu bật) nằm góc phải trên.
function routeFitPadding(
  map: MapLibreMap,
  cardCollapsed: boolean,
  debugPanel: boolean,
) {
  const { clientWidth: width, clientHeight: height } = map.getContainer();
  if (width < 640) {
    return {
      top: 70,
      bottom: cardCollapsed ? 90 : Math.round(height * 0.45),
      left: 40,
      right: 40,
    };
  }
  const right = debugPanel && width >= 1280 ? 330 : 60;
  // Chỉ chừa chỗ cho thẻ khi bản đồ đủ rộng; hẹp quá thì fitBounds không xếp
  // vừa và MapLibre bỏ qua cả lệnh.
  const left = !cardCollapsed && width - right >= 700 ? 400 : 60;
  return { top: 80, bottom: cardCollapsed ? 90 : 60, left, right };
}

function fitMapToResults(
  map: MapLibreMap | null,
  position: Position,
  results: Poi[],
) {
  if (!map || results.length === 0) return;
  const bounds = new maplibregl.LngLatBounds();
  bounds.extend([position.longitude, position.latitude]);
  for (const poi of results) {
    bounds.extend([poi.longitude, poi.latitude]);
  }
  map.fitBounds(bounds, { padding: 72, maxZoom: 15, duration: 600 });
}

// Biểu tượng của từng chip danh mục.
//
// Tra theo NHÃN tiếng Việt, không theo mã `category`: `/api/v1/categories` gom
// POI theo `category_label` (xem `ranking.fetch_categories`), nên nhãn mới là
// thứ chip thật sự mang — còn mã thì một nhãn "Mua sắm" ứng với cả
// supermarket, mall, convenience, clothes, electronics...
//
// Đủ 19 nhãn mà `poi_features.CATEGORY_MAP` sinh ra. Nhãn lạ (dữ liệu nhập sau
// này thêm loại mới) rơi về `MapPin` — chip vẫn đọc được vì luôn có chữ đi kèm,
// biểu tượng chỉ để quét nhanh bằng mắt chứ không thay chữ.
const CATEGORY_CHIP_ICONS: Record<string, LucideIcon> = {
  'Ăn uống': UtensilsCrossed,
  'Cà phê': Coffee,
  'Mua sắm': ShoppingBag,
  Chợ: Store,
  'Công viên': Trees,
  'Y tế': Stethoscope,
  'Giáo dục': GraduationCap,
  'Dịch vụ': CreditCard,
  'Lưu trú': Hotel,
  'Giải trí': PartyPopper,
  'Thể thao': Dumbbell,
  'Văn hóa': Landmark,
  'Địa danh': Camera,
  'Xem phim': Film,
  'Sân bay': Plane,
  Spa: Flower2,
  'Nha khoa': Smile,
  'Tiệc cưới & sự kiện': Cake,
  'Cắt tóc': Scissors,
  'Cây xăng': Fuel,
  'Nhà vệ sinh': Toilet,
  'Trạm sạc': BatteryCharging,
  'Sửa xe': Wrench,
  'Rửa xe': SprayCan,
  'Bãi xe': CircleParking,
  'Bến xe': Bus,
  'Ga tàu': TrainFront,
  'Tín ngưỡng': Church,
  'Bưu điện': Mailbox,
  'Công an': Shield,
  'Hành chính': Building2,
  'Mầm non': Baby,
  'Thú cưng': PawPrint,
  'Khu vui chơi': FerrisWheel,
  'Bể bơi': Droplets,
  'Sân thể thao': Volleyball,
  'Giày dép': Footprints,
  'Tiệm vàng': Gem,
  'Kính mắt': Glasses,
  'Tiệm hoa': Flower,
  'Giặt ủi': WashingMachine,
  'Làm đẹp': Sparkles,
};

function categoryChipIcon(label: string): LucideIcon {
  return CATEGORY_CHIP_ICONS[label] ?? MapPin;
}

// Màu chấm POI trên bản đồ theo NHÓM danh mục — 40 nhãn mà 40 màu thì mắt
// không phân biệt nổi, gom thành ~12 họ màu (ăn uống cam, y tế đỏ, mua sắm
// hồng...). Tránh xanh lục emerald vì đó là màu của cụm, và đỏ #ea4335 đã
// dành cho ghim POI đang chọn nên y tế dùng đỏ đậm hơn.
const CATEGORY_COLOR_GROUPS: [string, string[]][] = [
  ['#f97316', ['Ăn uống']],
  ['#92400e', ['Cà phê']],
  ['#db2777', ['Mua sắm', 'Chợ', 'Giày dép', 'Tiệm vàng', 'Kính mắt', 'Tiệm hoa']],
  ['#65a30d', ['Công viên', 'Khu vui chơi']],
  ['#b91c1c', ['Y tế', 'Nha khoa']],
  ['#2563eb', ['Giáo dục', 'Mầm non']],
  ['#0891b2', ['Dịch vụ', 'Bưu điện', 'Giặt ủi', 'Thú cưng', 'Nhà vệ sinh']],
  ['#c026d3', ['Spa', 'Làm đẹp', 'Cắt tóc']],
  ['#4f46e5', ['Lưu trú']],
  ['#9333ea', ['Giải trí', 'Xem phim', 'Tiệc cưới & sự kiện']],
  ['#0d9488', ['Thể thao', 'Bể bơi', 'Sân thể thao']],
  ['#ca8a04', ['Văn hóa', 'Địa danh', 'Tín ngưỡng']],
  ['#475569', ['Cây xăng', 'Trạm sạc', 'Sửa xe', 'Rửa xe', 'Bãi xe', 'Bến xe', 'Ga tàu', 'Sân bay']],
  ['#1e3a8a', ['Công an', 'Hành chính']],
];
const CATEGORY_COLORS: Record<string, string> = Object.fromEntries(
  CATEGORY_COLOR_GROUPS.flatMap(([color, labels]) =>
    labels.map((label) => [label, color]),
  ),
);

function categoryColor(label: string): string {
  return CATEGORY_COLORS[label] ?? DEFAULT_POINT_COLOR;
}

// Ảnh icon của chấm POI đăng ký với MapLibre dưới id `poi-icon:<nhãn>`, tạo
// lười trong `styleimagemissing` — chỉ nhãn nào thật sự xuất hiện mới tốn canvas.
const POI_ICON_PREFIX = 'poi-icon:';
const POI_ICON_SIZE = 15;
const POI_ICON_PIXEL_RATIO = 2;
const POI_ICON_MIN_ZOOM = 15;

type LucideIconNode = [string, Record<string, string | number>][];

// Lấy danh sách phần tử SVG của icon lucide. lucide-react không export
// `__iconNode` qua entry chính, nhưng mỗi icon là forwardRef mà hàm render chỉ
// trả `createElement(Icon, { iconNode, ... })` (không hook) — gọi thẳng là đọc
// được. Đổi phiên bản lucide mà cấu trúc khác thì trả null, chấm vẫn có màu.
function lucideIconNode(icon: LucideIcon): LucideIconNode | null {
  try {
    const element = (
      icon as unknown as {
        render: (props: object, ref: null) => { props: { iconNode?: LucideIconNode } };
      }
    ).render({}, null);
    return element.props.iconNode ?? null;
  } catch {
    return null;
  }
}

// Vẽ icon trắng lên canvas bằng Path2D thay vì nạp SVG qua <img>: nạp ảnh là
// bất đồng bộ, mà `styleimagemissing` cần addImage NGAY trong handler — trễ một
// nhịp là MapLibre đã dựng tile không có icon và không tự vẽ lại.
function renderPoiIcon(icon: LucideIcon): ImageData | null {
  const nodes = lucideIconNode(icon);
  const pixels = POI_ICON_SIZE * POI_ICON_PIXEL_RATIO;
  const canvas = document.createElement('canvas');
  canvas.width = pixels;
  canvas.height = pixels;
  const context = canvas.getContext('2d');
  if (!nodes || !context) return null;
  // viewBox lucide là 24×24, nét 2.
  context.scale(pixels / 24, pixels / 24);
  context.strokeStyle = '#ffffff';
  context.lineWidth = 2.25;
  context.lineCap = 'round';
  context.lineJoin = 'round';
  const num = (value: string | number | undefined) => Number(value ?? 0);
  for (const [tag, attrs] of nodes) {
    let path: Path2D;
    if (tag === 'path') {
      path = new Path2D(String(attrs.d));
    } else if (tag === 'circle') {
      path = new Path2D();
      path.arc(num(attrs.cx), num(attrs.cy), num(attrs.r), 0, Math.PI * 2);
    } else if (tag === 'rect') {
      path = new Path2D();
      path.roundRect(
        num(attrs.x),
        num(attrs.y),
        num(attrs.width),
        num(attrs.height),
        num(attrs.rx),
      );
    } else if (tag === 'line') {
      path = new Path2D(
        `M${num(attrs.x1)} ${num(attrs.y1)}L${num(attrs.x2)} ${num(attrs.y2)}`,
      );
    } else if (tag === 'polyline' || tag === 'polygon') {
      path = new Path2D(
        `M${String(attrs.points)}${tag === 'polygon' ? 'Z' : ''}`,
      );
    } else {
      continue;
    }
    context.stroke(path);
  }
  return context.getImageData(0, 0, pixels, pixels);
}

// Số chip danh mục hiện khi thu gọn — vừa đủ hai hàng trong cột 430px.
const COLLAPSED_CATEGORY_COUNT = 7;
const RADIUS_OPTIONS = [1_000, 3_000, 5_000, 10_000] as const;
// Độ trễ giữa các lần thử lại `/api/v1/categories` khi backend chưa sẵn sàng.
const CATEGORY_RETRY_DELAYS_MS = [1_000, 2_000, 4_000, 8_000, 16_000];

function chipClass(active: boolean) {
  return `nearby-chip whitespace-nowrap rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
    active
      ? 'border-primary bg-primary text-primary-foreground shadow-[0_4px_12px_-2px_rgb(15_138_98/45%)]'
      : 'border-emerald-950/10 bg-white/90 text-foreground/70 shadow-[0_1px_2px_rgb(14_68_48/6%)] hover:border-primary/35 hover:bg-emerald-50/70 hover:text-foreground dark:border-white/10 dark:bg-white/5 dark:hover:bg-white/10'
  }`;
}

export function LocationExplorer() {
  const telemetry = useMemo(() => getTelemetry(API_BASE_URL), []);
  // Ngôn ngữ giao diện (134 ngôn ngữ) — dịch cả trang tại chỗ, xem
  // hooks/use-auto-translate.ts. Thuyết minh trong panel mặc định theo nó.
  const uiLanguage = useAutoTranslate(API_BASE_URL);
  // Nút "Gửi xe" ở panel chi tiết đẩy yêu cầu sang ParkingFinder.
  const [parkingRequest, setParkingRequest] = useState<ParkingRequest | null>(null);
  // Dữ liệu thật có ~45 danh mục: bày hết thì khối tìm kiếm dài gần một màn
  // hình và đẩy danh sách kết quả xuống tận đáy. Mặc định chỉ hiện hai hàng.
  const [categoriesExpanded, setCategoriesExpanded] = useState(false);
  // Khung "Tìm chỗ gửi xe" chỉ hiện khi người dùng cần — để mặc định thì cột
  // trái quá rối. Mở bằng nút gọn ở cột trái hoặc nút "Gửi xe" ở panel chi tiết.
  const [parkingOpen, setParkingOpen] = useState(false);
  const [chargingOpen, setChargingOpen] = useState(false);
  const [fuelOpen, setFuelOpen] = useState(false);
  const [convenienceOpen, setConvenienceOpen] = useState(false);
  const [toiletOpen, setToiletOpen] = useState(false);
  const [busOpen, setBusOpen] = useState(false);
  // Lớp vẽ tạm của trợ lý (tuyến tour, người trong nhóm hẹn, quán gợi ý) — xem
  // components/chat-widget.tsx. Tách khỏi 'route' để chỉ đường và tour không
  // xoá lẫn nhau.
  const [assistantOverlay, setAssistantOverlay] = useState<AssistantOverlay | null>(null);
  const assistantMarkersRef = useRef<Marker[]>([]);
  const assistantOverlayKeyRef = useRef<string>('');
  const landmarkMarkersRef = useRef<Marker[]>([]);
  // "Chạm lên bản đồ để chọn vị trí" (hẹn nhóm). Ref để handler click của
  // MapLibre — đăng ký MỘT lần lúc khởi tạo — luôn đọc giá trị mới nhất.
  const mapPickRef = useRef<((latitude: number, longitude: number) => void) | null>(null);
  const [mapPicking, setMapPicking] = useState(false);
  // Chế độ giọng nói cho người khiếm thị (Alt+V, nút "Giọng nói" trên thanh trên).
  const [voiceOpen, setVoiceOpen] = useState(false);
  // Tìm nhanh bằng giọng (bảng nổi nhỏ) — khác chế độ giọng nói toàn màn hình ở trên.
  const [voiceSearchOpen, setVoiceSearchOpen] = useState(false);
  const [arOpen, setArOpen] = useState(false);
  // Bản đồ sương mù: bật thì ghi ô H3 đã đi qua (xem hooks/use-exploration.ts).
  const [fogOn, setFogOn] = useState(false);
  const [fogGps, setFogGps] = useState<'waiting' | 'ok' | 'denied'>('waiting');
  const [fogDistrictsOpen, setFogDistrictsOpen] = useState(false);
  // Dưới lg bố cục là một ứng dụng ba màn: bản đồ luôn phủ kín vùng giữa, còn
  // "Tìm kiếm" và "Kết quả" là lớp phủ đè lên nó, chuyển bằng thanh tab dưới
  // đáy. Bản đồ KHÔNG bao giờ bị display:none — MapLibre đo khung 0×0 thì
  // fitBounds lúc tìm kiếm tính ra mức zoom vô nghĩa.
  const [mobileView, setMobileView] = useState<'search' | 'map' | 'results'>(
    'map',
  );
  const showMapOnMobile = useCallback(() => {
    if (window.innerWidth < 1024) setMobileView('map');
  }, []);
  const requestMapPick = useCallback(
    (callback: ((latitude: number, longitude: number) => void) | null) => {
      mapPickRef.current = callback;
      setMapPicking(callback !== null);
      if (callback) showMapOnMobile();
    },
    [showMapOnMobile],
  );
  const { theme, toggleTheme } = useTheme();
  const about = useAboutDialog();
  const guide = useGuideDialog(about.open);
  const [chatOpen, setChatOpen] = useState(false);
  const mapContainerRef = useRef<HTMLDivElement>(null);
  // Trên điện thoại bấm một địa điểm trong danh sách thì chuyển sang màn bản
  // đồ để thấy nó, nếu không người dùng chọn xong mà không thấy gì đổi.
  // Lớp phủ "Tìm kiếm"/"Kết quả" dùng chung một vùng cuộn: đổi màn phải đưa
  // nó về đầu, không thì danh sách kết quả mở ra ở giữa chừng.
  const mobileSheetRef = useRef<HTMLElement>(null);
  useEffect(() => {
    mobileSheetRef.current?.scrollTo({ top: 0 });
  }, [mobileView]);
  const skipFirstSelectScrollRef = useRef(true);
  const mapRef = useRef<MapLibreMap | null>(null);
  const mapLoadedRef = useRef(false);
  // GPS có thể trả về trước khi MapLibre dựng xong. Giữ lại tâm cần bay tới
  // để lúc bản đồ sẵn sàng không quay về DEFAULT_POSITION ở Quận 1.
  const pendingLocationCenterRef = useRef<Position | null>(null);
  const userMarkerRef = useRef<Marker | null>(null);
  // Pin đỏ đánh dấu POI đang chọn — kiểu ghim của Google Maps. Tách khỏi lớp
  // circle 'unclustered-point': lớp đó vẫn tô màu mọi POI, còn pin chỉ có MỘT
  // cái và luôn nổi trên cùng (Marker là overlay HTML, không bị layer che).
  const selectedMarkerRef = useRef<Marker | null>(null);
  const selectedSinceRef = useRef<number | null>(null);
  const poisRef = useRef<Poi[]>([]);
  const selectedPoiIdRef = useRef<string | null>(null);
  const focusPoiRef = useRef<(poi: Poi, source?: string) => void>(() => {});
  // Handler click marker được gắn MỘT LẦN trong effect khởi tạo bản đồ, nên nó
  // đóng băng mọi closure của lần render đầu. Đi qua ref là cách duy nhất để nó
  // gọi được bản openDetail mới nhất — y hệt focusPoiRef ngay trên.
  const openDetailRef = useRef<(poiId: string, source: string) => void>(
    () => {},
  );
  // POI cần bay tới NGAY KHI chi tiết về. Chỉ dùng cho đường vào không biết
  // trước toạ độ: mở bằng deep-link thì trong tay chỉ có mỗi UUID, mà để bản đồ
  // đứng yên ở Quận 1 trong khi panel nói về một quán ở Thủ Đức thì người nhận
  // link không hiểu mình đang xem cái gì.
  const flyToOnDetailRef = useRef<string | null>(null);
  // Ngữ cảnh lần tìm kiếm gần nhất. Click phải mang cùng request_id và rank với
  // impression, nếu không thì không ghép cặp được để tính CTR theo vị trí —
  // tức mất một nửa mục đích của việc ghi impression.
  const lastSearchRef = useRef<{
    requestId: string;
    ranks: Map<string, number>;
  } | null>(null);
  const [position, setPosition] = useState(DEFAULT_POSITION);
  // Sai số của GPS thật ứng với `position`; null khi vị trí là mô phỏng/mặc định/đã lưu.
  const [positionAccuracy, setPositionAccuracy] = useState<number | null>(null);
  // POI trong vùng bản đồ đang nhìn — nạp lại mỗi khi kéo/zoom xong (moveend).
  // Tách khỏi `pois`: danh sách kết quả bên trái vẫn là của lần tìm kiếm, còn
  // các chấm trên bản đồ là hợp của cả hai — không có nó thì kéo bản đồ ra
  // khỏi vùng tìm kiếm là trống trơn dù DB có hàng chục nghìn POI.
  //
  // Khai báo TRƯỚC effect [position] bên dưới (dùng setAreaPois) — thứ tự
  // ngược lại từng khiến React Compiler báo lỗi Immutability vì phân tích
  // tĩnh không suy được setAreaPois đã tồn tại khi effect thực sự chạy (dù
  // đúng lúc chạy thời gian thực do effect luôn chạy sau khi component đã
  // dựng xong toàn bộ).
  const [areaPois, setAreaPois] = useState<Poi[]>([]);
  // Bản sao cho các closure sống lâu (handler moveend của bản đồ, đăng ký một
  // lần lúc mount): đọc thẳng `position` ở đó là đóng băng vị trí mặc định.
  const positionRef = useRef<Position>(DEFAULT_POSITION);
  useEffect(() => {
    positionRef.current = position;
  }, [position]);
  // Vị trí đổi (người dùng vừa bật GPS, hoặc đang theo dõi liên tục) thì
  // khoảng cách của các POI đã nạp theo vùng cũng phải tính lại — không thì
  // thẻ vẫn khoe con số đo từ vị trí cũ cho tới lần kéo bản đồ kế tiếp.
  useEffect(() => {
    // Đồng bộ derived state (distanceMeters) theo `position` — bên ngoài
    // React (GPS), không tính lại được ngay trong render vì areaPois đến từ
    // một nguồn khác (nạp theo vùng bản đồ).
    // oxlint-disable-next-line react/react-compiler
    setAreaPois((current) =>
      current.map((poi) => ({
        ...poi,
        distanceMeters: distanceInMeters(position, {
          latitude: poi.latitude,
          longitude: poi.longitude,
        }),
      })),
    );
  }, [position]);
  const [query, setQuery] = useState('');
  // Gợi ý gõ-tới-đâu (autocomplete) cho ô tìm kiếm. Tách khỏi `pois`/`areaPois`:
  // đây là danh sách TÊN để chọn nhanh, không phải kết quả tìm kiếm đã qua
  // ranking, nên không được trộn chung.
  const [suggestions, setSuggestions] = useState<PoiSuggestion[]>([]);
  const [suggestionsOpen, setSuggestionsOpen] = useState(false);
  // Mục đang tô sáng khi điều hướng dropdown bằng bàn phím (-1 = chưa chọn).
  // Theo đúng mẫu ARIA combobox: focus vẫn ở ô input, các mục chỉ được đánh
  // dấu qua aria-activedescendant — không rời focus sang từng mục.
  const [activeSuggestionIndex, setActiveSuggestionIndex] = useState(-1);
  const [radius, setRadius] = useState(3_000);
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [categories, setCategories] = useState<CategoryOption[]>([]);
  const [trending, setTrending] = useState<TrendingResponse | null>(null);
  // Metadata CẤP TRUY VẤN: đường truy xuất đã chạy, vành H3 đã quét, thời tiết
  // tại tâm. Trước đây backend trả đủ nhưng không state nào giữ, nên toàn bộ
  // kiến trúc đa kênh vô hình với người dùng.
  const [searchMeta, setSearchMeta] = useState<{
    backend: 'opensearch' | 'postgis';
    geoFilter: GeoFilterInfo;
    ranker?: string;
  } | null>(null);
  const [recommendations, setRecommendations] = useState<Poi[]>([]);
  const [pois, setPois] = useState<Poi[]>(() =>
    enrichSamplePois(DEFAULT_POSITION, '', 3_000, null),
  );
  const [selectedPoiId, setSelectedPoiId] = useState<string | null>(null);
  // POI đang mở trong panel chi tiết. Cố tình TÁCH khỏi selectedPoiId: chọn một
  // POI (bấm thẻ trong danh sách, bấm marker) là thao tác nhẹ và xảy ra liên
  // tục khi lướt; mở panel là thao tác nặng, kéo theo hai yêu cầu mạng và che
  // mất nửa bản đồ. Gộp hai thứ làm một thì mỗi lần lướt danh sách là một lần
  // gọi Wikimedia.
  const [detailPoiId, setDetailPoiId] = useState<string | null>(null);
  const [status, setStatus] = useState('Dữ liệu mẫu tại trung tâm TP.HCM');
  const [isLoading, setIsLoading] = useState(false);
  const [hasLocationConsent, setHasLocationConsent] = useState(false);
  const [gpsStatus, setGpsStatus] = useState('Vị trí mặc định · chưa dùng GPS');
  // Theo dõi vị trí liên tục (lộ trình B13a). Trước đây chỉ có
  // getCurrentPosition gọi một lần mỗi khi bấm nút, nên topic
  // user-location-pings của sơ đồ gần như không bao giờ có dữ liệu — và cả
  // Dwell Time, Redis GEO theo phiên lẫn geofence đều đói theo.
  const [isWatching, setIsWatching] = useState(false);
  const [watchStatus, setWatchStatus] = useState('Theo dõi vị trí: tắt');
  // Bản đồ tự trượt theo chấm xanh (kiểu Google Maps lúc lái xe). Tách khỏi
  // isWatching: theo dõi vị trí vẫn chạy khi người dùng muốn tự xem bản đồ.
  const [followMe, setFollowMe] = useState(false);
  const watchIdRef = useRef<number | null>(null);
  const lastPingRef = useRef<{ at: number; position: Position } | null>(null);
  // Lần cuối chấm xanh được vẽ lại — dày hơn lastPingRef khi đang bám theo.
  const lastShownRef = useRef<{ at: number; position: Position } | null>(null);
  // Bản mới nhất của followMe cho callback watchPosition (đăng ký một lần).
  const followRef = useRef(false);
  // POI đã đăng ký "nhắc khi tới gần": poiId -> subscriptionId.
  // Địa điểm đã lưu của phiên này. Giữ nguyên mảng từ API (đã sắp Nhà/Chỗ làm
  // lên đầu) thay vì sắp lại ở client: thứ tự là quyết định của backend, hai
  // nơi cùng sắp thì sẽ có ngày lệch nhau.
  const [savedPlaces, setSavedPlaces] = useState<SavedPlace[]>([]);
  const [geofences, setGeofences] = useState<Map<string, string>>(
    () => new Map(),
  );
  // Tuyến đường tới POI đang chọn, tính bằng OSRM tự dựng (lộ trình B16).
  // `null` phân biệt với `routeStatus` để giao diện nói được VÌ SAO chưa có
  // tuyến: đang tính, không có đường đi, hay chưa dựng dữ liệu định tuyến.
  const [route, setRoute] = useState<RoutePlan | null>(null);
  const [routeStatus, setRouteStatus] = useState<
    'idle' | 'loading' | 'none' | 'off'
  >('idle');
  // Mặc định "Xe máy" — phương tiện phổ biến nhất ở TP.HCM. Từ Phase 12.8 đã
  // có đồ thị riêng (osrm/motorbike.lua); máy nào chưa dựng thì backend lùi về
  // đồ thị ô tô và bật cờ `approximate`, giao diện đọc cờ đó chứ không đoán.
  const [transportMode, setTransportMode] =
    useState<TransportMode>('motorbike');
  const [showSteps, setShowSteps] = useState(false);
  // Thu thẻ chỉ đường thành một dải nhỏ để tuyến trên bản đồ không bị che.
  // Mỗi lần bấm "Chỉ đường" mở lại thẻ đầy đủ (xem startNavigation).
  const [directionsCollapsed, setDirectionsCollapsed] = useState(false);
  // Desktop: ẩn cột tìm kiếm bên trái để bản đồ chiếm hết chiều ngang.
  const [mapExpanded, setMapExpanded] = useState(false);
  // POI mà người dùng ĐÃ BẤM "Chỉ đường". Tách khỏi selectedPoiId giống Google
  // Maps: chọn một địa điểm chỉ hiện thông tin, tuyến đường chỉ được tính và
  // vẽ khi người dùng chủ động yêu cầu. Chỉ có hiệu lực khi trùng POI đang chọn
  // (xem `directionsActive`), nên chọn sang POI khác là tự thoát chế độ chỉ đường.
  const [directionsPoiId, setDirectionsPoiId] = useState<string | null>(null);
  const [parserStatus, setParserStatus] = useState(
    'Sẵn sàng hiểu “gần Bến Thành”',
  );
  const [gatewayStatus, setGatewayStatus] = useState('Chưa gửi yêu cầu');
  const [telemetryState, setTelemetryState] = useState<TelemetryState>({
    sessionId: '',
    queued: 0,
    delivered: 0,
    dropped: 0,
    transport: 'idle',
  });
  // Panel "Bảng điều khiển tầng 1" lộ chi tiết hạ tầng (GPS accuracy, trạng
  // thái Redis Stream...) — hữu ích lúc trình bày kiến trúc cho hội đồng,
  // nhưng luôn hiện với người xem link demo thì thiếu chuyên nghiệp. Ẩn mặc
  // định, chỉ bật lại khi có ?debug=1 trên URL.
  const [showDebugPanel, setShowDebugPanel] = useState(false);
  useEffect(() => {
    const debugParam = new URLSearchParams(window.location.search).get(
      'debug',
    );
    // Đọc URLSearchParams — API trình duyệt, chỉ có sau mount.
    // oxlint-disable-next-line react/react-compiler
    if (debugParam === '1' || debugParam === 'true') setShowDebugPanel(true);
  }, []);

  // Kênh thông báo tới gần. Chỉ mở khi người dùng đã đăng ký ít nhất một vùng
  // nhắc: giữ một kết nối SSE cho người chưa dùng tính năng này là tốn một
  // luồng của server để chờ một sự kiện không bao giờ tới.
  const proximity = useProximityNotifications({
    apiBaseUrl: API_BASE_URL,
    sessionId: telemetryState.sessionId,
    enabled: geofences.size > 0,
    onNotification: (notification) => {
      setStatus(
        `Bạn đang ở gần ${notification.title} · ${Math.round(notification.distanceMeters)} m`,
      );
    },
  });

  // clearWatch khi component rời đi. Thiếu đoạn này thì watchPosition sống lâu
  // hơn cả trang: GPS vẫn chạy, pin vẫn hao, và ping vẫn bắn từ một component
  // đã unmount.
  useEffect(() => {
    return () => {
      if (watchIdRef.current !== null) {
        navigator.geolocation.clearWatch(watchIdRef.current);
        watchIdRef.current = null;
      }
    };
  }, []);

  // Nạp lại vùng nhắc đã đăng ký khi có phiên: người dùng tải lại trang vẫn
  // --- Địa điểm đã lưu --------------------------------------------------------
  //
  // Đã đăng nhập thì danh sách thuộc về tài khoản (gửi kèm token), chưa thì
  // thuộc `session_id` ẩn danh. Đăng nhập/đăng xuất đổi `authToken` nên danh
  // sách tự nạp lại theo chủ sở hữu mới — xem `_account_owner_id` ở backend.
  const { token: authToken } = useAuth();
  const exploration = useExploration({
    apiBaseUrl: API_BASE_URL,
    sessionId: telemetryState.sessionId,
    authToken,
    active: fogOn,
  });
  const recordExploration = exploration.record;
  const exploredCellCount = exploration.overview?.cellCount ?? 0;
  const loadFogDistricts = exploration.loadDistricts;
  // Bảng quận mỗi lần nạp phải dò POI gần nhất cho từng ô, nên chỉ nạp khi đang
  // mở và nạp lại khi số ô đổi.
  useEffect(() => {
    if (!fogOn || !fogDistrictsOpen) return;
    // oxlint-disable-next-line react/react-compiler
    void loadFogDistricts();
  }, [fogOn, fogDistrictsOpen, exploredCellCount, loadFogDistricts]);
  const nextFogMilestone = exploration.overview?.milestones.find((milestone) => !milestone.earned) ?? null;

  // Địa danh "Săn địa danh Sài Gòn" ở gần: thẻ trên trang chính, marker trên bản
  // đồ và nhắc khi tới gần. Chung một nguồn dữ liệu với màn Săn địa danh.
  const nearbyLandmarks = useNearbyLandmarks({
    apiBaseUrl: API_BASE_URL,
    sessionId: telemetryState.sessionId,
    position,
  });
  const refreshNearbyLandmarks = nearbyLandmarks.refresh;
  // Khám phá xong trong khung chat thì trạng thái ✓ phải cập nhật khi đóng nó.
  useEffect(() => {
    if (!chatOpen) void refreshNearbyLandmarks();
  }, [chatOpen, refreshNearbyLandmarks]);
  const landmarkAlerts = useLandmarkAlerts({
    landmarks: nearbyLandmarks.landmarks,
    // `positionAccuracy` chỉ khác null khi vị trí đến từ GPS thật.
    hasRealGps: positionAccuracy !== null,
  });
  const [landmarkLayerOn, setLandmarkLayerOn] = useState(true);
  const openLandmark = useCallback(
    (landmark: { poiId: string }) => {
      flyToOnDetailRef.current = landmark.poiId;
      showMapOnMobile();
      openDetailRef.current(landmark.poiId, 'landmark');
    },
    [showMapOnMobile],
  );
  // Bấm vào thông báo "gần địa danh" (Service Worker) thì mở đúng địa danh đó.
  useEffect(() => {
    if (!('serviceWorker' in navigator)) return;
    const onMessage = (event: MessageEvent) => {
      const data = event.data as { type?: string; poiId?: string } | null;
      if (data?.type === 'nearby:focus-poi' && data.poiId) openLandmark({ poiId: data.poiId });
    };
    navigator.serviceWorker.addEventListener('message', onMessage);
    return () => navigator.serviceWorker.removeEventListener('message', onMessage);
  }, [openLandmark]);
  // Backend đã xếp theo độ liên quan; lấy chỗ gần nhất trong số chưa tới để làm
  // đích cho người đang bật sương mù.
  const nextFogTarget = useMemo(
    () =>
      recommendations
        .filter((poi) => poi.unexplored)
        .sort((a, b) => (a.distanceMeters ?? Infinity) - (b.distanceMeters ?? Infinity))[0] ?? null,
    [recommendations],
  );

  // Chế độ sương mù có GPS RIÊNG, không dùng "Theo dõi vị trí": cái đó còn gửi
  // ping telemetry, còn sương mù chỉ ghi ô — bật cái này không được kéo theo
  // việc gửi thêm dữ liệu vị trí nào khác.
  useEffect(() => {
    if (!fogOn || !navigator.geolocation) return;
    const id = navigator.geolocation.watchPosition(
      ({ coords }) => {
        setFogGps('ok');
        void recordExploration({
          latitude: coords.latitude,
          longitude: coords.longitude,
          accuracy: coords.accuracy,
        });
      },
      () => setFogGps('denied'),
      { enableHighAccuracy: true, maximumAge: 10_000, timeout: 20_000 },
    );
    return () => navigator.geolocation.clearWatch(id);
  }, [fogOn, recordExploration]);
  const reloadSavedPlaces = useCallback(async () => {
    const sessionId = telemetryState.sessionId;
    if (!sessionId) return;
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/saved`, {
        headers: {
          'X-Session-ID': sessionId,
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
      });
      if (!response.ok) return;
      const data = (await response.json()) as { places?: SavedPlace[] };
      setSavedPlaces(data.places ?? []);
    } catch {
      // Mất mạng thì giữ nguyên danh sách đang hiện, đừng xoá trắng: danh sách
      // rỗng trông giống "bạn chưa lưu gì" và người dùng sẽ lưu lại lần nữa.
    }
  }, [telemetryState.sessionId, authToken]);

  useEffect(() => {
    // Fetch rồi setState — đúng mẫu effect chính đáng theo tài liệu React
    // (mục "Update external systems with the latest state from React").
    // oxlint-disable-next-line react/react-compiler
    void reloadSavedPlaces();
  }, [reloadSavedPlaces]);

  const savedByPoi = useMemo(() => {
    const map = new Map<string, SavedPlace>();
    for (const place of savedPlaces) {
      if (place.poiId) map.set(place.poiId, place);
    }
    return map;
  }, [savedPlaces]);

  /** Lưu / bỏ lưu một POI. `kind` = 'home' để đặt làm nhà. */
  const toggleSaved = useCallback(
    async (poi: Poi, kind: SavedPlace['kind'] = 'saved') => {
      const sessionId = telemetryState.sessionId;
      if (!sessionId) {
        setStatus('Chưa có phiên làm việc — tải lại trang rồi thử lại');
        return;
      }
      // POI mẫu (id dạng 'poi-001') không tồn tại trong database, lưu sẽ 404.
      // Nói thẳng lý do thay vì để người dùng đoán, giống toggleGeofence.
      if (!UUID_PATTERN.test(poi.id)) {
        setStatus('Đây là địa điểm mẫu, chưa có trong dữ liệu thật');
        return;
      }
      const existing = savedByPoi.get(poi.id);
      try {
        if (existing && kind === 'saved') {
          await fetch(`${API_BASE_URL}/api/v1/saved/${existing.id}`, {
            method: 'DELETE',
            headers: { 'X-Session-ID': sessionId, ...authHeaders() },
          });
          setStatus(`Đã bỏ lưu "${poi.name}"`);
        } else {
          const response = await fetch(`${API_BASE_URL}/api/v1/saved`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-Session-ID': sessionId,
              ...authHeaders(),
            },
            // KHÔNG gửi toạ độ: backend lấy thẳng từ pois.location, cùng lý do
            // với geofence — lỗi phía này sẽ ghim "nhà" ở sai chỗ.
            body: JSON.stringify({ poi_id: poi.id, kind }),
          });
          if (!response.ok) {
            const detail = await response.text();
            throw new Error(`HTTP ${response.status} ${detail.slice(0, 160)}`);
          }
          setStatus(
            kind === 'home'
              ? `Đã đặt "${poi.name}" làm nhà`
              : `Đã lưu "${poi.name}"`,
          );
        }
        await reloadSavedPlaces();
      } catch (error) {
        setStatus(
          `Không lưu được: ${error instanceof Error ? error.message : 'lỗi không rõ'}`,
        );
      }
    },
    [savedByPoi, reloadSavedPlaces, telemetryState.sessionId],
  );

  const removeSavedPlace = useCallback(
    async (place: SavedPlace) => {
      const sessionId = telemetryState.sessionId;
      if (!sessionId) return;
      try {
        await fetch(`${API_BASE_URL}/api/v1/saved/${place.id}`, {
          method: 'DELETE',
          headers: { 'X-Session-ID': sessionId, ...authHeaders() },
        });
        setStatus(`Đã bỏ lưu "${place.label}"`);
        await reloadSavedPlaces();
      } catch {
        setStatus('Không xoá được, thử lại sau');
      }
    },
    [reloadSavedPlaces, telemetryState.sessionId],
  );

  // phải thấy đúng những POI mình đã bật nhắc, nếu không nút sẽ báo sai trạng
  // thái và cú bấm kế tiếp tạo thêm một vùng trùng.
  useEffect(() => {
    const sessionId = telemetryState.sessionId;
    if (!sessionId) return;
    let cancelled = false;
    void (async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/v1/geofences`, {
          headers: { 'X-Session-ID': sessionId },
        });
        if (!response.ok) return;
        const data = (await response.json()) as {
          subscriptions: Array<{ id: string; poiId: string | null }>;
        };
        if (cancelled) return;
        const next = new Map<string, string>();
        for (const item of data.subscriptions ?? []) {
          if (item.poiId) next.set(item.poiId, item.id);
        }
        setGeofences(next);
      } catch {
        // Không có vùng nhắc nào là trạng thái hợp lệ; im lặng là đúng ở đây.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [telemetryState.sessionId]);

  // Kết quả tìm kiếm đứng trước và thắng khi trùng id: chúng mang request_id
  // và rank phục vụ telemetry, còn bản ghi từ /api/pois/nearby thì không.
  // Khai báo TRƯỚC effect lấy tuyến ngay dưới — deps của effect được đánh giá
  // lúc render, đặt sau là ReferenceError (temporal dead zone).
  const visiblePois = useMemo(() => {
    const seen = new Set(pois.map((poi) => poi.id));
    return [...pois, ...areaPois.filter((poi) => !seen.has(poi.id))];
  }, [pois, areaPois]);

  // POI đang chọn. Khai báo PHẢI nằm trên effect lấy tuyến bên dưới: mảng
  // dependency của effect đó đọc `selectedPoi?.id` NGAY TRONG LÚC RENDER, nên
  // để khai báo ở dưới là chạm vùng chết (TDZ) chứ không phải hoisting vô hại.
  //
  // `visiblePois` đổi ĐỊNH DANH mỗi lần areaPois nạp lại — chuyện bình thường
  // khi kéo bản đồ — nên effect lấy tuyến không được phụ thuộc vào chính mảng
  // đó, xem ghi chú ở effect.
  const selectedPoi = useMemo(
    () => visiblePois.find((item) => item.id === selectedPoiId) ?? null,
    [visiblePois, selectedPoiId],
  );
  // Địa chỉ hiện dưới tên điểm đến ở thẻ chỉ đường: địa chỉ thật nếu có, không
  // thì tên đường sát điểm đó (đánh dấu "~" vì là ước lượng từ OSRM).
  const directionsAddress = useMemo(() => {
    if (!selectedPoi) return null;
    if (selectedPoi.address) return selectedPoi.address;
    if (route && route.poiId === selectedPoi.id) {
      if (route.destinationAddress) return route.destinationAddress;
      if (route.destinationStreet)
        return `~${formatStreetAddress(route.destinationStreet)}`;
    }
    return null;
  }, [selectedPoi, route]);

  useEffect(() => {
    // Bỏ lần chạy đầu: 'poi-001' được chọn sẵn lúc mở trang, không phải thao tác của người dùng.
    if (skipFirstSelectScrollRef.current) {
      skipFirstSelectScrollRef.current = false;
      return;
    }
    if (!selectedPoiId || typeof window === 'undefined') return;
    // Sang khung hình kế tiếp: đổi màn ngay trong effect sẽ render dây chuyền
    // giữa lúc các effect khác (vẽ marker, lấy tuyến) còn đang chạy.
    const frame = requestAnimationFrame(showMapOnMobile);
    return () => cancelAnimationFrame(frame);
  }, [selectedPoiId, showMapOnMobile]);
  // Giá trị nguyên thuỷ tách riêng để effect lấy tuyến đường bên dưới KHÔNG
  // bao giờ đóng gói tham chiếu tới `selectedPoi`/`visiblePois` — xem lý do
  // (179 request/lượt xem, đo được thật) ngay tại effect đó.
  const selectedPoiLatitude = selectedPoi?.latitude ?? null;
  const selectedPoiLongitude = selectedPoi?.longitude ?? null;
  const selectedPoiName = selectedPoi?.name ?? null;
  const directionsActive =
    directionsPoiId !== null && directionsPoiId === selectedPoiId;

  // Lấy tuyến đường khi người dùng bật chỉ đường cho POI đang chọn, và tính lại
  // khi đổi vị trí người dùng hoặc phương tiện. Chỉ CHỌN POI thì không gọi gì.
  //
  // Huỷ bằng AbortController: chọn nhanh ba POI liên tiếp thì ba yêu cầu cùng
  // bay, và nếu không huỷ thì cái nào về SAU sẽ ghi đè — người dùng thấy tuyến
  // tới POI họ đã bỏ chọn. Đây là lỗi hay gặp và rất khó lần ra vì nó chỉ xảy
  // ra khi mạng chậm.
  useEffect(() => {
    // visiblePois chứ không chỉ pois: POI nạp theo vùng bản đồ (areaPois) cũng
    // chọn được từ marker, và thẻ của nó cũng phải có tuyến nội bộ — tra trong
    // mỗi kết quả tìm kiếm thì các POI đó vĩnh viễn không có đường đi.
    //
    // CHỈ đọc các biến nguyên thuỷ đã tách sẵn (selectedPoiId/Latitude/…) —
    // KHÔNG đọc `selectedPoi` (object) ở đây, dù object đó có đủ thông tin.
    // Đây là điểm mấu chốt để effect không phải liệt kê `selectedPoi` vào
    // deps, xem giải thích đầy đủ ở deps bên dưới.
    if (
      !directionsActive ||
      !selectedPoiId ||
      selectedPoiLatitude === null ||
      selectedPoiLongitude === null ||
      selectedPoiName === null
    ) {
      // Reset có chủ đích khi bỏ chọn POI hoặc thoát chế độ chỉ đường.
      // oxlint-disable-next-line react/react-compiler
      setRoute(null);
      setRouteStatus('idle');
      return;
    }

    const controller = new AbortController();
    setRouteStatus('loading');
    void (async () => {
      try {
        const params = new URLSearchParams({
          from_lat: String(position.latitude),
          from_lng: String(position.longitude),
          mode: transportMode,
        });
        if (UUID_PATTERN.test(selectedPoiId)) {
          params.set('to_poi_id', selectedPoiId);
        } else {
          // POI mẫu chưa tồn tại trong Postgres nên không có UUID. Gửi cặp toạ
          // độ của chính dữ liệu mẫu để backend vẫn tính OSRM và giữ người dùng
          // ở trong website.
          params.set('to_lat', String(selectedPoiLatitude));
          params.set('to_lng', String(selectedPoiLongitude));
          params.set('to_name', selectedPoiName);
        }
        const response = await fetch(
          `${API_BASE_URL}/api/v1/directions?${params}`,
          {
            signal: controller.signal,
          },
        );
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = (await response.json()) as DirectionsResponse;
        if (controller.signal.aborted) return;
        if (!data.route) {
          setRoute(null);
          setRouteStatus(data.reason === 'osrm-unavailable' ? 'off' : 'none');
          return;
        }
        setRoute({
          // Với POI mẫu backend trả id tổng quát vì nó chỉ nhận toạ độ. State
          // phía giao diện phải giữ id thật của thẻ để startNavigation ghép đúng
          // tuyến với địa điểm đang chọn.
          poiId: selectedPoiId,
          poiName: selectedPoiName,
          destinationAddress: data.destination?.address ?? null,
          destinationStreet: data.destination?.streetAddress ?? null,
          geometry: data.route.geometry,
          distanceMeters: data.route.distanceMeters,
          durationMinutes: data.route.durationMinutes,
          durationSeconds: data.route.durationSeconds,
          steps: data.route.steps ?? [],
          cached: Boolean(data.route.cached),
          mode: data.route.mode,
          approximate: data.route.approximate,
        });
        setRouteStatus('idle');
      } catch (error) {
        if ((error as Error)?.name === 'AbortError') return;
        setRoute(null);
        setRouteStatus('none');
      }
    })();

    return () => controller.abort();
    // CHỈ phụ thuộc giá trị nguyên thuỷ, không phụ thuộc object/mảng.
    //
    // Bản cũ liệt kê `visiblePois` và `position` và tạo ra một vòng lặp fetch
    // VÔ HẠN: setRoute trả object mới -> effect [route] gọi map.fitBounds ->
    // hoạt ảnh kết thúc bắn moveend -> loadAreaPois -> setAreaPois trả mảng
    // mới -> visiblePois đổi định danh -> effect này chạy lại -> setRoute...
    // Đo được 179 request /api/v1/directions và 160 request /api/pois/nearby
    // chỉ trong MỘT lượt xem trang, đủ để backend trả 429.
    //
    // Toạ độ và id là thứ thực sự quyết định tuyến đường; định danh của mảng
    // chứa chúng thì không.
  }, [
    directionsActive,
    selectedPoiId,
    selectedPoiLatitude,
    selectedPoiLongitude,
    selectedPoiName,
    position.latitude,
    position.longitude,
    transportMode,
  ]);

  // Vẽ sương mù. Dữ liệu cũng giữ trong ref: lượt nạp đầu có thể về TRƯỚC khi
  // bản đồ dựng xong lớp, lúc đó initMapLayers lấy từ ref.
  const fogDataRef = useRef<{ fog: GeoJSON.FeatureCollection; explored: GeoJSON.FeatureCollection }>({
    fog: { type: 'FeatureCollection', features: [] },
    explored: { type: 'FeatureCollection', features: [] },
  });
  const fogShape = exploration.overview?.shape ?? null;
  useEffect(() => {
    const empty: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };
    const asCollection = (geometry: GeoJSON.Geometry): GeoJSON.FeatureCollection => ({
      type: 'FeatureCollection',
      features: [{ type: 'Feature', properties: {}, geometry }],
    });
    fogDataRef.current = fogOn
      ? { fog: asCollection(fogGeometry(fogShape)), explored: fogShape ? asCollection(fogShape) : empty }
      : { fog: empty, explored: empty };
    const map = mapRef.current;
    if (!map || !mapLoadedRef.current) return;
    (map.getSource('fog') as GeoJSONSource | undefined)?.setData(fogDataRef.current.fog);
    (map.getSource('explored') as GeoJSONSource | undefined)?.setData(fogDataRef.current.explored);
  }, [fogOn, fogShape]);

  // Vẽ vành hexagon H3 của lần tìm kiếm gần nhất.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoadedRef.current) return;
    const source = map.getSource('h3-ring') as GeoJSONSource | undefined;
    if (!source) return;
    const info = searchMeta?.geoFilter;
    const outline = info && !('geoFilter' in info) ? info.h3Outline : undefined;
    source.setData(
      outline
        ? {
            type: 'FeatureCollection',
            features: [{ type: 'Feature', properties: {}, geometry: outline }],
          }
        : { type: 'FeatureCollection', features: [] },
    );
  }, [searchMeta]);

  // Vẽ tuyến lên bản đồ và lùi khung nhìn cho vừa cả tuyến.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoadedRef.current) return;
    const source = map.getSource('route') as GeoJSONSource | undefined;
    if (!source) return;

    if (!route) {
      source.setData({ type: 'FeatureCollection', features: [] });
      return;
    }
    source.setData({
      type: 'FeatureCollection',
      features: [{ type: 'Feature', properties: {}, geometry: route.geometry }],
    });

  }, [route]);

  // Lùi khung nhìn cho vừa cả tuyến — chạy lại khi thu/mở thẻ chỉ đường hoặc
  // phóng to bản đồ, vì vùng bản đồ thực sự nhìn thấy đã đổi.
  // maxZoom bắt buộc: POI đầu tiên được tự chọn có thể cách người dùng chỉ
  // vài mét (đo được 10 m ở Quận 11) — tuyến ngắn như vậy mà không kẹp zoom
  // thì fitBounds đẩy bản đồ tới mức sát nóc nhà, khung nhìn còn vài chục mét
  // và mọi POI khác rơi ra ngoài: người dùng thấy "quanh tôi không có gì".
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoadedRef.current || !route) return;
    // Đợi một khung hình để lưới bố cục đổi cột xong rồi mới đo kích thước.
    const frame = requestAnimationFrame(() => {
      map.resize();
      map.fitBounds(lineBounds(route.geometry.coordinates), {
        padding: routeFitPadding(map, directionsCollapsed, showDebugPanel),
        maxZoom: ROUTE_MAX_ZOOM,
        duration: 700,
      });
    });
    return () => cancelAnimationFrame(frame);
  }, [route, directionsCollapsed, mapExpanded, showDebugPanel]);

  // Thời tiết là tín hiệu CẤP TRUY VẤN: backend lấy một lần cho cả lượt tìm rồi
  // gắn cùng một object vào mọi ứng viên. Đọc từ kết quả đầu tiên là đủ.
  const queryWeather = useMemo<WeatherInfo | null>(
    () =>
      (pois.find((poi) => poi.weather)?.weather as WeatherInfo | undefined) ??
      null,
    [pois],
  );

  const h3Badge = useMemo(() => {
    const info = searchMeta?.geoFilter;
    if (!info || 'geoFilter' in info) return null;
    if (info.h3Skipped) return 'H3 bỏ qua · bán kính quá lớn';
    if (!info.h3CellCount) return null;
    return `H3 r${info.h3Resolution} · vành k=${info.h3RingK} · ${info.h3CellCount} ô`;
  }, [searchMeta]);

  const fallbackCategories = useMemo<CategoryOption[]>(() => {
    const counts = new Map<string, CategoryOption>();
    for (const poi of SAMPLE_POIS) {
      const existing = counts.get(poi.category);
      counts.set(poi.category, {
        category: poi.category,
        categoryLabel: poi.categoryLabel,
        count: (existing?.count ?? 0) + 1,
      });
    }
    return Array.from(counts.values());
  }, []);
  const categoryOptions =
    categories.length > 0 ? categories : fallbackCategories;
  // Trending/gợi ý phục vụ trạng thái khám phá ban đầu. Khi người dùng đã gõ
  // từ khoá hoặc chọn danh mục, đặt chúng trước kết quả sẽ đẩy đúng thứ họ vừa
  // tìm xuống dưới nếp gấp — đặc biệt rõ trên màn hình laptop có chiều cao CSS
  // thấp do display scaling.
  const showDiscovery = query.trim().length === 0 && selectedCategory === null;

  useEffect(() => {
    poisRef.current = visiblePois;
  }, [visiblePois]);
  useEffect(() => {
    selectedPoiIdRef.current = selectedPoiId;
  }, [selectedPoiId]);

  const focusPoi = useCallback(
    (poi: Poi, source = 'list') => {
      if (
        selectedPoiId &&
        selectedPoiId !== poi.id &&
        selectedSinceRef.current !== null
      ) {
        telemetry.capture({
          // Đây là sự kiện RỜI một POI đã click, không phải impression. Trước
          // đây nó mang nhãn 'poi_impression', khiến impression trở thành tập
          // con của click và đẩy CTR trong feature store tiến tới 1.0.
          event_type: 'poi_dwell',
          poi_id: selectedPoiId,
          dwell_ms: Date.now() - selectedSinceRef.current,
          metadata: { source },
        });
      }
      // Chỉ đóng dấu request_id khi POI này THỰC SỰ nằm trong lần tìm kiếm gần
      // nhất. lastSearchRef không bao giờ bị xoá, nên nếu gắn vô điều kiện thì
      // click vào POI từ trending hay gợi ý cũng mang request_id của một lần
      // tìm kiếm chẳng liên quan — tạo cặp impression/click giả trong bảng huấn
      // luyện, đúng loại nhiễu mà bước A2 sinh ra để loại bỏ.
      const searchContext = lastSearchRef.current;
      const rankInSearch = searchContext?.ranks.get(poi.id);
      telemetry.capture({
        event_type: 'poi_click',
        poi_id: poi.id,
        metadata: {
          source,
          ...(rankInSearch === undefined
            ? {}
            : { request_id: searchContext?.requestId, rank: rankInSearch }),
        },
      });
      selectedSinceRef.current = Date.now();
      // Chọn POI khác thì về lại chế độ xem thông tin. Bấm lại đúng POI đang
      // chỉ đường thì giữ nguyên tuyến.
      setDirectionsPoiId((current) => (current === poi.id ? current : null));
      setSelectedPoiId(poi.id);
      mapRef.current?.flyTo({
        center: [poi.longitude, poi.latitude],
        zoom: 15.5,
        essential: true,
      });
      // Gọi thẳng ở đây chứ không chỉ trông vào effect theo selectedPoiId: bấm
      // lại đúng POI đang chọn thì id không đổi, effect không chạy, và người
      // dùng kẹt lại ở màn danh sách.
      showMapOnMobile();
    },
    [selectedPoiId, telemetry, showMapOnMobile],
  );
  useEffect(() => {
    focusPoiRef.current = focusPoi;
  }, [focusPoi]);

  // Ghi/xoá tham số ?poi= trên thanh địa chỉ. pushState chứ không đổi route:
  // đổi route sẽ dựng lại cả trang, bản đồ khởi tạo lại từ đầu và mất luôn
  // khung nhìn người dùng đang ở.
  const syncDetailUrl = useCallback((poiId: string | null, replace = false) => {
    if (typeof window === 'undefined') return;
    const url = new URL(window.location.href);
    if (poiId) url.searchParams.set('poi', poiId);
    else url.searchParams.delete('poi');
    const next = `${url.pathname}${url.search}${url.hash}`;
    if (replace) window.history.replaceState({ poi: poiId }, '', next);
    else window.history.pushState({ poi: poiId }, '', next);
  }, []);

  const openDetail = useCallback(
    (poiId: string, source: string) => {
      // POI mẫu hard-code không có trong database: backend trả 400 và panel sẽ
      // mở ra trống trơn. Nói thẳng nguyên nhân giống toggleGeofence thay vì
      // bày một khung rỗng để người dùng tự đoán.
      if (!UUID_PATTERN.test(poiId)) {
        setStatus(
          'Đây là địa điểm mẫu, chưa có trong dữ liệu thật — hãy tìm kiếm trước',
        );
        return;
      }
      setDetailPoiId(poiId);
      // Chỉ đẩy history khi THỰC SỰ đổi POI. Bấm lại đúng marker đang mở là
      // chuyện thường xuyên; pushState vô điều kiện thì mỗi cú bấm thêm một
      // mục vào lịch sử và người dùng phải bấm Lùi năm lần mới ra khỏi trang.
      if (detailPoiId !== poiId) syncDetailUrl(poiId);
      // CHỈ phát poi_click ở hai lối vào này. Mở từ marker hay từ thẻ "Đang
      // chọn" thì focusPoi đã phát rồi; phát thêm lần nữa là đếm một cú bấm
      // thành hai và thổi phồng CTR trong feature store — đúng lỗi mà nhãn
      // poi_dwell/poi_impression đã phải sửa một lần.
      if (source === 'deep-link' || source === 'similar') {
        telemetry.capture({
          event_type: 'poi_click',
          poi_id: poiId,
          metadata: { source: 'detail-panel' },
        });
      }
    },
    [detailPoiId, syncDetailUrl, telemetry],
  );
  useEffect(() => {
    openDetailRef.current = openDetail;
  }, [openDetail]);
  const openParkingDetail = useCallback(
    (poiId: string) => openDetail(poiId, 'parking'),
    [openDetail],
  );

  const closeDetail = useCallback(() => {
    setDetailPoiId(null);
    // Đóng panel phải HUỶ mục lịch sử mà openDetail đã đẩy, chứ không đẩy thêm
    // mục mới: đẩy thêm thì bấm Lùi rơi đúng vào mục ?poi= vừa rời, handler
    // popstate đọc lại id và bật panel lên — đúng cái bẫy mà comment ở handler
    // popstate tuyên bố đã tránh. Mỗi chu kỳ mở-đóng còn đẻ ra hai mục lịch sử.
    //
    // Chỉ lùi khi mục hiện tại DO CHÍNH TA đẩy (nhận ra qua history.state.poi).
    // Người vào thẳng bằng link chia sẻ ?poi= không có mục nào để lùi, gọi
    // back() là văng họ khỏi trang; trường hợp đó chỉ xoá tham số tại chỗ.
    if (typeof window !== 'undefined' && window.history.state?.poi)
      window.history.back();
    else syncDetailUrl(null, true);
  }, [syncDetailUrl]);

  // Chỉ đưa vị trí xuống hook khi người dùng ĐÃ cấp GPS. `position` khởi tạo
  // bằng DEFAULT_POSITION — một điểm hard-code ở trung tâm TP.HCM dùng để mồi
  // bản đồ, không phải chỗ người dùng đứng. Truyền nó đi thì panel in ra
  // "1,2 km · 15 phút đi bộ" đo từ một điểm không ai đứng, và nhánh trung thực
  // "Chưa biết khoảng cách — cần vị trí của bạn" trong panel thành mã chết.
  const {
    detail: poiDetail,
    photos: poiPhotos,
    loading: detailLoading,
    error: detailError,
    refreshDetail: refreshPoiDetail,
  } = usePoiDetail(
    API_BASE_URL,
    detailPoiId,
    hasLocationConsent ? position : null,
  );

  // Mở sẵn panel từ ?poi=<uuid> để link chia sẻ được. Chạy một lần lúc mount:
  // sau đó chính openDetail/closeDetail là nguồn sự thật của tham số này, đọc
  // lại URL nữa sẽ đá nhau.
  useEffect(() => {
    const shared = new URLSearchParams(window.location.search).get('poi');
    if (!shared || !UUID_PATTERN.test(shared)) return;
    // Đọc URLSearchParams — API trình duyệt, chỉ có sau mount.
    // oxlint-disable-next-line react/react-compiler
    setDetailPoiId(shared);
    flyToOnDetailRef.current = shared;
    telemetry.capture({
      event_type: 'poi_click',
      poi_id: shared,
      metadata: { source: 'detail-panel' },
    });
    // `telemetry` vào deps không đổi hành vi: nó là useMemo(..., []) nên
    // reference không bao giờ đổi giữa các lần render, effect vẫn chỉ chạy
    // đúng một lần lúc mount như trước — chỉ khai đúng cho react-hooks thay vì
    // bỏ deps rồi disable rule (bị chính react-compiler chặn ở nơi khác).
  }, [telemetry]);

  // Nút Lùi của trình duyệt. Thiếu popstate thì pushState ở trên biến nút Lùi
  // thành cái bẫy: URL lùi về nhưng panel vẫn mở, bấm tiếp là rời hẳn trang.
  useEffect(() => {
    const handlePopState = () => {
      const shared = new URLSearchParams(window.location.search).get('poi');
      setDetailPoiId(shared && UUID_PATTERN.test(shared) ? shared : null);
    };
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  useEffect(() => {
    if (!poiDetail || flyToOnDetailRef.current !== poiDetail.id) return;
    flyToOnDetailRef.current = null;
    mapRef.current?.flyTo({
      center: [poiDetail.longitude, poiDetail.latitude],
      zoom: 15.5,
      essential: true,
    });
  }, [poiDetail]);

  // PoiDetail là tập cha của Poi về mặt trường dữ liệu, nên chuyển kiểu ở đây
  // không phải bịa thêm số nào — điều kiện bắt buộc để dùng lại startNavigation
  // và toggleGeofence vốn nhận Poi.
  const detailAsPoi = useMemo<Poi | null>(() => {
    if (!poiDetail) return null;
    return {
      id: poiDetail.id,
      name: poiDetail.name,
      description: poiDetail.description,
      category: poiDetail.category,
      categoryLabel: poiDetail.categoryLabel,
      address: poiDetail.address,
      latitude: poiDetail.latitude,
      longitude: poiDetail.longitude,
      rating: poiDetail.rating,
      reviewCount: poiDetail.reviewCount,
      popularityScore: poiDetail.popularityScore,
      distanceMeters: poiDetail.distanceMeters ?? undefined,
      etaMinutes: poiDetail.etaMinutes,
      openNow: poiDetail.openingStatus?.openNow ?? null,
      closesInMinutes: poiDetail.openingStatus?.closesInMinutes ?? null,
      opensInMinutes: poiDetail.openingStatus?.opensInMinutes ?? null,
    };
  }, [poiDetail]);

  // Tuyến OSRM chỉ được tính cho selectedPoiId. Mở panel cho một POI khác (deep
  // link, địa điểm tương tự) thì chưa có tuyến nào của nó — trả null để panel
  // im lặng, thay vì gán nhầm thời gian đi tới một quán khác.
  const detailRouteSummary = useMemo<PoiRouteSummary | null>(
    () =>
      route && detailPoiId && route.poiId === detailPoiId
        ? {
            poiId: route.poiId,
            durationMinutes: route.durationMinutes,
            distanceMeters: route.distanceMeters,
            approximate: route.approximate,
          }
        : null,
    [route, detailPoiId],
  );

  const spotlightPoi = useCallback(
    (poi: Poi, source: string) => {
      const enriched: Poi = {
        ...poi,
        distanceMeters: poi.distanceMeters ?? distanceInMeters(position, poi),
      };
      setPois((current) => {
        const exists = current.some((item) => item.id === enriched.id);
        return exists
          ? current.map((item) => (item.id === enriched.id ? enriched : item))
          : [enriched, ...current];
      });
      telemetry.capture({
        event_type: 'poi_click',
        poi_id: enriched.id,
        metadata: { source },
      });
      selectedSinceRef.current = Date.now();
      setDirectionsPoiId((current) =>
        current === enriched.id ? current : null,
      );
      setSelectedPoiId(enriched.id);
      mapRef.current?.flyTo({
        center: [enriched.longitude, enriched.latitude],
        zoom: 15.5,
        essential: true,
      });
    },
    [position, telemetry],
  );

  /** POI thật (id là UUID) sau khi chọn từ dropdown autocomplete: điền tên vào
   *  ô tìm kiếm, bay bản đồ tới đó và mở panel chi tiết — không phải chạy lại
   *  toàn bộ tìm kiếm, vì người dùng đã chỉ đúng địa điểm họ muốn. */
  const selectSuggestion = useCallback(
    (suggestion: PoiSuggestion) => {
      setQuery(suggestion.name);
      setSuggestions([]);
      setSuggestionsOpen(false);
      setActiveSuggestionIndex(-1);
      spotlightPoi(
        {
          id: suggestion.id,
          name: suggestion.name,
          description: '',
          category: suggestion.categoryLabel,
          categoryLabel: suggestion.categoryLabel,
          address: suggestion.address,
          latitude: suggestion.latitude,
          longitude: suggestion.longitude,
          rating: null,
          reviewCount: 0,
          popularityScore: 0,
          distanceMeters: suggestion.distanceMeters ?? undefined,
        },
        'search-suggestion',
      );
      openDetail(suggestion.id, 'search-suggestion');
    },
    [spotlightPoi, openDetail],
  );

  // Debounce 250ms trước khi gọi /pois/suggest: tránh bắn một request mỗi phím
  // gõ. AbortController huỷ request đang bay khi người dùng gõ tiếp — không thì
  // một phản hồi chậm về sau có thể đè lên gợi ý của từ khóa mới hơn.
  useEffect(() => {
    const trimmed = query.trim();
    // Reset có chủ đích khi đổi từ khoá tìm kiếm.
    // oxlint-disable-next-line react/react-compiler
    setActiveSuggestionIndex(-1);
    if (trimmed.length < 2) {
      setSuggestions([]);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void (async () => {
        try {
          const params = new URLSearchParams({
            q: trimmed,
            limit: '8',
            lat: String(positionRef.current.latitude),
            lng: String(positionRef.current.longitude),
          });
          const response = await fetch(
            `${API_BASE_URL}/api/v1/pois/suggest?${params}`,
            { signal: controller.signal },
          );
          if (!response.ok) return;
          const data = (await response.json()) as PoiSuggestion[];
          setSuggestions(data);
          // Chỉ bung danh sách khi đang gõ trong ô tìm kiếm — từ khoá đến từ
          // giọng nói / lịch sử thì kết quả đã hiện, gợi ý chỉ che bản đồ.
          setSuggestionsOpen(
            document.activeElement?.getAttribute('aria-controls') ===
              'poi-suggestion-listbox',
          );
        } catch (error) {
          if ((error as Error)?.name !== 'AbortError') setSuggestions([]);
        }
      })();
    }, 250);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [query]);

  useEffect(() => {
    const unsubscribe = telemetry.subscribe(setTelemetryState);
    // drain() thay vì flush(): flush chỉ tiêu thụ MỘT lô 50 sự kiện, mà hàng đợi
    // có thể tới 500 — đóng tab sẽ mất tới 450 sự kiện.
    const flush = () => void telemetry.drain();
    window.addEventListener('pagehide', flush);
    return () => {
      unsubscribe();
      window.removeEventListener('pagehide', flush);
    };
  }, [telemetry]);

  useEffect(() => {
    // Chỉ gọi một lần lúc mount: nếu backend đang khởi động lại (vừa deploy,
    // gateway trả 502/503) thì chip danh mục kẹt ở bộ suy ra từ dữ liệu mẫu cho
    // tới khi người dùng tải lại trang. Thử lại với độ trễ tăng dần (~31 giây
    // tổng) cho lỗi mạng và 5xx; 4xx là lỗi thật, thử lại cũng vô ích.
    let cancelled = false;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    const load = async (attempt: number) => {
      let retryable = false;
      try {
        const response = await fetch(`${API_BASE_URL}/api/v1/categories`);
        if (response.ok) {
          const data = (await response.json()) as CategoryOption[];
          if (!cancelled) setCategories(data);
          return;
        }
        retryable = response.status >= 500;
      } catch {
        // API chưa sẵn sàng — tạm dùng category suy ra từ dữ liệu mẫu.
        retryable = true;
      }
      if (cancelled || !retryable || attempt >= CATEGORY_RETRY_DELAYS_MS.length) {
        return;
      }
      retryTimer = setTimeout(
        () => void load(attempt + 1),
        CATEGORY_RETRY_DELAYS_MS[attempt],
      );
    };
    void load(0);
    return () => {
      cancelled = true;
      clearTimeout(retryTimer);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/v1/trending?limit=6`);
        if (!response.ok) return;
        const data = (await response.json()) as TrendingResponse;
        if (!cancelled) setTrending(data);
      } catch {
        // Trending là tính năng nâng cao — im lặng bỏ qua khi backend chưa sẵn sàng.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!telemetryState.sessionId) return;
    let cancelled = false;
    void (async () => {
      try {
        const params = new URLSearchParams({
          lat: String(position.latitude),
          lng: String(position.longitude),
          session_id: telemetryState.sessionId,
          limit: '6',
        });
        // Header để backend nhận ra chủ sở hữu (tài khoản hoặc phiên) và biết
        // vùng nào người dùng đã đi qua — xem `exploration.mix_unexplored`.
        const response = await fetch(
          `${API_BASE_URL}/api/v1/recommendations?${params}`,
          { headers: authToken ? { Authorization: `Bearer ${authToken}` } : undefined },
        );
        if (!response.ok) return;
        const data = (await response.json()) as RecommendationsResponse;
        if (!cancelled) setRecommendations(data.results);
      } catch {
        // Cá nhân hóa là tính năng nâng cao — im lặng bỏ qua khi lỗi.
      }
    })();
    return () => {
      cancelled = true;
    };
    // Mở thêm ô mới thì danh sách "vùng chưa tới" đổi theo.
  }, [telemetryState.sessionId, position.latitude, position.longitude, authToken, exploredCellCount]);

  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: MAP_STYLE_URL || OSM_RASTER_STYLE,
      center: [DEFAULT_POSITION.longitude, DEFAULT_POSITION.latitude],
      zoom: 14,
      attributionControl: false,
    });
    map.addControl(
      new maplibregl.NavigationControl({ showCompass: false }),
      'bottom-right',
    );
    map.addControl(
      new maplibregl.AttributionControl({ compact: true }),
      'bottom-left',
    );
    mapRef.current = map;
    const pendingCenter = pendingLocationCenterRef.current;
    if (pendingCenter) {
      map.jumpTo({
        center: [pendingCenter.longitude, pendingCenter.latitude],
        zoom: 14,
      });
      pendingLocationCenterRef.current = null;
    }

    // MapLibre chỉ phát `load` khi MỌI source trong style báo đã tải xong. Style
    // Streets của MapTiler có source `maptiler_attribution` kiểu vector nhưng không
    // url, không tiles — nó chỉ tồn tại để mang dòng ghi công — nên source đó không
    // bao giờ chuyển sang trạng thái loaded, `isStyleLoaded()` vĩnh viễn false và
    // `load` KHÔNG BAO GIỜ phát. Toàn bộ lớp POI, cụm và handler click nằm trong đây
    // nên bản đồ sẽ không có chấm nào, bấm cũng không ăn. `styledata` phát ngay khi
    // style được parse xong — đủ điều kiện để addSource/addLayer — và không phụ thuộc
    // vào việc tile tải được hay không.
    const initMapLayers = () => {
      map.on('styleimagemissing', (event) => {
        if (!event.id.startsWith(POI_ICON_PREFIX) || map.hasImage(event.id)) return;
        const image = renderPoiIcon(
          categoryChipIcon(event.id.slice(POI_ICON_PREFIX.length)),
        );
        if (image) map.addImage(event.id, image, { pixelRatio: POI_ICON_PIXEL_RATIO });
      });

      map.addSource('pois', {
        type: 'geojson',
        data: poisToFeatureCollection(poisRef.current),
        cluster: true,
        clusterRadius: 50,
        clusterMaxZoom: 14,
      });

      // Sương mù — thêm trước mọi lớp khác nên nằm ngay trên nền bản đồ, dưới
      // vành H3, tuyến đường và POI: sương che phố, không che thứ người dùng bấm.
      map.addSource('fog', { type: 'geojson', data: fogDataRef.current.fog });
      map.addSource('explored', { type: 'geojson', data: fogDataRef.current.explored });
      map.addLayer({
        id: 'fog-fill',
        type: 'fill',
        source: 'fog',
        paint: { 'fill-color': '#0b1220', 'fill-opacity': 0.62 },
      });
      map.addLayer({
        id: 'explored-edge',
        type: 'line',
        source: 'explored',
        paint: { 'line-color': '#34d399', 'line-width': 2.5, 'line-blur': 1.5, 'line-opacity': 0.9 },
      });

      // Vành hexagon H3 — vùng mà kênh 2 thật sự đã quét. Thêm ĐẦU TIÊN nên
      // nằm dưới cùng: nó là nền ngữ cảnh, không được che tuyến đường lẫn POI.
      map.addSource('h3-ring', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      });
      map.addLayer({
        id: 'h3-ring-fill',
        type: 'fill',
        source: 'h3-ring',
        paint: { 'fill-color': '#0ea5e9', 'fill-opacity': 0.07 },
      });
      map.addLayer({
        id: 'h3-ring-outline',
        type: 'line',
        source: 'h3-ring',
        paint: {
          'line-color': '#0ea5e9',
          'line-width': 1.5,
          'line-opacity': 0.55,
          'line-dasharray': [2, 2],
        },
      });

      // Tuyến đường thêm TRƯỚC các lớp POI để nó nằm DƯỚI marker — thứ tự
      // addLayer quyết định cái gì che cái gì trong MapLibre, và một đường kẻ
      // dày 6 px vẽ đè lên chấm POI sẽ che mất đúng cái đích đến.
      map.addSource('route', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      });
      // Hai lớp chồng nhau: một viền trắng dày ở dưới, một nét màu mảnh ở trên.
      // Đường đơn sắc chìm nghỉm trên nền bản đồ nhiều màu của MapTiler.
      map.addLayer({
        id: 'route-casing',
        type: 'line',
        source: 'route',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
          'line-color': '#ffffff',
          'line-width': 9,
          'line-opacity': 0.9,
        },
      });
      map.addLayer({
        id: 'route-line',
        type: 'line',
        source: 'route',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': SELECTED_POINT_COLOR, 'line-width': 5 },
      });

      map.addLayer({
        id: 'clusters',
        type: 'circle',
        source: 'pois',
        filter: ['has', 'point_count'],
        paint: {
          'circle-color': [
            'step',
            ['get', 'point_count'],
            '#6ee7b7',
            10,
            '#34d399',
            30,
            '#059669',
          ],
          'circle-radius': ['step', ['get', 'point_count'], 16, 10, 20, 30, 26],
          'circle-stroke-width': 3,
          'circle-stroke-color': '#ffffff',
        },
      });
      map.addLayer({
        id: 'cluster-count',
        type: 'symbol',
        source: 'pois',
        filter: ['has', 'point_count'],
        layout: {
          'text-field': ['get', 'point_count_abbreviated'],
          // Mặc định của MapLibre là Open Sans Regular — font server demo không có
          // font đó (404). Noto Sans Regular có ở cả demo lẫn MapTiler.
          'text-font': ['Noto Sans Regular'],
          'text-size': 12,
        },
        paint: { 'text-color': '#ffffff' },
      });
      map.addLayer({
        id: 'unclustered-point',
        type: 'circle',
        source: 'pois',
        filter: ['!', ['has', 'point_count']],
        paint: {
          // Dưới zoom 15 không có icon (xem 'unclustered-icon') nên thu chấm
          // lại cho đỡ rối; từ 15 trở lên phóng to cho icon đủ chỗ.
          'circle-radius': ['step', ['zoom'], 8, POI_ICON_MIN_ZOOM, 13],
          'circle-stroke-width': 2.5,
          'circle-stroke-color': '#ffffff',
          'circle-color': pointColorExpression(selectedPoiIdRef.current),
        },
      });
      // Icon loại địa điểm vẽ đè lên chấm màu, chỉ khi đã zoom đủ gần — xa hơn
      // thì khu trung tâm dày đặc icon, nhìn rối mà cũng không đọc nổi. Không
      // bắt click riêng: handler của 'unclustered-point' vẫn nhận cú bấm vì
      // chấm nằm ngay bên dưới.
      map.addLayer({
        id: 'unclustered-icon',
        type: 'symbol',
        source: 'pois',
        minzoom: POI_ICON_MIN_ZOOM,
        filter: ['!', ['has', 'point_count']],
        layout: {
          'icon-image': ['get', 'icon'],
          'icon-allow-overlap': true,
          'icon-ignore-placement': true,
        },
      });

      // Chế độ chọn vị trí: cú chạm này thuộc về trợ lý, không phải chọn POI.
      // Xoá ref ở tick SAU: handler theo lớp ('clusters', 'unclustered-point')
      // chạy trong cùng lượt sự kiện và phải còn thấy ref để tự bỏ qua.
      map.on('click', (event) => {
        const pick = mapPickRef.current;
        if (!pick) return;
        pick(event.lngLat.lat, event.lngLat.lng);
        setTimeout(() => {
          if (mapPickRef.current === pick) mapPickRef.current = null;
          setMapPicking(false);
        }, 0);
      });

      // Người dùng tự kéo bản đồ thì thôi bám theo — nếu không, lần ping kế tiếp
      // giật khung nhìn về lại chấm xanh ngay lúc họ đang xem chỗ khác.
      // `originalEvent` chỉ có khi là thao tác thật, easeTo từ code thì không.
      map.on('dragstart', (event) => {
        if (event.originalEvent) setFollowMe(false);
      });

      map.on('click', 'clusters', (event) => {
        if (mapPickRef.current) return;
        const features = map.queryRenderedFeatures(event.point, {
          layers: ['clusters'],
        });
        const clusterId = features[0]?.properties?.cluster_id as
          | number
          | undefined;
        const source = map.getSource('pois') as GeoJSONSource | undefined;
        if (clusterId === undefined || !source) return;
        void source
          .getClusterExpansionZoom(clusterId)
          .then((zoom) => {
            const geometry = features[0].geometry as GeoJSON.Point;
            map.easeTo({
              center: geometry.coordinates as [number, number],
              zoom,
            });
          })
          .catch(() => undefined);
      });

      map.on('click', 'unclustered-point', (event) => {
        if (mapPickRef.current) return;
        const feature = event.features?.[0];
        const poiId = feature?.properties?.id as string | undefined;
        const poi = poisRef.current.find((item) => item.id === poiId);
        if (!poi) return;
        // CHỈ chọn (thẻ "Đang chọn" + tuyến đường), KHÔNG mở panel chi tiết:
        // panel che gần nửa bản đồ và kéo theo hai yêu cầu mạng, bung nó ra
        // theo mỗi cú bấm marker là quá tay. Muốn xem chi tiết thì bấm "Xem
        // chi tiết" trên thẻ, hoặc bấm lần nữa vào ghim đỏ đang chọn.
        focusPoiRef.current(poi, 'map');
      });

      for (const layer of ['clusters', 'unclustered-point']) {
        map.on('mouseenter', layer, () => {
          map.getCanvas().style.cursor = 'pointer';
        });
        map.on('mouseleave', layer, () => {
          map.getCanvas().style.cursor = '';
        });
      }

      mapLoadedRef.current = true;
      loadAreaPois();
    };

    // Nạp POI cho vùng đang nhìn. Bán kính lấy ~nửa đường chéo viewport (tâm →
    // góc đông bắc) nên zoom xa thì quét rộng, zoom gần thì quét hẹp; kẹp theo
    // giới hạn của API (100..50000 m). Chỉ đổ vào areaPois — không đụng danh
    // sách kết quả tìm kiếm.
    const loadAreaPois = () => {
      const center = map.getCenter();
      const radiusMeters = Math.min(
        50_000,
        Math.max(
          300,
          Math.round(center.distanceTo(map.getBounds().getNorthEast())),
        ),
      );
      const params = new URLSearchParams({
        lat: center.lat.toFixed(6),
        lng: center.lng.toFixed(6),
        radius: String(radiusMeters),
        limit: '100',
      });
      // X-Session-ID để badge "người quanh đây" không đếm chính người đang xem.
      fetch(`${API_BASE_URL}/api/pois/nearby?${params}`, {
        headers: { 'X-Session-ID': telemetry.sessionId },
      })
        .then((response) =>
          response.ok ? (response.json() as Promise<Poi[]>) : Promise.reject(),
        )
        // distanceMeters của API tính từ TÂM BẢN ĐỒ (tham số lat/lng ở trên) —
        // hiển thị lên thẻ sẽ thành "cách 200 m" trong khi người dùng đứng cách
        // 5 km. Tính lại từ vị trí thiết bị; đọc qua ref vì closure này đăng ký
        // một lần lúc mount, còn vị trí thì đổi khi người dùng bật GPS.
        .then((data) =>
          setAreaPois(
            data.map((poi) => ({
              ...poi,
              distanceMeters: distanceInMeters(positionRef.current, {
                latitude: poi.latitude,
                longitude: poi.longitude,
              }),
            })),
          ),
        )
        // Backend chưa chạy thì thôi — bản đồ vẫn còn chấm của lần tìm kiếm.
        .catch(() => undefined);
    };
    // Debounce: moveend bắn cả khi easeTo/flyTo kết thúc và khi người dùng thả
    // tay giữa chuỗi thao tác kéo — không gõ backend theo từng cú hích.
    let moveTimer: ReturnType<typeof setTimeout> | undefined;
    const handleMoveEnd = () => {
      clearTimeout(moveTimer);
      moveTimer = setTimeout(loadAreaPois, 350);
    };
    map.on('moveend', handleMoveEnd);

    if (map.isStyleLoaded()) initMapLayers();
    else void map.once('styledata', initMapLayers);

    return () => {
      clearTimeout(moveTimer);
      map.remove();
      mapRef.current = null;
      mapLoadedRef.current = false;
    };
    // `telemetry` là singleton (useMemo []) — có trong deps cũng không dựng lại bản đồ.
  }, [telemetry]);

  // Panel chi tiết là z-30 và phủ trọn mép phải, trong khi cặp nút +/- của
  // MapLibre chỉ có z-index:2 — mà không lớp nào ở giữa tạo stacking context,
  // nên panel nuốt gọn hai nút: mở panel ra là chỉ còn lăn chuột/pinch mới phóng
  // to được. Đẩy góc control sang trái đúng bề rộng panel chứ KHÔNG nâng
  // z-index: nâng z-index thì hai nút lại nổi lên TRÊN MẶT panel và che nội dung
  // bên trong. Ba góc còn lại đều đã có người ở nên cũng không dời góc được.
  //
  // Ghi thẳng style vào DOM chứ không viết rule trong globals.css: maplibre-gl.css
  // nạp KHÔNG layer nên luôn thắng utility Tailwind (nằm trong @layer utilities) —
  // đúng cái bẫy đã ghi ở comment của .map-canvas-host trong globals.css.
  useEffect(() => {
    const corner = mapContainerRef.current?.querySelector<HTMLElement>(
      '.maplibregl-ctrl-bottom-right',
    );
    if (!corner) return;
    if (!detailPoiId) {
      corner.style.right = '';
      return;
    }
    // Phải bám ĐÚNG breakpoint sm: của panel (w-[92%] -> sm:w-[420px]). Lệch số
    // ở đây là nút zoom chui lại xuống dưới panel mà không ai thấy.
    const wide = window.matchMedia('(min-width: 40rem)');
    const apply = () => {
      corner.style.right = wide.matches ? '420px' : '92%';
    };
    apply();
    wide.addEventListener('change', apply);
    return () => {
      wide.removeEventListener('change', apply);
      corner.style.right = '';
    };
  }, [detailPoiId]);

  // Vẽ lớp của trợ lý: một đường nét đứt (tuyến tour) + marker đánh số. So
  // khoá nội dung để không fitBounds lại mỗi lần component con dựng object mới
  // với cùng dữ liệu (ví dụ lúc người dùng đang gõ tên bạn bè).
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoadedRef.current) return;
    const key = assistantOverlay ? JSON.stringify(assistantOverlay) : '';
    if (key === assistantOverlayKeyRef.current) return;
    assistantOverlayKeyRef.current = key;

    for (const marker of assistantMarkersRef.current) marker.remove();
    assistantMarkersRef.current = [];

    if (!map.getSource('assistant-line')) {
      map.addSource('assistant-line', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      });
      map.addLayer({
        id: 'assistant-line-casing',
        type: 'line',
        source: 'assistant-line',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': '#ffffff', 'line-width': 8, 'line-opacity': 0.9 },
      });
      map.addLayer({
        id: 'assistant-line',
        type: 'line',
        source: 'assistant-line',
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': '#7c3aed', 'line-width': 4, 'line-dasharray': [1.4, 1] },
      });
    }
    (map.getSource('assistant-line') as GeoJSONSource).setData(
      assistantOverlay?.line
        ? { type: 'Feature', geometry: assistantOverlay.line, properties: {} }
        : { type: 'FeatureCollection', features: [] },
    );
    if (!assistantOverlay) return;

    const TONE_COLORS = { stop: '#7c3aed', person: '#0284c7', result: '#f97316' } as const;
    const bounds = new maplibregl.LngLatBounds();
    for (const point of assistantOverlay.points) {
      const dot = document.createElement('button');
      dot.type = 'button';
      dot.className =
        'grid size-7 place-items-center rounded-full border-2 border-white text-[11px] font-bold text-white shadow-md';
      dot.style.background = TONE_COLORS[point.tone];
      dot.textContent = point.label;
      dot.title = point.title;
      dot.setAttribute('aria-label', point.title);
      const poiId = point.poiId;
      if (poiId) {
        dot.addEventListener('click', (event) => {
          event.stopPropagation();
          openDetailRef.current(poiId, 'assistant');
        });
      }
      assistantMarkersRef.current.push(
        new maplibregl.Marker({ element: dot }).setLngLat([point.longitude, point.latitude]).addTo(map),
      );
      bounds.extend([point.longitude, point.latitude]);
    }
    const line = assistantOverlay.line;
    const coordinates = line?.type === 'MultiLineString' ? line.coordinates.flat() : (line?.coordinates ?? []);
    for (const coordinate of coordinates) bounds.extend(coordinate);
    if (!bounds.isEmpty()) {
      map.fitBounds(bounds, { padding: 80, maxZoom: 16, duration: 600 });
    }
  }, [assistantOverlay]);

  // Lớp địa danh nổi bật: luôn có trên bản đồ (bật/tắt ở thẻ "Địa danh gần bạn"),
  // kể cả khi chưa mở trợ lý. Ẩn khi trợ lý đang vẽ lớp của nó — màn Săn địa danh
  // vẽ lại đúng các địa danh này với nhãn ?/✓, vẽ hai lần là chồng marker.
  // Khoá theo (id, đã khám phá) để không dựng lại marker mỗi lần GPS nhích.
  const landmarksRef = useRef(nearbyLandmarks.landmarks);
  useEffect(() => {
    landmarksRef.current = nearbyLandmarks.landmarks;
  }, [nearbyLandmarks.landmarks]);
  const landmarkPinKey = nearbyLandmarks.landmarks
    .map((place) => `${place.poiId}:${place.discovered ? 1 : 0}`)
    .sort()
    .join('|');
  const landmarkLayerVisible = landmarkLayerOn && assistantOverlay === null;
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    for (const marker of landmarkMarkersRef.current) marker.remove();
    landmarkMarkersRef.current = [];
    if (!landmarkLayerVisible) return;

    for (const place of landmarksRef.current) {
      const pin = document.createElement('button');
      pin.type = 'button';
      pin.className = cn(
        'grid size-7 place-items-center rounded-full border-2 bg-white text-sm shadow-md transition-transform hover:scale-110',
        place.discovered ? 'border-emerald-500' : 'border-amber-500',
      );
      pin.textContent = place.discovered ? '✓' : '🏛️';
      const label = place.discovered ? place.name : `${place.name} · địa danh chưa khám phá`;
      pin.title = label;
      pin.setAttribute('aria-label', label);
      pin.addEventListener('click', (event) => {
        event.stopPropagation();
        openDetailRef.current(place.poiId, 'landmark');
      });
      landmarkMarkersRef.current.push(
        new maplibregl.Marker({ element: pin }).setLngLat([place.longitude, place.latitude]).addTo(map),
      );
    }
  }, [landmarkPinKey, landmarkLayerVisible]);

  useEffect(() => {
    const canvas = mapRef.current?.getCanvas();
    if (canvas) canvas.style.cursor = mapPicking ? 'crosshair' : '';
  }, [mapPicking]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapLoadedRef.current) return;
    const source = map.getSource('pois') as GeoJSONSource | undefined;
    if (!source) return;
    source.setData(poisToFeatureCollection(visiblePois));
    map.setPaintProperty(
      'unclustered-point',
      'circle-color',
      pointColorExpression(selectedPoiId),
    );
  }, [visiblePois, selectedPoiId]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    userMarkerRef.current?.remove();
    const userDot = document.createElement('div');
    userDot.className =
      'h-5 w-5 rounded-full border-[3px] border-white bg-sky-500 shadow-[0_0_0_5px_rgb(14_165_233/22%)]';
    userDot.setAttribute('aria-label', 'Vị trí của bạn');
    userMarkerRef.current = new maplibregl.Marker({ element: userDot })
      .setLngLat([position.longitude, position.latitude])
      .addTo(map);
  }, [position]);

  useEffect(() => {
    followRef.current = followMe;
  }, [followMe]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !followMe || !isWatching) return;
    map.easeTo({
      center: [position.longitude, position.latitude],
      // Giữ mức zoom người dùng đã chọn nếu đã đủ gần để thấy đường.
      zoom: Math.max(map.getZoom(), 16),
      duration: 1000,
      essential: true,
    });
  }, [position, followMe, isWatching]);

  // Ghim pin đỏ lên POI đang chọn. Tạo mới thay vì setLngLat trên marker cũ:
  // bỏ chọn (selectedPoi = null) thì pin phải BIẾN MẤT, mà một marker sống dai
  // không có API "ẩn" — remove rồi tạo lại là đường đơn giản và đủ rẻ vì thao
  // tác chọn không xảy ra hàng chục lần mỗi giây.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    selectedMarkerRef.current?.remove();
    selectedMarkerRef.current = null;
    if (!selectedPoi) return;
    const marker = new maplibregl.Marker({ color: SELECTED_PIN_COLOR })
      .setLngLat([selectedPoi.longitude, selectedPoi.latitude])
      .addTo(map);
    const element = marker.getElement();
    element.style.cursor = 'pointer';
    element.setAttribute('aria-label', selectedPoi.name);
    // Pin là overlay HTML nên nó CHE chấm POI bên dưới — không bắt click ở đây
    // thì bấm vào đúng địa điểm đang chọn không mở được panel chi tiết nữa.
    // stopPropagation để cú bấm không lọt xuống bản đồ phía sau.
    element.addEventListener('click', (event) => {
      event.stopPropagation();
      openDetailRef.current(selectedPoi.id, 'map');
    });
    selectedMarkerRef.current = marker;
  }, [selectedPoi]);

  // Backend không trả lời: hiện dữ liệu mẫu. Tách khỏi khối `catch` của
  // runSearch vì callback bắt biến khai báo TRONG `catch` làm React Compiler của
  // oxlint vấp lỗi nội bộ ("consistently local or context references") và CI
  // lint đỏ.
  function showSampleFallback(
    searchOrigin: Position,
    searchQuery: string,
    searchRadius: number,
    category: string | null,
  ) {
    const fallback = enrichSamplePois(
      searchOrigin,
      searchQuery,
      searchRadius,
      category,
    );
    // Dữ liệu mẫu không thuộc lần tìm kiếm nào; xoá ngữ cảnh để click sau đó
    // không bị đóng dấu request_id cũ.
    lastSearchRef.current = null;
    setPois(fallback);
    // Xoá metadata: giữ lại thì bảng tín hiệu vẫn khoe "truy xuất đa kênh"
    // trong khi màn hình đang là 6 POI mẫu bịa sẵn.
    setSearchMeta(null);
    setDirectionsPoiId(null);
    setSelectedPoiId((prev) =>
      prev && fallback.some((poi) => poi.id === prev) ? prev : null,
    );
    setStatus(
      `${fallback.length} kết quả mẫu · khởi động backend để dùng PostGIS`,
    );
    setGatewayStatus('Gateway ngoại tuyến · dùng dữ liệu mẫu');
    fitMapToResults(mapRef.current, searchOrigin, fallback);
  }

  // `origin` cho phép tìm kiếm tại một toạ độ CHƯA kịp vào state. setPosition là
  // bất đồng bộ, nên gọi runSearch ngay sau nó vẫn đọc được `position` cũ trong
  // closure này và sẽ hỏi backend quanh vị trí trước đó.
  async function runSearch(
    searchQuery: string,
    category: string | null,
    origin?: Position,
    // Cùng lý do với `origin`: đổi bán kính rồi tìm lại ngay thì `radius` trong
    // closure này vẫn là giá trị cũ.
    searchRadius: number = radius,
  ) {
    const searchOrigin = origin ?? position;
    // Có `origin` nghĩa là toạ độ vừa lấy từ GPS sau khi người dùng bấm đồng ý;
    // `hasLocationConsent` lúc này còn là giá trị cũ của lần render trước.
    const consent = hasLocationConsent || origin !== undefined;
    setIsLoading(true);
    telemetry.capture({
      event_type: 'search',
      query: searchQuery.trim(),
      location: consent ? searchOrigin : undefined,
      location_consent: consent,
      metadata: {
        radius_meters: searchRadius,
        source: 'search-form',
        category: category ?? undefined,
      },
    });
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/search`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Session-ID': telemetry.sessionId,
        },
        body: JSON.stringify({
          query: searchQuery.trim(),
          latitude: searchOrigin.latitude,
          longitude: searchOrigin.longitude,
          radius: searchRadius,
          limit: 50,
          session_id: telemetry.sessionId,
          category: category ?? undefined,
        }),
      });
      if (!response.ok) throw new Error('Backend chưa sẵn sàng');
      const data = (await response.json()) as ContextualSearchResponse;
      setPois(data.results);
      // Bắn lô impression NGAY TẠI ĐÂY, từ data.results — không dùng useEffect
      // theo [pois] và không đọc state `pois`. Lý do: pois còn được set từ ba
      // luồng khác (POI mẫu lúc mount, nhánh catch offline, sau khi lấy GPS)
      // vốn không có requestId và mang id giả 'poi-001'…; ghi chúng vào
      // ingestion_events sẽ tạo rác mà mọi JOIN với bảng pois lặng lẽ bỏ qua.
      // Gọi thẳng ở đây cũng tránh việc React Strict Mode chạy effect hai lần.
      // Cập nhật ngữ cảnh KỂ CẢ khi 0 kết quả: nếu không, ngữ cảnh của lần tìm
      // TRƯỚC còn nguyên, và cú click kế tiếp bị đóng dấu request_id của một
      // lần tìm kiếm đã bị thay thế — sinh nhãn positive giả.
      const isNewSearch = lastSearchRef.current?.requestId !== data.requestId;
      if (isNewSearch) {
        lastSearchRef.current = {
          requestId: data.requestId,
          ranks: new Map(
            data.results.map((poi, index) => [poi.id, poi.rank ?? index]),
          ),
        };
      }
      if (isNewSearch && data.results.length) {
        telemetry.captureBatch(
          data.results.map((poi, index) => ({
            event_type: 'poi_impression' as const,
            poi_id: poi.id,
            metadata: {
              request_id: data.requestId,
              query: data.query,
              // rank do SERVER gán (sau diversify). Không suy từ chỉ số mảng:
              // spotlightPoi chèn POI vào đầu mảng nên client lệch một bậc.
              rank: poi.rank ?? index,
            },
          })),
        );
      }
      // KHÔNG tự chọn kết quả nào: thẻ "Đang chọn" chỉ hiện khi người dùng bấm.
      // Chỉ giữ lựa chọn cũ nếu POI đó vẫn còn trong kết quả mới.
      setDirectionsPoiId(null);
      setSelectedPoiId((prev) =>
        prev && data.results.some((poi) => poi.id === prev) ? prev : null,
      );
      setGatewayStatus(`Gateway OK · ${data.requestId.slice(0, 8)}`);
      if (data.parsedLocation.matched && data.parsedLocation.bestMatch) {
        setParserStatus(
          `${data.parsedLocation.bestMatch.canonicalName} · ${Math.round(data.parsedLocation.bestMatch.confidence * 100)}%`,
        );
        mapRef.current?.flyTo({
          center: [data.searchCenter.longitude, data.searchCenter.latitude],
          zoom: 14.5,
          essential: true,
        });
      } else {
        setParserStatus(
          data.parsedLocation.locationText
            ? 'Không nhận ra địa danh'
            : 'Dùng tọa độ thiết bị',
        );
        fitMapToResults(mapRef.current, searchOrigin, data.results);
      }
      setSearchMeta({
        backend: data.retrievalBackend,
        geoFilter: data.geoFilter ?? null,
        ranker: data.ranker,
      });
      // Chữ "PostGIS" từng bị HARD-CODE ở đây, bất kể backend thật đã chạy gì.
      // Người dùng nhìn thấy "kết quả từ PostGIS" trong khi hệ thống đang chạy
      // truy xuất đa kênh qua OpenSearch — giao diện nói sai về kiến trúc của
      // chính nó, ngay dòng chữ dưới ô tìm kiếm. Cùng loại lỗi mà trường
      // `retrievalBackend` được thêm vào để phơi ra, chỉ là lần này chỗ hỏng
      // nằm ở phía hiển thị.
      const duong =
        data.retrievalBackend === 'opensearch'
          ? 'truy xuất đa kênh'
          : 'PostGIS dự phòng';
      setStatus(`${data.results.length} kết quả · ${duong}`);
    } catch {
      showSampleFallback(searchOrigin, searchQuery, searchRadius, category);
    } finally {
      setIsLoading(false);
    }
  }

  async function searchNearby() {
    await runSearch(query, selectedCategory);
  }

  function toggleCategory(category: string) {
    const next = selectedCategory === category ? null : category;
    setSelectedCategory(next);
    void runSearch(query, next);
  }

  function requestCurrentLocation() {
    if (!navigator.geolocation) {
      setStatus('Trình duyệt không hỗ trợ định vị');
      return;
    }
    setStatus('Đang lấy vị trí của bạn…');

    const acceptLocation = (
      { coords }: GeolocationPosition,
      source: 'gps' | 'network',
    ) => {
      // Máy bàn/laptop không có GPS: trình duyệt trả vị trí đoán theo IP với
      // accuracy hàng chục-trăm km. Tin tọa độ đó là bay bản đồ về một huyện
      // ngẫu nhiên và tìm kiếm 0 kết quả — tệ hơn hẳn đứng yên ở trung tâm
      // TP.HCM. Quá ngưỡng thì coi như KHÔNG định vị được, nói rõ sai số.
      if (coords.accuracy > MAX_USABLE_ACCURACY_METERS) {
        setGpsStatus(
          `Vị trí quá mờ (±${Math.round(coords.accuracy / 1000)} km) · dùng vị trí mặc định`,
        );
        setStatus(
          'Máy không định vị chính xác được — đang dùng trung tâm TP.HCM',
        );
        return false;
      }
      const nextPosition = {
        latitude: coords.latitude,
        longitude: coords.longitude,
      };
      positionRef.current = nextPosition;
      setPosition(nextPosition);
      setPositionAccuracy(source === 'gps' ? coords.accuracy : null);
      setHasLocationConsent(true);
      setGpsStatus(
        `${source === 'gps' ? 'GPS' : 'Vị trí mạng'} chính xác ±${Math.round(coords.accuracy)} m`,
      );
      setStatus('Đã dùng vị trí hiện tại của bạn');
      try {
        window.localStorage.setItem(
          LAST_LOCATION_STORAGE_KEY,
          JSON.stringify({
            ...nextPosition,
            accuracy: coords.accuracy,
            savedAt: Date.now(),
          }),
        );
      } catch {
        // Chế độ riêng tư có thể chặn localStorage; GPS vẫn dùng bình thường.
      }
      telemetry.capture({
        event_type: 'location_ping',
        location: { ...nextPosition, accuracy_meters: coords.accuracy },
        location_consent: true,
        metadata: {
          source: 'browser-geolocation',
          high_accuracy: source === 'gps',
        },
      });
      const map = mapRef.current;
      if (map) {
        map.flyTo({
          center: [nextPosition.longitude, nextPosition.latitude],
          zoom: 14,
          essential: true,
        });
        pendingLocationCenterRef.current = null;
      } else {
        pendingLocationCenterRef.current = nextPosition;
      }
      // Trước đây chỗ này nạp SAMPLE_POIS — 6 địa điểm hard-code quanh Quận 1.
      // Người dùng ở Thủ Đức hay Hà Nội bấm "Vị trí của tôi" vẫn nhận đúng 6 POI
      // đó, kèm khoảng cách tính từ toạ độ thật tới chúng: giao diện trông như
      // đang chạy, số liệu thì vô nghĩa. Hỏi lại backend quanh toạ độ mới, truyền
      // thẳng nextPosition vì setPosition chưa kịp vào state.
      void runSearch(query, selectedCategory, nextPosition);
      return true;
    };

    const handleFinalError = (error: GeolocationPositionError) => {
      if (error.code === error.PERMISSION_DENIED) {
        setGpsStatus('Quyền vị trí đang bị chặn trong trình duyệt');
        setStatus('Vị trí đang bị chặn — bật lại trong cài đặt trình duyệt');
      } else {
        setGpsStatus('Không lấy được vị trí từ thiết bị hoặc mạng');
        setStatus(
          'Không thể lấy vị trí — đang dùng vị trí gần nhất hoặc trung tâm TP.HCM',
        );
      }
    };

    navigator.geolocation.getCurrentPosition(
      (location) => {
        // Có GPS thật thì tự theo dõi liên tục luôn: trên điện thoại lúc di
        // chuyển, chấm xanh đứng yên vì không ai bấm "Theo dõi vị trí".
        if (acceptLocation(location, 'gps')) startWatching();
      },
      (error) => {
        if (error.code === error.PERMISSION_DENIED) {
          handleFinalError(error);
          return;
        }
        // Laptop thường không có cảm biến GPS. Nếu độ chính xác cao timeout,
        // thử Wi-Fi/IP cache để vẫn có tâm gần người dùng thay vì cố định Q.1.
        setGpsStatus('GPS chưa phản hồi · đang thử vị trí mạng…');
        navigator.geolocation.getCurrentPosition(
          (location) => {
            acceptLocation(location, 'network');
          },
          handleFinalError,
          {
            enableHighAccuracy: false,
            timeout: 12_000,
            maximumAge: 5 * 60_000,
          },
        );
      },
      { enableHighAccuracy: true, timeout: 15_000, maximumAge: 60_000 },
    );
  }
  // `requestCurrentLocation` đọc `query`/`selectedCategory`/`runSearch` — cả
  // ba đổi tham chiếu mỗi render, nên hàm cũng vậy. Giữ bản MỚI NHẤT qua ref
  // (cập nhật trong effect, không phải ngay thân component — cùng lý do với
  // use-proximity.ts) để effect tự-định-vị lúc mount ở dưới gọi được đúng bản
  // mới nhất mà không phải liệt kê nó (hay runSearch/query/selectedCategory)
  // vào deps — tránh việc useCallback đòi liệt kê chính xác toàn bộ closure
  // của runSearch, một hàm dài, dễ sót một biến và tạo stale closure còn tệ
  // hơn cảnh báo lint.
  const requestCurrentLocationRef = useRef(requestCurrentLocation);
  useEffect(() => {
    requestCurrentLocationRef.current = requestCurrentLocation;
  });

  // Cùng lý do với requestCurrentLocationRef: runSearch là hàm dài đổi tham
  // chiếu mỗi render, giữ bản mới nhất qua ref.
  const runSearchRef = useRef(runSearch);
  useEffect(() => {
    runSearchRef.current = runSearch;
  });

  // Vị trí MÔ PHỎNG: máy tính không có GPS mà vẫn phải trình diễn được Săn địa
  // danh / dẫn đường. Không gửi location_ping (không phải vị trí thật của ai) và
  // ghi rõ trên trạng thái để không ai nhầm với GPS.
  const simulatePosition = useCallback(
    (latitude: number, longitude: number) => {
      const nextPosition = { latitude, longitude };
      setPosition(nextPosition);
      setPositionAccuracy(null);
      setGpsStatus('Vị trí mô phỏng (trình diễn) · không phải GPS');
      setStatus('Đang dùng vị trí mô phỏng đặt trên bản đồ');
      mapRef.current?.flyTo({ center: [longitude, latitude], zoom: 16, essential: true });
      void runSearchRef.current(query, selectedCategory, nextPosition);
    },
    [query, selectedCategory],
  );

  // Alt+V bật/tắt chế độ giọng nói ở bất cứ đâu trên trang — người không nhìn
  // thấy màn hình không phải đi tìm nút.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.altKey && (event.key === 'v' || event.key === 'V')) {
        event.preventDefault();
        setVoiceSearchOpen(false);
        setVoiceOpen((value) => !value);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  // Tự hỏi vị trí NGAY KHI MỞ TRANG thay vì đứng ở Quận 1 chờ người dùng bấm
  // "Vị trí của tôi". Trình duyệt tự lo phần đồng ý: lần đầu nó hiện hộp xin
  // quyền, đã cho phép từ trước thì vào thẳng, đã chặn thì rơi vào nhánh lỗi
  // của requestCurrentLocation và bản đồ đứng yên ở mặc định — không hỏi lại, không
  // vòng lặp. Ref chặn StrictMode chạy effect hai lần: hai getCurrentPosition
  // song song là hai lượt runSearch giẫm nhau.
  const autoLocatedRef = useRef(false);
  useEffect(() => {
    if (autoLocatedRef.current) return;
    autoLocatedRef.current = true;
    try {
      const stored = JSON.parse(
        window.localStorage.getItem(LAST_LOCATION_STORAGE_KEY) ?? 'null',
      ) as (Position & { accuracy: number; savedAt: number }) | null;
      const fresh =
        stored && Date.now() - stored.savedAt <= LAST_LOCATION_MAX_AGE_MS;
      const valid =
        fresh &&
        Number.isFinite(stored.latitude) &&
        Number.isFinite(stored.longitude) &&
        stored.accuracy <= MAX_USABLE_ACCURACY_METERS;
      if (valid) {
        const restored = {
          latitude: stored.latitude,
          longitude: stored.longitude,
        };
        pendingLocationCenterRef.current = restored;
        window.queueMicrotask(() => {
          positionRef.current = restored;
          setPosition(restored);
          setHasLocationConsent(true);
          setGpsStatus(
            `Vị trí gần nhất ±${Math.round(stored.accuracy)} m · đang cập nhật…`,
          );
          mapRef.current?.jumpTo({
            center: [restored.longitude, restored.latitude],
            zoom: 14,
          });
          void runSearchRef.current('', null, restored);
        });
      }
    } catch {
      // Dữ liệu cũ hỏng hoặc storage bị chặn: bỏ qua và xin GPS mới bên dưới.
    }
    requestCurrentLocationRef.current();
  }, []);

  // Ping mới chỉ được gửi khi đã đủ xa lần trước HOẶC đã đủ lâu. Không có bộ
  // lọc này thì watchPosition bắn mỗi lần GPS nhích một mét: hàng nghìn sự kiện
  // rác mỗi phiên, và bộ chấm chất lượng toạ độ sẽ thấy một chuỗi dịch chuyển
  // vi mô thay vì một hành trình.
  const PING_MIN_INTERVAL_MS = 15_000;
  const PING_MIN_DISTANCE_M = 50;
  const FOLLOW_MIN_INTERVAL_MS = 3_000;
  const FOLLOW_MIN_DISTANCE_M = 5;

  function stopWatching() {
    if (watchIdRef.current !== null) {
      navigator.geolocation.clearWatch(watchIdRef.current);
      watchIdRef.current = null;
    }
    lastPingRef.current = null;
    lastShownRef.current = null;
    setIsWatching(false);
    setFollowMe(false);
    setWatchStatus('Theo dõi vị trí: tắt');
  }

  function startWatching() {
    if (!navigator.geolocation) {
      setWatchStatus('Trình duyệt không hỗ trợ định vị');
      return;
    }
    // Idempotent: bấm "Vị trí của tôi" nhiều lần không được nhân đôi watcher.
    if (watchIdRef.current !== null) return;
    const id = navigator.geolocation.watchPosition(
      ({ coords }) => {
        const nextPosition = {
          latitude: coords.latitude,
          longitude: coords.longitude,
        };
        const now = Date.now();

        // Hai nhịp tách nhau: chấm xanh/bản đồ cập nhật dày khi đang bám theo
        // (lúc chạy xe 15 s là ~150 m), còn location_ping gửi backend giữ
        // nguyên 15 s / 50 m để không đẩy hàng nghìn sự kiện mỗi chuyến đi.
        const shown = lastShownRef.current;
        const shownMoved = shown
          ? distanceInMeters(shown.position, nextPosition)
          : Infinity;
        const shownElapsed = shown ? now - shown.at : Infinity;
        const previous = lastPingRef.current;
        const moved = previous
          ? distanceInMeters(previous.position, nextPosition)
          : Infinity;
        const elapsed = previous ? now - previous.at : Infinity;
        const shouldPing =
          moved >= PING_MIN_DISTANCE_M || elapsed >= PING_MIN_INTERVAL_MS;
        // Bám theo: 3 s một lần, bỏ qua nhiễu GPS khi đứng yên (< 5 m).
        const shouldShow = followRef.current
          ? shownElapsed >= FOLLOW_MIN_INTERVAL_MS &&
            shownMoved >= FOLLOW_MIN_DISTANCE_M
          : shouldPing;
        if (!shouldPing && !shouldShow) return;

        lastShownRef.current = { at: now, position: nextPosition };
        setPosition(nextPosition);
        setPositionAccuracy(coords.accuracy);
        setHasLocationConsent(true);
        setGpsStatus(`GPS chính xác ±${Math.round(coords.accuracy)} m`);
        if (!shouldPing) return;

        lastPingRef.current = { at: now, position: nextPosition };
        setWatchStatus(
          `Theo dõi vị trí: bật · ping lúc ${new Date(now).toLocaleTimeString('vi-VN')}`,
        );
        telemetry.capture({
          event_type: 'location_ping',
          location: { ...nextPosition, accuracy_meters: coords.accuracy },
          location_consent: true,
          metadata: {
            source: 'browser-geolocation-watch',
            high_accuracy: true,
            moved_meters: Number.isFinite(moved) ? Math.round(moved) : null,
          },
        });
      },
      () => {
        setWatchStatus('Theo dõi vị trí: bị từ chối');
        stopWatching();
      },
      { enableHighAccuracy: true, timeout: 15_000, maximumAge: 5_000 },
    );
    watchIdRef.current = id;
    setIsWatching(true);
    setWatchStatus('Theo dõi vị trí: bật · đang chờ ping đầu tiên');
  }

  async function toggleGeofence(poi: Poi) {
    const sessionId = telemetryState.sessionId;
    if (!sessionId) {
      setStatus('Chưa có phiên — thử lại sau một nhịp');
      return;
    }
    // POI mẫu hard-code (poi-001…) không có trong database, nên backend từ chối
    // bằng 422. Chặn ngay ở đây và nói đúng nguyên nhân: báo "kiểm tra kết nối
    // tới API" trong khi API đang trả lời bình thường là đẩy người dùng đi tìm
    // sai chỗ — đúng loại thông báo lỗi tệ nhất.
    if (!UUID_PATTERN.test(poi.id)) {
      setStatus(
        'Đây là địa điểm mẫu, chưa có trong dữ liệu thật — hãy tìm kiếm trước',
      );
      return;
    }

    const existing = geofences.get(poi.id);
    try {
      if (existing) {
        await fetch(`${API_BASE_URL}/api/v1/geofences/${existing}`, {
          method: 'DELETE',
          headers: { 'X-Session-ID': sessionId },
        });
        setGeofences((current) => {
          const next = new Map(current);
          next.delete(poi.id);
          return next;
        });
        setStatus(`Đã bỏ nhắc "${poi.name}"`);
        return;
      }
      // Xin quyền thông báo NGAY TRONG cú bấm này. Xin lúc tải trang là cách
      // nhanh nhất để bị từ chối vĩnh viễn, và quyền đã bị chặn thì không xin
      // lại được bằng code.
      const allowed = await proximity.requestPermission();
      const response = await fetch(`${API_BASE_URL}/api/v1/geofences`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Session-ID': sessionId,
        },
        // KHÔNG gửi toạ độ: tâm vùng do backend lấy thẳng từ pois.location.
        body: JSON.stringify({ poi_id: poi.id, radius_meters: 300 }),
      });
      if (!response.ok) {
        // Đọc lý do server đưa ra thay vì nuốt nó: 422 (POI không tồn tại) và
        // 503 (backend chết) cần hai hành động khác hẳn nhau từ người dùng.
        const detail = await response.text();
        throw new Error(`HTTP ${response.status} ${detail.slice(0, 160)}`);
      }
      const created = (await response.json()) as { id: string };
      setGeofences((current) => new Map(current).set(poi.id, created.id));
      setStatus(
        allowed
          ? `Sẽ nhắc khi bạn tới gần "${poi.name}" (300 m)`
          : `Đã lưu vùng nhắc "${poi.name}", nhưng trình duyệt đang chặn thông báo`,
      );
    } catch (error) {
      setStatus(`Không lưu được vùng nhắc — ${(error as Error).message}`);
    }
  }

  /** Bật chế độ chỉ đường cho một POI — cách DUY NHẤT để tuyến được tính.
   *  Effect lấy tuyến tự chạy khi `directionsActive` bật; effect vẽ tuyến tự
   *  lùi khung nhìn cho vừa tuyến khi dữ liệu về. */
  function startNavigation(poi: Poi) {
    // Nút chính luôn ở trong ứng dụng. Trước đây khi route chưa kịp tải hoặc
    // POI mẫu không có UUID, nhánh cuối tự mở Google Maps — đúng cú nhảy trang
    // mà người dùng không mong đợi.
    const inAppRoute =
      directionsActive && route && route.poiId === poi.id ? route : null;
    telemetry.capture({
      event_type: 'navigation_start',
      poi_id: poi.id,
      metadata: {
        provider: 'in-app',
        mode: transportMode,
        route_ready: Boolean(inAppRoute),
      },
    });
    setShowSteps(true);
    // Chỉ đường bấm từ danh sách kết quả: tuyến vẽ trên bản đồ nên phải sang đó.
    showMapOnMobile();
    if (selectedPoiId !== poi.id) {
      // "Chỉ đường" trong panel chi tiết có thể thuộc một POI chưa được chọn
      // (deep link, địa điểm tương tự). Tuyến chỉ tính cho POI đang chọn, nên
      // chọn nó trước — thêm vào danh sách nếu nó chưa có ở đó.
      if (!visiblePois.some((item) => item.id === poi.id)) {
        setPois((current) => [
          {
            ...poi,
            distanceMeters:
              poi.distanceMeters ?? distanceInMeters(position, poi),
          },
          ...current,
        ]);
      }
      setSelectedPoiId(poi.id);
    }
    setDirectionsPoiId(poi.id);
    setDirectionsCollapsed(false);
    if (inAppRoute) {
      const map = mapRef.current;
      if (map) {
        // Cùng padding với effect khung tuyến — thẻ chỉ đường vừa mở đầy đủ.
        map.fitBounds(lineBounds(inAppRoute.geometry.coordinates), {
          padding: routeFitPadding(map, false, showDebugPanel),
          maxZoom: ROUTE_MAX_ZOOM,
          duration: 700,
        });
      }
    }
  }

  // "Chỉ đường tới số 1" trong trợ lý chỉ mang poiId, còn startNavigation cần
  // đủ Poi (toạ độ, tên) — mở panel chi tiết trước, chi tiết về thì bật chỉ đường.
  const pendingChatDirectionsRef = useRef<string | null>(null);
  const directionsFromChat = useCallback(
    (poiId: string) => {
      pendingChatDirectionsRef.current = poiId;
      openDetail(poiId, 'chat');
    },
    [openDetail],
  );
  const navigateFromChat = useEffectEvent((poi: Poi) => startNavigation(poi));
  useEffect(() => {
    if (!detailAsPoi || pendingChatDirectionsRef.current !== detailAsPoi.id) return;
    pendingChatDirectionsRef.current = null;
    navigateFromChat(detailAsPoi);
  }, [detailAsPoi]);

  return (
    <main className="nearby-app flex h-dvh flex-col overflow-hidden bg-transparent text-foreground">
      <header className="app-header relative z-30 shrink-0 border-b border-emerald-950/[0.07] bg-white/75 px-3 pt-[max(0.5rem,env(safe-area-inset-top))] pb-2 backdrop-blur-xl sm:px-6 sm:py-3 dark:border-white/[0.07] dark:bg-background/75">
        <div className="mx-auto flex max-w-[1500px] flex-wrap items-center justify-between gap-x-4 gap-y-2 max-lg:flex-nowrap max-sm:gap-x-2">
          <div className="flex min-w-0 items-center gap-2.5 sm:gap-3">
            <div className="brand-mark grid size-9 shrink-0 place-items-center rounded-xl text-white sm:size-11 sm:rounded-2xl">
              <Compass className="size-5 sm:size-[22px]" strokeWidth={2.25} />
            </div>
            {/* Máy < 380px (360px là phổ biến) không đủ chỗ cho chữ cạnh năm nút
                thao tác — chữ bị bẻ hai dòng làm header cao vọt. Logo la bàn
                vẫn đủ nhận diện. */}
            <div className="max-[379px]:sr-only">
              <div className="flex items-center gap-2">
                <span className="brand-wordmark text-lg font-extrabold tracking-tight whitespace-nowrap sm:text-xl" translate="no">Nearby</span>
                <span className="hidden items-center gap-1.5 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[11px] font-semibold text-emerald-700 ring-1 ring-emerald-600/15 sm:inline-flex dark:text-emerald-300 dark:ring-emerald-400/20">
                  <span className="live-dot size-1.5 rounded-full bg-emerald-500" aria-hidden />
                  Tầng 1-3 · Live
                </span>
              </div>
              <p className="hidden text-xs text-muted-foreground sm:block">
                Tìm kiếm địa điểm theo vị trí
              </p>
            </div>
          </div>
          {/* Dưới lg (điện thoại, máy tính bảng — cùng mốc với thanh tab dưới
              đáy): một hàng duy nhất — ba thao tác hay dùng nhất hiện
              thẳng, còn ngôn ngữ / giao diện tối / giới thiệu gom vào menu "⋮".
              Bày cả sáu nút ra như desktop thì header vỡ thành ba hàng và
              chiếm ~1/3 màn hình trước khi người dùng thấy được gì. */}
          <div className="header-actions-mobile flex shrink-0 items-center gap-1 lg:hidden">
            <Button
              variant="ghost"
              size="icon"
              className="rounded-full"
              onClick={requestCurrentLocation}
              aria-label="Vị trí của tôi"
              title="Vị trí của tôi"
            >
              <LocateFixed className="size-5" />
            </Button>
            <Button
              variant={isWatching ? 'default' : 'ghost'}
              size="icon"
              className="rounded-full"
              onClick={() => (isWatching ? stopWatching() : startWatching())}
              title={watchStatus}
              aria-label={isWatching ? 'Đang theo dõi vị trí' : 'Theo dõi vị trí'}
              aria-pressed={isWatching}
            >
              <Route className="size-5" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="rounded-full"
              onClick={() => setVoiceSearchOpen((value) => !value)}
              data-voice-search-trigger
              aria-expanded={voiceSearchOpen}
              aria-label="Tìm bằng giọng nói (Alt+V: chế độ giọng nói cho người khiếm thị)"
              title="Tìm bằng giọng nói"
            >
              <Mic className="size-5" />
            </Button>
            <AccountMenu
              apiBaseUrl={API_BASE_URL}
              sessionId={telemetryState.sessionId}
              compact
            />
            <Popover>
              <PopoverTrigger
                render={
                  <Button
                    variant="ghost"
                    size="icon"
                    className="rounded-full"
                    aria-label="Thêm tuỳ chọn"
                  />
                }
              >
                <EllipsisVertical className="size-5" />
              </PopoverTrigger>
              <PopoverContent align="end" className="w-[min(18rem,calc(100vw-1.5rem))] gap-1 p-2">
                <label className="flex flex-col gap-1.5 px-2 pt-1 pb-2" translate="no">
                  <span className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                    <Languages className="size-4" aria-hidden />
                    Ngôn ngữ / Language
                    {uiLanguage.progress && (
                      <output className="ml-auto flex items-center gap-1 tabular-nums">
                        <LoaderCircle className="size-3.5 animate-spin" aria-hidden />
                        {uiLanguage.progress.done}/{uiLanguage.progress.total}
                      </output>
                    )}
                  </span>
                  <select
                    value={uiLanguage.language}
                    onChange={(event) => uiLanguage.setLanguage(event.target.value)}
                    className="h-11 w-full rounded-lg border border-input bg-background px-3 text-base text-foreground"
                    aria-label="Ngôn ngữ / Language"
                  >
                    {uiLanguage.languages.map((item) => (
                      <option key={item.code} value={item.code}>
                        {item.nativeName}
                        {item.nativeName !== item.name ? ` · ${item.name}` : ''}
                      </option>
                    ))}
                  </select>
                </label>
                <Button
                  variant="ghost"
                  className="h-11 justify-start gap-3 px-2 text-sm"
                  onClick={toggleTheme}
                >
                  {theme === 'dark' ? <Sun className="size-5" /> : <Moon className="size-5" />}
                  {theme === 'dark' ? 'Giao diện sáng' : 'Giao diện tối'}
                </Button>
                <Button
                  variant="ghost"
                  className="h-11 justify-start gap-3 px-2 text-sm"
                  onClick={() => guide.setOpen(true)}
                >
                  <CircleQuestionMark className="size-5" />
                  Hướng dẫn sử dụng
                </Button>
                <Button
                  variant="ghost"
                  className="h-11 justify-start gap-3 px-2 text-sm"
                  onClick={() => about.setOpen(true)}
                >
                  <Info className="size-5" />
                  Giới thiệu đồ án
                </Button>
              </PopoverContent>
            </Popover>
          </div>
          <div className="header-actions hidden items-center gap-2 text-xs text-muted-foreground lg:flex">
            <span className="hidden items-center gap-1 px-1 font-medium 2xl:inline-flex">
              <MapPin className="size-3.5 text-primary" aria-hidden />
              TP. Hồ Chí Minh
            </span>
            {/* Nhóm tiện ích phụ (ngôn ngữ, giao diện, giọng nói, giới thiệu)
                gom vào một thanh bo tròn — sáu nút viền rời nhau trước đây
                tranh sự chú ý với hai thao tác vị trí chính. */}
            <div className="flex h-10 items-center gap-0.5 rounded-full border border-emerald-950/10 bg-white/70 p-1 shadow-[0_1px_2px_rgb(14_68_48/6%)] dark:border-white/10 dark:bg-white/5">
              {/* translate="no": tên ngôn ngữ đã là tên bản ngữ, không dịch. */}
              <label className="flex h-8 items-center gap-1.5 rounded-full pr-1 pl-2.5 transition-colors hover:bg-muted" translate="no">
                <Languages className="size-4 text-primary" aria-hidden />
                <span className="sr-only">Ngôn ngữ / Language</span>
                <select
                  value={uiLanguage.language}
                  onChange={(event) => uiLanguage.setLanguage(event.target.value)}
                  className="h-8 max-w-[9.5rem] cursor-pointer rounded-full border-0 bg-transparent pr-1 text-xs font-medium text-foreground outline-none"
                  aria-label="Ngôn ngữ / Language"
                >
                  {uiLanguage.languages.map((item) => (
                    <option key={item.code} value={item.code}>
                      {item.nativeName}
                      {item.nativeName !== item.name ? ` · ${item.name}` : ''}
                    </option>
                  ))}
                </select>
                {uiLanguage.progress && (
                  <output className="flex items-center gap-1 tabular-nums">
                    <LoaderCircle className="size-3.5 animate-spin" aria-hidden />
                    {uiLanguage.progress.done}/{uiLanguage.progress.total}
                  </output>
                )}
              </label>
              <span className="mx-0.5 h-5 w-px bg-border" aria-hidden />
              <Button
                variant="ghost"
                size="icon"
                className="size-8 rounded-full"
                onClick={toggleTheme}
                aria-label="Chuyển giao diện sáng/tối"
                title={theme === 'dark' ? 'Giao diện sáng' : 'Giao diện tối'}
              >
                {theme === 'dark' ? (
                  <Sun className="size-4" />
                ) : (
                  <Moon className="size-4" />
                )}
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="size-8 rounded-full"
                onClick={() => setVoiceSearchOpen((value) => !value)}
                data-voice-search-trigger
                aria-expanded={voiceSearchOpen}
                aria-label="Tìm bằng giọng nói (Alt+V: chế độ giọng nói cho người khiếm thị)"
                title="Tìm bằng giọng nói · Alt+V: chế độ đầy đủ"
              >
                <Mic className="size-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="size-8 rounded-full"
                onClick={() => guide.setOpen(true)}
                aria-label="Hướng dẫn sử dụng"
                title="Hướng dẫn sử dụng"
              >
                <CircleQuestionMark className="size-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="size-8 rounded-full"
                onClick={() => about.setOpen(true)}
                aria-label="Giới thiệu đồ án"
                title="Giới thiệu đồ án"
              >
                <Info className="size-4" />
              </Button>
            </div>
            <AccountMenu apiBaseUrl={API_BASE_URL} sessionId={telemetryState.sessionId} />
            <Button
              variant={isWatching ? 'default' : 'outline'}
              className="h-9 rounded-full px-3.5 text-[13px]"
              onClick={() => (isWatching ? stopWatching() : startWatching())}
              title={watchStatus}
              aria-label={isWatching ? 'Đang theo dõi vị trí' : 'Theo dõi vị trí'}
              aria-pressed={isWatching}
            >
              <Route data-icon="inline-start" />
              {isWatching ? 'Đang theo dõi' : 'Theo dõi vị trí'}
            </Button>
            <Button
              className="h-9 rounded-full px-4 text-[13px] shadow-[0_6px_16px_-4px_rgb(15_138_98/55%)]"
              onClick={requestCurrentLocation}
              aria-label="Vị trí của tôi"
              title="Vị trí của tôi"
            >
              <LocateFixed data-icon="inline-start" />
              Vị trí của tôi
            </Button>
          </div>
        </div>
      </header>
      <AboutDialog open={about.open} onOpenChange={about.onOpenChange} />
      <GuideDialog open={guide.open} onOpenChange={guide.onOpenChange} />


      <section
        className={cn(
          'explorer-layout relative mx-auto min-h-0 w-full max-w-[1500px] flex-1 overflow-hidden lg:grid lg:grid-cols-[430px_minmax(0,1fr)] lg:gap-5 lg:overflow-visible lg:p-5',
          chatOpen && 'xl:grid-cols-[390px_minmax(0,1fr)_360px]',
          mapExpanded && 'lg:grid-cols-[minmax(0,1fr)]',
          mapExpanded && chatOpen && 'xl:grid-cols-[minmax(0,1fr)_360px]',
        )}
      >
        <aside
          ref={mobileSheetRef}
          className={cn(
            'absolute inset-0 z-20 flex flex-col gap-3 overflow-y-auto overscroll-contain bg-background p-3 sm:gap-4 sm:p-4 lg:static lg:z-auto lg:-mr-3 lg:min-h-0 lg:min-w-0 lg:gap-4 lg:bg-transparent lg:p-0 lg:pr-3 lg:pb-2',
            mobileView === 'map' && 'max-lg:hidden',
            mapExpanded && 'lg:hidden',
          )}
        >
          <Card
            id="nearby-search"
            className={cn(
              'glass-card min-w-0 shrink-0 overflow-visible rounded-3xl ring-0',
              mobileView !== 'search' && 'max-lg:hidden',
            )}
          >
            {/* Điện thoại: bỏ dòng mô tả và biểu tượng trang trí để ô tìm kiếm,
                bán kính và các tiện ích hiện đủ trong MỘT màn hình, không phải cuộn. */}
            <CardHeader className="px-4 pt-4 pb-2 max-lg:pt-3 max-lg:pb-0 sm:px-5 sm:pt-5 sm:pb-3">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <CardTitle className="text-[22px] font-bold tracking-tight">
                    Bạn muốn đi đâu?
                  </CardTitle>
                  <CardDescription className="max-lg:hidden">
                    Tìm địa điểm phù hợp trong vài giây.
                  </CardDescription>
                </div>
                <div className="grid size-11 shrink-0 place-items-center rounded-2xl bg-gradient-to-br from-emerald-100 to-teal-50 text-primary ring-1 ring-emerald-600/10 max-lg:hidden dark:from-emerald-500/20 dark:to-teal-500/5 dark:ring-emerald-400/15">
                  <Sparkles className="size-5" />
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-3 px-4 pb-4 sm:px-5 sm:pb-5">
              <form
                className="flex gap-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  void searchNearby();
                  // Điện thoại: bấm "Tìm" là muốn xem danh sách, đừng để người
                  // dùng tự đi tìm tab Kết quả. Chip danh mục thì KHÔNG chuyển
                  // màn — người dùng thường bấm vài chip liền để lọc thử.
                  if (window.innerWidth < 1024) setMobileView('results');
                }}
              >
                <div className="relative min-w-0 flex-1">
                  <Search className="pointer-events-none absolute left-3.5 top-1/2 size-[18px] -translate-y-1/2 text-primary/70" />
                  <Input
                    className="h-12 rounded-2xl border-emerald-950/10 bg-white pl-10 pr-11 text-[15px] shadow-[inset_0_1px_2px_rgb(14_68_48/5%)] transition-shadow focus-visible:shadow-[0_0_0_4px_rgb(15_138_98/12%)] dark:border-white/10 dark:bg-input/40"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    onFocus={() => {
                      if (suggestions.length > 0) setSuggestionsOpen(true);
                    }}
                    onBlur={() => setSuggestionsOpen(false)}
                    onKeyDown={(event) => {
                      if (!suggestionsOpen || suggestions.length === 0) return;
                      if (event.key === 'ArrowDown') {
                        event.preventDefault();
                        setActiveSuggestionIndex(
                          (current) => (current + 1) % suggestions.length,
                        );
                      } else if (event.key === 'ArrowUp') {
                        event.preventDefault();
                        setActiveSuggestionIndex((current) =>
                          current <= 0 ? suggestions.length - 1 : current - 1,
                        );
                      } else if (
                        event.key === 'Enter' &&
                        activeSuggestionIndex >= 0
                      ) {
                        event.preventDefault();
                        selectSuggestion(suggestions[activeSuggestionIndex]);
                      } else if (event.key === 'Escape') {
                        setSuggestionsOpen(false);
                      }
                    }}
                    placeholder="Cà phê, phở, ATM…"
                    aria-label="Từ khóa tìm kiếm"
                    // Input bọc một <input> thật; role="combobox" là mẫu ARIA
                    // combobox chuẩn (kèm aria-controls/aria-activedescendant
                    // dưới đây), không phải role đặt sai chỗ.
                    // eslint-disable-next-line jsx-a11y/prefer-tag-over-role
                    role="combobox"
                    aria-expanded={suggestionsOpen && suggestions.length > 0}
                    aria-autocomplete="list"
                    aria-controls="poi-suggestion-listbox"
                    aria-activedescendant={
                      activeSuggestionIndex >= 0
                        ? `poi-suggestion-${suggestions[activeSuggestionIndex]?.id}`
                        : undefined
                    }
                    autoComplete="off"
                  />
                  <button
                    type="button"
                    onClick={() => setVoiceSearchOpen((value) => !value)}
                    data-voice-search-trigger
                    aria-expanded={voiceSearchOpen}
                    aria-label="Tìm bằng giọng nói"
                    title="Tìm bằng giọng nói"
                    className={`absolute right-1.5 top-1/2 grid size-9 -translate-y-1/2 place-items-center rounded-xl transition-colors ${
                      voiceSearchOpen
                        ? 'bg-amber-400 text-slate-950'
                        : 'text-primary/70 hover:bg-emerald-50 hover:text-primary dark:hover:bg-white/10'
                    }`}
                  >
                    <Mic className="size-[18px]" />
                  </button>
                  {suggestionsOpen && suggestions.length > 0 && (
                    <div
                      id="poi-suggestion-listbox"
                      // <datalist>/<select> không render được icon, địa chỉ
                      // và khoảng cách trên mỗi dòng — popup role="listbox"
                      // là cách chuẩn ARIA để làm một combobox tuỳ biến.
                      // eslint-disable-next-line jsx-a11y/prefer-tag-over-role
                      role="listbox"
                      aria-label="Gợi ý địa điểm"
                      className="absolute left-0 right-0 top-[calc(100%+6px)] z-20 max-h-72 overflow-y-auto rounded-2xl border border-border bg-white p-1 shadow-[0_18px_48px_-12px_rgb(14_68_48/28%)] dark:border-white/10 dark:bg-popover"
                    >
                      {suggestions.map((suggestion, index) => (
                        // Mục KHÔNG nhận focus: đây là mẫu combobox dùng
                        // aria-activedescendant (focus luôn ở ô input phía
                        // trên) — thêm tabIndex ở đây sẽ tạo thêm điểm dừng
                        // Tab sai với mẫu này, không phải sửa đúng.
                        // eslint-disable-next-line jsx-a11y/interactive-supports-focus
                        <div
                          key={suggestion.id}
                          id={`poi-suggestion-${suggestion.id}`}
                          // eslint-disable-next-line jsx-a11y/prefer-tag-over-role
                          role="option"
                          aria-selected={index === activeSuggestionIndex}
                          className={`flex cursor-pointer items-start gap-2 rounded-xl px-3 py-2 text-sm ${
                            index === activeSuggestionIndex
                              ? 'bg-muted'
                              : 'hover:bg-muted'
                          }`}
                          onMouseEnter={() => setActiveSuggestionIndex(index)}
                          // onMouseDown (không phải onClick) chạy TRƯỚC blur
                          // của input, và preventDefault chặn luôn blur đó —
                          // không thì onBlur đóng dropdown trước khi click
                          // kịp đăng ký, và cú bấm coi như không xảy ra.
                          onPointerDown={(event) => {
                            event.preventDefault();
                            selectSuggestion(suggestion);
                          }}
                        >
                          <MapPin className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
                          <span className="min-w-0 flex-1">
                            <span className="block truncate font-medium">
                              {suggestion.name}
                            </span>
                            <span className="block truncate text-xs text-muted-foreground">
                              {suggestion.categoryLabel}
                              {suggestion.address
                                ? ` · ${suggestion.address}`
                                : ''}
                            </span>
                          </span>
                          {suggestion.distanceMeters != null && (
                            <span className="shrink-0 text-xs text-muted-foreground">
                              {formatMeters(suggestion.distanceMeters)}
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                <Button
                  className="h-12 rounded-2xl px-5 text-[15px] font-semibold shadow-[0_8px_20px_-6px_rgb(15_138_98/60%)]"
                  type="submit"
                  disabled={isLoading}
                >
                  {isLoading ? 'Đang tìm…' : 'Tìm'}
                </Button>
              </form>
              <div className="flex items-center justify-between gap-3 rounded-2xl bg-emerald-50/70 px-3.5 py-2 ring-1 ring-emerald-600/[0.06] dark:bg-white/5 dark:ring-white/5">
                <div className="flex shrink-0 items-center gap-2 text-sm font-medium whitespace-nowrap">
                  <SlidersHorizontal className="size-4 text-primary max-sm:hidden" />
                  <span>Bán kính</span>
                </div>
                {/* Bốn nút chọn thẳng thay cho <select>: một chạm thay vì mở hộp
                    chọn của hệ điều hành rồi chạm lần nữa. */}
                <fieldset
                  aria-label="Bán kính tìm kiếm"
                  className="m-0 flex min-w-0 max-w-64 flex-1 gap-1 rounded-xl border-0 bg-white p-1 shadow-[0_1px_2px_rgb(14_68_48/6%)] ring-1 ring-emerald-950/10 dark:bg-input/40 dark:ring-white/10"
                >
                  {RADIUS_OPTIONS.map((meters) => (
                    <button
                      key={meters}
                      type="button"
                      aria-pressed={radius === meters}
                      onClick={() => {
                        if (meters === radius) return;
                        // Trước đây chỉ setRadius: bán kính mới chỉ có hiệu lực ở
                        // lần bấm "Tìm" kế tiếp, nên đổi 1 km <-> 10 km trông như
                        // không làm gì với danh sách đang hiện.
                        setRadius(meters);
                        void runSearch(query, selectedCategory, undefined, meters);
                      }}
                      className={cn(
                        'nearby-chip min-w-11 flex-1 rounded-lg px-1.5 py-1 text-sm font-semibold whitespace-nowrap tabular-nums transition-colors',
                        radius === meters
                          ? 'bg-primary text-primary-foreground shadow-sm'
                          : 'text-foreground/70 hover:bg-muted',
                      )}
                    >
                      {meters / 1000} km
                    </button>
                  ))}
                </fieldset>
              </div>
              {/* Điện thoại: MỘT hàng chip vuốt ngang, đủ mọi danh mục — thay
                  cho lưới chip xuống dòng chiếm nửa màn hình và nút "+N danh
                  mục". Từ lg vẫn là lưới xuống dòng thu gọn như cũ. */}
              {categoryOptions.length > 0 && (
                <div className="-mx-4 flex gap-1.5 overflow-x-auto px-4 pb-1 hide-scrollbar sm:-mx-5 sm:px-5 lg:mx-0 lg:flex-wrap lg:overflow-visible lg:px-0 lg:pb-0">
                  <button
                    type="button"
                    onClick={() => {
                      setSelectedCategory(null);
                      void runSearch(query, null);
                    }}
                    className={`inline-flex shrink-0 items-center gap-1.5 ${chipClass(
                      selectedCategory === null,
                    )}`}
                  >
                    <LayoutGrid className="size-3.5" aria-hidden />
                    Tất cả
                  </button>
                  {categoryOptions.map((option, index) => {
                    // `aria-hidden` vì nhãn ngay bên cạnh đã nói đúng nội dung
                    // đó rồi; đọc thêm tên icon chỉ làm trình đọc màn hình lặp.
                    const Icon = categoryChipIcon(option.categoryLabel);
                    // Chỉ ẩn ở lg+: dưới lg mọi chip luôn hiện trong hàng vuốt.
                    // Danh mục đang chọn luôn hiện, kể cả khi nằm ngoài hai
                    // hàng đầu — không thì không biết đang lọc gì.
                    const hiddenOnDesktop =
                      !categoriesExpanded &&
                      index >= COLLAPSED_CATEGORY_COUNT &&
                      option.category !== selectedCategory;
                    return (
                      <button
                        key={option.category}
                        type="button"
                        onClick={() => toggleCategory(option.category)}
                        className={cn(
                          'inline-flex shrink-0 items-center gap-1.5',
                          chipClass(selectedCategory === option.category),
                          hiddenOnDesktop && 'lg:hidden',
                        )}
                      >
                        <Icon className="size-3.5" aria-hidden />
                        {option.categoryLabel}
                      </button>
                    );
                  })}
                  {categoryOptions.length > COLLAPSED_CATEGORY_COUNT && (
                    <button
                      type="button"
                      onClick={() => setCategoriesExpanded((current) => !current)}
                      aria-expanded={categoriesExpanded}
                      className="nearby-chip inline-flex items-center gap-1 rounded-full px-3 py-1.5 text-xs font-semibold text-primary transition-colors hover:bg-primary/10 max-lg:hidden"
                    >
                      {categoriesExpanded
                        ? 'Thu gọn'
                        : `+${categoryOptions.length - COLLAPSED_CATEGORY_COUNT} danh mục`}
                      {categoriesExpanded ? (
                        <ChevronUp className="size-3.5" aria-hidden />
                      ) : (
                        <ChevronDown className="size-3.5" aria-hidden />
                      )}
                    </button>
                  )}
                </div>
              )}
              <div className="flex items-center justify-between gap-3">
                <p className="min-w-0 text-xs text-muted-foreground" aria-live="polite">
                  {status}
                </p>
                {/* Chưa có vị trí thì "gần bạn" chỉ là trung tâm TP.HCM — đưa
                    thẳng nút xin quyền ra đây thay vì bắt người dùng tự đi tìm
                    biểu tượng ở góc trên. */}
                {!hasLocationConsent && (
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    className="shrink-0 gap-1.5 rounded-full px-3 text-xs font-semibold lg:hidden"
                    onClick={requestCurrentLocation}
                  >
                    <LocateFixed className="size-4" aria-hidden />
                    Dùng vị trí của tôi
                  </Button>
                )}
              </div>
              {/* Dải tín hiệu CẤP TRUY VẤN — những thứ dùng chung cho cả lượt
                  tìm, không lặp lại trên từng dòng kết quả. Mỗi chip hoặc có số
                  kèm đơn vị, hoặc là một câu nói rõ vì sao chưa có dữ liệu.
                  Không chip nào in ra một số 0 trần trụi. */}
              {(searchMeta || queryWeather) && (
                <div className="flex flex-wrap gap-1.5 text-[11px]">
                  {searchMeta && (
                    <span
                      className={`inline-flex items-center gap-1 rounded-full px-2 py-1 font-medium ${
                        searchMeta.backend === 'opensearch'
                          ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300'
                          : 'bg-amber-50 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300'
                      }`}
                      title={
                        searchMeta.backend === 'opensearch'
                          ? 'BM25 + vector + geo + H3 + trending, gộp bằng Reciprocal Rank Fusion'
                          : 'OpenSearch không dùng được — đang chạy đường PostGIS dự phòng'
                      }
                    >
                      {searchMeta.backend === 'opensearch'
                        ? 'Đa kênh · RRF'
                        : 'PostGIS dự phòng'}
                    </span>
                  )}
                  {h3Badge && (
                    <span
                      className="inline-flex items-center gap-1 rounded-full bg-sky-50 px-2 py-1 font-medium text-sky-700 dark:bg-sky-500/15 dark:text-sky-300"
                      title="Kênh 2 lọc bằng vành hexagon H3 (terms trên chỉ mục đảo) thay vì tính khoảng cách từng document"
                    >
                      {h3Badge}
                    </span>
                  )}
                  {queryWeather && (
                    <span
                      className="inline-flex items-center gap-1 rounded-full bg-violet-50 px-2 py-1 font-medium text-violet-700 dark:bg-violet-500/15 dark:text-violet-300"
                      title={
                        queryWeather.isWet
                          ? 'Trời mưa: hạ điểm địa điểm ngoài trời, nâng địa điểm có mái che'
                          : 'Trời khô: thời tiết không tác động tới thứ hạng'
                      }
                    >
                      {weatherLabel(queryWeather)}
                    </span>
                  )}
                  {searchMeta?.ranker && (
                    <span
                      className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-1 font-medium text-muted-foreground"
                      title="Bộ xếp hạng ĐÃ CHẠY THẬT, không phải cái được yêu cầu"
                    >
                      {searchMeta.ranker === 'ltr'
                        ? 'LambdaMART'
                        : 'Tuyến tính 9 tín hiệu'}
                    </span>
                  )}
                </div>
              )}
              <div className="grid grid-cols-2 gap-2 max-lg:hidden xl:hidden">
                <div className="rounded-xl border border-border/70 bg-white px-3 py-2 dark:bg-card">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Định vị
                  </p>
                  <p className="mt-1 truncate text-xs font-medium">
                    {gpsStatus}
                  </p>
                </div>
                <div className="rounded-xl border border-border/70 bg-white px-3 py-2 dark:bg-card">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Event stream
                  </p>
                  <p className="mt-1 text-xs font-medium">
                    {telemetryState.delivered} gửi · {telemetryState.queued} chờ
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>
          <div className={cn('min-w-0 shrink-0', mobileView !== 'search' && 'max-lg:hidden')}>
          {parkingOpen ? (
            <ParkingFinder
              apiBaseUrl={API_BASE_URL}
              mapRef={mapRef}
              userPosition={position}
              selectedPlace={
                poiDetail
                  ? { name: poiDetail.name, latitude: poiDetail.latitude, longitude: poiDetail.longitude }
                  : null
              }
              request={parkingRequest}
              onOpenDetail={openParkingDetail}
              onClose={() => {
                setParkingOpen(false);
                // Xoá yêu cầu cũ: không thì lần mở sau tự tìm lại điểm đến cũ.
                setParkingRequest(null);
              }}
            />
          ) : chargingOpen ? (
            <ChargingFinder
              apiBaseUrl={API_BASE_URL}
              mapRef={mapRef}
              userPosition={position}
              onOpenDetail={openParkingDetail}
              onClose={() => setChargingOpen(false)}
            />
          ) : fuelOpen ? (
            <FuelFinder
              apiBaseUrl={API_BASE_URL}
              mapRef={mapRef}
              userPosition={position}
              onOpenDetail={openParkingDetail}
              onClose={() => setFuelOpen(false)}
            />
          ) : convenienceOpen ? (
            <ConvenienceFinder
              apiBaseUrl={API_BASE_URL}
              mapRef={mapRef}
              userPosition={position}
              onOpenDetail={openParkingDetail}
              onClose={() => setConvenienceOpen(false)}
            />
          ) : toiletOpen ? (
            <ToiletFinder
              apiBaseUrl={API_BASE_URL}
              mapRef={mapRef}
              userPosition={position}
              onOpenDetail={openParkingDetail}
              onClose={() => setToiletOpen(false)}
            />
          ) : busOpen ? (
            <BusFinder
              apiBaseUrl={API_BASE_URL}
              mapRef={mapRef}
              userPosition={position}
              onShowMap={() => setMobileView('map')}
              onClose={() => setBusOpen(false)}
            />
          ) : (
            <div className="grid gap-3">
            {/* 6 nút, lưới 3 cột × 2 hàng (giữ lưới 6 cột để mỗi nút chiếm 2). */}
            <div className="grid shrink-0 grid-cols-6 gap-2">
              {(
                [
                  {
                    label: 'Tìm chỗ gửi xe',
                    short: 'Gửi xe',
                    Icon: CircleParking,
                    tone: 'bg-emerald-50 text-emerald-600 ring-emerald-600/10 dark:bg-emerald-500/15 dark:text-emerald-300',
                    open: () => setParkingOpen(true),
                  },
                  {
                    label: 'Trạm sạc xe điện',
                    short: 'Trạm sạc',
                    Icon: Zap,
                    tone: 'bg-sky-50 text-sky-600 ring-sky-600/10 dark:bg-sky-500/15 dark:text-sky-300',
                    open: () => setChargingOpen(true),
                  },
                  {
                    label: 'Tìm trạm xăng',
                    short: 'Trạm xăng',
                    Icon: Fuel,
                    tone: 'bg-amber-50 text-amber-600 ring-amber-600/10 dark:bg-amber-500/15 dark:text-amber-300',
                    open: () => setFuelOpen(true),
                  },
                  {
                    label: 'Cửa hàng tiện lợi',
                    short: 'Tiện lợi',
                    Icon: Store,
                    tone: 'bg-blue-50 text-blue-600 ring-blue-600/10 dark:bg-blue-500/15 dark:text-blue-300',
                    open: () => setConvenienceOpen(true),
                  },
                  {
                    label: 'Nhà vệ sinh',
                    short: 'Nhà vệ sinh',
                    Icon: Toilet,
                    tone: 'bg-teal-50 text-teal-600 ring-teal-600/10 dark:bg-teal-500/15 dark:text-teal-300',
                    open: () => setToiletOpen(true),
                  },
                  {
                    label: 'Xe buýt',
                    short: 'Xe buýt',
                    Icon: Bus,
                    tone: 'bg-indigo-50 text-indigo-600 ring-indigo-600/10 dark:bg-indigo-500/15 dark:text-indigo-300',
                    open: () => setBusOpen(true),
                  },
                ] as const
              ).map(({ label, short, Icon, tone, open }) => (
                <Button
                  key={label}
                  type="button"
                  variant="outline"
                  onClick={open}
                  className={cn(
                    'col-span-2',
                    'glass-card group h-auto min-h-11 min-w-0 flex-col gap-1.5 rounded-2xl px-2 py-2.5 text-center max-lg:text-xs lg:gap-2 lg:py-3 text-[13px] leading-tight font-semibold whitespace-normal transition-all hover:-translate-y-0.5 hover:border-primary/25 hover:bg-white hover:shadow-[0_14px_32px_-10px_rgb(14_68_48/22%)] dark:hover:bg-card',
                  )}
                >
                  <span
                    className={cn(
                      'grid size-9 place-items-center rounded-xl ring-1 transition-transform group-hover:scale-105 lg:size-10',
                      tone,
                    )}
                  >
                    <Icon className="size-5" aria-hidden />
                  </span>
                  <span className="lg:hidden">{short}</span>
                  <span className="max-lg:hidden">{label}</span>
                </Button>
              ))}
            </div>
            <NearbyLandmarksCard
              landmarks={nearbyLandmarks.landmarks}
              discovered={nearbyLandmarks.discovered}
              total={nearbyLandmarks.total}
              loaded={nearbyLandmarks.loaded}
              failed={nearbyLandmarks.failed}
              hasRealGps={positionAccuracy !== null}
              layerOn={landmarkLayerOn}
              onToggleLayer={() => setLandmarkLayerOn((value) => !value)}
              alertsEnabled={landmarkAlerts.enabled}
              alertsPermission={landmarkAlerts.permission}
              onToggleAlerts={() => {
                if (landmarkAlerts.enabled) {
                  landmarkAlerts.disable();
                  return;
                }
                void landmarkAlerts.enable().then((ok) => {
                  if (!ok) return;
                  // Nhắc chỉ có ích khi vị trí được cập nhật lúc di chuyển.
                  if (!isWatching) startWatching();
                  setStatus('Đã bật nhắc khi tới gần địa danh · đang theo dõi vị trí');
                });
              }}
              alert={landmarkAlerts.alert}
              onDismissAlert={landmarkAlerts.dismiss}
              onOpen={openLandmark}
            />
            </div>
          )}
          </div>

          <div
            id="nearby-results"
            className={cn(
              'flex min-w-0 flex-col gap-4',
              mobileView !== 'results' && 'max-lg:hidden',
            )}
          >
            {showDiscovery &&
              trending &&
              (trending.pois.length > 0 || trending.queries.length > 0) && (
                <div className="glass-card shrink-0 space-y-2.5 rounded-3xl p-4">
                  <div className="flex items-center gap-2 text-sm font-semibold">
                    <span className="grid size-7 place-items-center rounded-lg bg-orange-50 text-orange-500 ring-1 ring-orange-500/10 dark:bg-orange-500/15">
                      <Flame className="size-4" />
                    </span>
                    Xu hướng gần đây
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {trending.queries.map((item) => (
                      <button
                        key={item.query}
                        type="button"
                        onClick={() => {
                          setQuery(item.query);
                          void runSearch(item.query, selectedCategory);
                        }}
                        className={chipClass(false)}
                      >
                        {item.query}
                      </button>
                    ))}
                    {trending.pois.map((poi) => (
                      <button
                        key={poi.id}
                        type="button"
                        onClick={() => spotlightPoi(poi, 'trending')}
                        className={chipClass(false)}
                      >
                        {poi.name}
                      </button>
                    ))}
                  </div>
                </div>
              )}

            {/* "Đã lưu" — chỉ hiện khi có gì để hiện. Một mục rỗng kèm
                câu "bạn chưa lưu địa điểm nào" chiếm chỗ vĩnh viễn trên
                panel vốn đã chật, mà không nói thêm được gì.
                ĐỨNG NGOÀI hộp lọc: đặt bên trong thì nó nằm dưới dải
                chip danh mục trong một vùng cuộn riêng, người dùng lưu
                xong không thấy gì xảy ra (đo được khi dựng tính năng). */}
            {savedPlaces.length > 0 && (
              <div className="glass-card flex flex-col gap-2 rounded-3xl p-4">
                <div className="flex items-center gap-2 text-sm font-semibold">
                  <Bookmark className="size-4 text-primary" />
                  <span>Đã lưu</span>
                  <span className="text-xs text-muted-foreground">
                    {savedPlaces.length} địa điểm
                  </span>
                </div>
                <ul className="flex max-h-44 flex-col gap-1 overflow-y-auto">
                  {savedPlaces.map((place) => (
                    <li
                      key={place.id}
                      className="flex items-center gap-2 rounded-xl bg-emerald-50/60 px-2.5 py-2 dark:bg-white/5"
                    >
                      {place.kind === 'home' ? (
                        <Home className="size-3.5 shrink-0 text-primary" aria-hidden />
                      ) : (
                        <Bookmark className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                      )}
                      <button
                        type="button"
                        className="min-w-0 flex-1 text-left"
                        onClick={() => {
                        // Bay tới địa điểm đã lưu. Dùng chính toạ độ đã
                        // lưu chứ không tra lại theo poiId: POI có thể đã
                        // bị lần nhập OSM sau xoá đi (migration 0016 cố ý
                        // giữ lại toạ độ cho đúng trường hợp này).
                        mapRef.current?.flyTo({
                          center: [place.longitude, place.latitude],
                          zoom: 16,
                        });
                        showMapOnMobile();
                        }}
                      >
                        <span className="block truncate text-xs font-medium">
                        {place.kind === 'home' ? `Nhà · ${place.label}` : place.label}
                        </span>
                        {place.address && (
                        <span className="block truncate text-[11px] text-muted-foreground">
                          {place.address}
                        </span>
                        )}
                      </button>
                      <button
                        type="button"
                        className="shrink-0 rounded-md p-1 text-muted-foreground hover:text-foreground"
                        aria-label={`Bỏ lưu ${place.label}`}
                        title="Bỏ lưu"
                        onClick={() => void removeSavedPlace(place)}
                      >
                        <X className="size-3.5" aria-hidden />
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {showDiscovery && recommendations.length > 0 && (
              <div className="shrink-0 space-y-2">
                <div className="flex items-center gap-2 px-1 text-sm font-semibold">
                  <Sparkles className="size-4 text-primary" /> Gợi ý cho bạn
                </div>
                <div className="flex gap-2 overflow-x-auto pb-1">
                  {recommendations.map((poi) => (
                    <button
                      key={poi.id}
                      type="button"
                      onClick={() => spotlightPoi(poi, 'recommendation')}
                      className="w-[188px] shrink-0 rounded-2xl border border-emerald-950/10 bg-white p-3.5 text-left shadow-[0_1px_2px_rgb(14_68_48/6%)] transition-all hover:-translate-y-0.5 hover:border-primary/25 hover:shadow-[0_14px_32px_-10px_rgb(14_68_48/22%)] dark:border-white/10 dark:bg-card"
                    >
                      <p className="truncate text-sm font-semibold">
                        {poi.name}
                      </p>
                      {poi.unexplored && (
                        <span className="mt-1 inline-flex items-center gap-1 rounded-full bg-slate-900 px-2 py-0.5 text-[10px] font-semibold text-emerald-300">
                          <CloudFog className="size-3" aria-hidden /> Vùng mới
                        </span>
                      )}
                      <p className="mt-0.5 line-clamp-2 text-[11px] text-muted-foreground">
                        {poi.reason}
                      </p>
                      <div className="mt-2 flex items-center gap-2 text-[11px]">
                        {poi.rating !== null && (
                          <span className="flex items-center gap-0.5 font-semibold text-amber-600">
                            <Star className="size-3 fill-current" />{' '}
                            {poi.rating.toFixed(1)}
                          </span>
                        )}
                        <span className="text-muted-foreground">
                          {formatMeters(poi.distanceMeters)}
                        </span>
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div className="shrink-0 flex items-center justify-between px-1">
              <h2 className="text-base font-bold tracking-tight">Địa điểm gần bạn</h2>
              <span className="flex items-center gap-1.5 rounded-full bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground">
                {isLoading && <LoaderCircle className="size-3.5 animate-spin" aria-hidden />}
                {isLoading ? 'Đang tìm…' : `${pois.length} kết quả`}
              </span>
            </div>
            <div className="grid shrink-0 gap-3">
              {/* Số hiển thị là VỊ TRÍ TRONG DANH SÁCH ĐANG THẤY, không phải
                  poi.rank. spotlightPoi chèn POI từ trending/gợi ý vào đầu mảng
                  và POI đó không có rank, nên dùng `poi.rank ?? index` sẽ cho
                  hai dòng cùng số 1. Thứ hạng server vẫn được ghi riêng vào
                  telemetry lúc impression — đó mới là số dùng để phân tích
                  position bias, và nó không cần khớp với số đang hiển thị. */}
              {pois.map((poi, index) => (
                <div
                  key={poi.id}
                  className={`group w-full rounded-3xl border bg-white text-left transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_18px_40px_-14px_rgb(14_68_48/25%)] dark:bg-card ${
                    selectedPoiId === poi.id
                      ? 'border-primary/45 shadow-[0_12px_35px_rgb(15_138_98/14%)] ring-4 ring-primary/10'
                      : 'border-emerald-950/[0.08] shadow-[0_1px_2px_rgb(14_68_48/6%)] hover:border-primary/20 dark:border-white/10'
                  }`}
                >
                <button
                  type="button"
                  onClick={() => focusPoi(poi)}
                  aria-label={`Chọn địa điểm ${poi.name}`}
                  className="block w-full rounded-3xl p-4 text-left max-lg:p-3.5"
                >
                  <div className="flex gap-3">
                    <div
                      className={cn(
                        'grid size-10 shrink-0 place-items-center rounded-2xl font-bold tabular-nums',
                        index < 3
                          ? 'brand-mark text-white'
                          : 'bg-emerald-50 text-primary ring-1 ring-emerald-600/10 dark:bg-emerald-500/10',
                      )}
                    >
                      {index + 1}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div className="min-w-0 flex-1 basis-32 break-words">
                          <h3 className="font-semibold leading-tight transition-colors group-hover:text-primary">
                            {poi.name}
                          </h3>
                          <p className="mt-1 line-clamp-1 text-xs text-muted-foreground">
                            {poi.address}
                          </p>
                        </div>
                        <Badge
                          variant="secondary"
                          className="shrink-0 rounded-full"
                        >
                          {poi.categoryLabel}
                        </Badge>
                      </div>
                      <p className="mt-2 line-clamp-2 text-sm text-muted-foreground max-lg:line-clamp-1">
                        {poi.description}
                      </p>
                      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                        {poi.rating === null ? (
                          <span className="text-muted-foreground">
                            Chưa có đánh giá
                          </span>
                        ) : (
                          <>
                            <span className="flex items-center gap-1 font-semibold text-amber-600">
                              <Star className="size-3.5 fill-current" />{' '}
                              {poi.rating.toFixed(1)}
                            </span>
                            <span className="text-muted-foreground">
                              {poi.reviewCount} đánh giá
                            </span>
                          </>
                        )}
                        <span className="ml-auto flex items-center gap-1 font-medium text-primary">
                          <Navigation className="size-3.5" />
                          {formatMeters(poi.distanceMeters)}
                        </span>
                      </div>
                      {/* Tín hiệu riêng của TỪNG POI. traffic đổi theo vị trí
                          nên nằm ở đây, không nằm ở dải cấp truy vấn. */}
                      {(poi.traffic?.isPeakHour ||
                        (poi.liveNearbyUsers ?? 0) > 0 ||
                        poi.trendingScope === 'hex' ||
                        poi.retrievalChannels?.includes('h3')) && (
                        <div className="mt-1 flex flex-wrap gap-1 text-[10px]">
                          {poi.traffic?.isPeakHour && (
                            <span
                              className="rounded-full bg-orange-50 px-1.5 py-0.5 font-medium text-orange-700 dark:bg-orange-500/15 dark:text-orange-300"
                              title={`Giờ cao điểm · thời gian đi đã nhân ${poi.traffic.factor.toFixed(2)} lần`}
                            >
                              Giờ cao điểm
                            </span>
                          )}
                          {(poi.liveNearbyUsers ?? 0) > 0 && (
                            <span
                              className="rounded-full bg-rose-50 px-1.5 py-0.5 font-medium text-rose-700 dark:bg-rose-500/15 dark:text-rose-300"
                              title="Số phiên đang hoạt động trong 300 m quanh địa điểm, đếm bằng GEOSEARCH trên Redis"
                            >
                              {poi.liveNearbyUsers} người quanh đây
                            </span>
                          )}
                          {poi.trendingScope === 'hex' && (
                            <span
                              className="rounded-full bg-amber-50 px-1.5 py-0.5 font-medium text-amber-700 dark:bg-amber-500/15 dark:text-amber-300"
                              title="Đang hot trong chính ô H3 quanh bạn, không phải hot toàn thành phố"
                            >
                              Hot quanh đây
                            </span>
                          )}
                          {poi.retrievalChannels &&
                            poi.retrievalChannels.length > 1 && (
                              <span
                                className="rounded-full bg-muted px-1.5 py-0.5 font-medium text-muted-foreground"
                                title={`Lọt vào ứng viên qua ${poi.retrievalChannels.length} kênh: ${poi.retrievalChannels.join(', ')}`}
                              >
                                {poi.retrievalChannels.length} kênh
                              </span>
                            )}
                        </div>
                      )}
                      {(poi.openNow != null || poi.etaMinutes) && (
                        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                          {poi.openNow === true &&
                          poi.closesInMinutes != null &&
                          poi.closesInMinutes <= 45 ? (
                            <span className="rounded-full bg-amber-50 px-2 py-0.5 font-medium text-amber-700 dark:bg-amber-500/10 dark:text-amber-400">
                              Sắp đóng · {poi.closesInMinutes} phút
                            </span>
                          ) : poi.openNow === true ? (
                            <span className="rounded-full bg-emerald-50 px-2 py-0.5 font-medium text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-400">
                              Đang mở
                            </span>
                          ) : poi.openNow === false ? (
                            <span className="rounded-full bg-muted px-2 py-0.5 font-medium text-muted-foreground">
                              {poi.opensInMinutes != null &&
                              poi.opensInMinutes <= 120
                                ? `Mở sau ${poi.opensInMinutes} phút`
                                : 'Đóng cửa'}
                            </span>
                          ) : null}
                          {poi.etaMinutes && (
                            <span className="flex items-center gap-1 text-muted-foreground">
                              <Bike className="size-3.5" />{' '}
                              {poi.etaMinutes.motorbike} phút
                              <Clock className="ml-0.5 size-3 opacity-60" />
                            </span>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                </button>
                {/* Điện thoại: chỉ đường / xem chi tiết ngay trên thẻ, khỏi phải
                    chạm thẻ để sang bản đồ rồi mới tìm nút. Nằm NGOÀI nút chọn
                    thẻ — hai <button> lồng nhau là HTML sai. */}
                <div className="flex gap-2 px-3.5 pb-3.5 lg:hidden">
                  <Button
                    type="button"
                    className="flex-1 gap-1.5 rounded-xl"
                    onClick={() => startNavigation(poi)}
                  >
                    <Route className="size-4" aria-hidden />
                    Chỉ đường
                  </Button>
                  <Button
                    type="button"
                    variant="secondary"
                    className="flex-1 gap-1.5 rounded-xl"
                    onClick={() => openDetail(poi.id, 'list')}
                  >
                    <Info className="size-4" aria-hidden />
                    Chi tiết
                  </Button>
                </div>
                </div>
              ))}
              {pois.length === 0 && (
                <div className="rounded-3xl border border-dashed border-emerald-900/15 bg-white/60 p-8 text-center dark:border-white/15 dark:bg-card/60">
                  <div className="mx-auto grid size-14 place-items-center rounded-2xl bg-emerald-50 text-primary dark:bg-emerald-500/10">
                    <MapPin className="size-7" />
                  </div>
                  <p className="mt-3 font-medium">Chưa có địa điểm phù hợp</p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Thử từ khóa khác hoặc tăng bán kính tìm kiếm.
                  </p>
                </div>
              )}
            </div>
          </div>
        </aside>

        <section className="nearby-map absolute inset-0 min-w-0 overflow-hidden bg-slate-100 lg:relative lg:inset-auto lg:min-h-0 lg:rounded-[28px] lg:border lg:border-white/80 lg:shadow-[0_24px_60px_-12px_rgb(14_68_48/22%)] lg:ring-1 lg:ring-emerald-950/[0.06] dark:bg-card dark:lg:border-white/10">
          <div className="map-fallback absolute inset-0" aria-hidden="true" />
          <div
            ref={mapContainerRef}
            className="map-canvas-host absolute inset-0"
            aria-label="Bản đồ địa điểm"
          />
          {/* Điện thoại: thanh tìm kiếm nổi trên bản đồ như các app bản đồ
              quen thuộc — chạm vào là sang màn Tìm kiếm với ô nhập đã focus.
              Chú giải màu nhường chỗ cho nó (chỉ hiện từ lg). */}
          <button
            type="button"
            onClick={() => {
              setMobileView('search');
              requestAnimationFrame(() =>
                document
                  .querySelector<HTMLInputElement>('#nearby-search input[role="combobox"]')
                  ?.focus(),
              );
            }}
            className="absolute inset-x-3 top-3 z-10 flex h-12 items-center gap-3 rounded-full border border-white/70 bg-white/95 px-4 text-left text-[15px] text-muted-foreground shadow-[0_6px_24px_rgb(14_68_48/18%)] backdrop-blur-md lg:hidden dark:border-white/10 dark:bg-card/95"
          >
            <Search className="size-5 shrink-0 text-primary" aria-hidden />
            <span className="min-w-0 flex-1 truncate">
              {query.trim() || 'Tìm quán ăn, cà phê, cây xăng…'}
            </span>
            {selectedCategory && (
              <span className="shrink-0 rounded-full bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary">
                {categoryOptions.find((option) => option.category === selectedCategory)?.categoryLabel ?? 'Đã lọc'}
              </span>
            )}
          </button>
          <div className="pointer-events-none absolute left-[4.25rem] top-4 z-10 hidden h-10 items-center rounded-full border border-white/70 bg-white/90 px-4 text-xs shadow-[0_8px_24px_rgb(14_68_48/14%)] backdrop-blur-md lg:flex dark:border-white/10 dark:bg-card/90">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 font-medium">
              <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-full bg-sky-500 ring-2 ring-sky-500/20" /> Vị trí của bạn</span>
              <span className="flex items-center gap-1.5"><span className="flex -space-x-1"><span className="size-2.5 rounded-full bg-orange-500 ring-1 ring-white" /><span className="size-2.5 rounded-full bg-pink-600 ring-1 ring-white" /><span className="size-2.5 rounded-full bg-blue-600 ring-1 ring-white" /></span> POI theo loại</span>
              <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-full bg-emerald-500 ring-2 ring-emerald-500/20" /> Cụm</span>
              <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-full bg-sky-500/60 ring-2 ring-sky-500/15" /> Vành H3</span>
            </div>
          </div>
          {/* Khám phá: AR và sương mù — điện thoại xếp dọc dưới thanh tìm kiếm
              nổi, desktop xếp ngang ở góc trên phải. */}
          <div className="absolute right-3 top-[4.25rem] z-10 flex flex-col items-end gap-2 lg:right-4 lg:top-4 lg:flex-row">
            {isWatching && (
              <button
                type="button"
                onClick={() => setFollowMe((on) => !on)}
                aria-pressed={followMe}
                aria-label={followMe ? 'Tắt bám theo vị trí' : 'Bật bám theo vị trí — bản đồ tự di chuyển theo bạn'}
                title="Bám theo vị trí của tôi"
                className={cn(
                  'flex h-10 items-center gap-1.5 rounded-full border px-3.5 text-sm font-semibold shadow-[0_8px_24px_rgb(14_68_48/14%)] backdrop-blur-md transition-colors',
                  followMe
                    ? 'border-sky-600/30 bg-sky-600 text-white hover:bg-sky-600/90'
                    : 'border-white/70 bg-white/95 text-primary hover:bg-white dark:border-white/10 dark:bg-card/90 dark:hover:bg-card',
                )}
              >
                <Navigation className="size-5" aria-hidden />
                Bám theo
              </button>
            )}
            <button
              type="button"
              onClick={() => setFogOn((on) => !on)}
              aria-pressed={fogOn}
              aria-label={fogOn ? 'Tắt bản đồ sương mù' : 'Bật bản đồ sương mù — đi tới đâu sáng tới đó'}
              title="Bản đồ sương mù"
              className={cn(
                'flex h-10 items-center gap-1.5 rounded-full border px-3.5 text-sm font-semibold shadow-[0_8px_24px_rgb(14_68_48/14%)] backdrop-blur-md transition-colors',
                fogOn
                  ? 'border-slate-900/20 bg-slate-900/90 text-emerald-300 hover:bg-slate-900'
                  : 'border-white/70 bg-white/95 text-primary hover:bg-white dark:border-white/10 dark:bg-card/90 dark:hover:bg-card',
              )}
            >
              <CloudFog className="size-5" aria-hidden />
              Sương mù
            </button>
            <button
              type="button"
              onClick={() => setArOpen(true)}
              aria-label="Khám phá bằng camera (AR)"
              title="Khám phá bằng camera (AR)"
              className="flex h-10 items-center gap-1.5 rounded-full border border-white/70 bg-white/95 px-3.5 text-sm font-semibold text-primary shadow-[0_8px_24px_rgb(14_68_48/14%)] backdrop-blur-md transition-colors hover:bg-white dark:border-white/10 dark:bg-card/90 dark:hover:bg-card"
            >
              <ScanEye className="size-5" aria-hidden />
              AR
            </button>
          </div>
          {/* Điện thoại: "Vị trí của tôi" nổi ở góc dưới phải — vùng ngón cái
              chạm được bằng một tay, thay vì với lên biểu tượng ở góc trên màn
              hình. Ẩn khi thẻ địa điểm đang chiếm đáy bản đồ. */}
          {!selectedPoi && (
            <button
              type="button"
              onClick={requestCurrentLocation}
              aria-label="Vị trí của tôi"
              title="Vị trí của tôi"
              className="absolute bottom-16 right-3 z-10 grid size-12 place-items-center rounded-full border border-white/70 bg-white/95 text-primary shadow-[0_8px_24px_rgb(14_68_48/22%)] backdrop-blur-md transition-colors active:bg-emerald-50 lg:hidden dark:border-white/10 dark:bg-card/95"
            >
              <LocateFixed className="size-6" aria-hidden />
            </button>
          )}
          {fogOn && (
            <div className="absolute left-3 top-[4.25rem] z-10 flex max-w-[calc(100%-9.5rem)] flex-col items-start gap-2 lg:left-4 lg:top-16 lg:max-w-xs">
            <div className="flex w-full items-center gap-2 rounded-2xl border border-slate-900/20 bg-slate-900/90 px-3 py-2 text-white shadow-lg backdrop-blur-md">
              <CloudFog className="size-5 shrink-0 text-emerald-300" aria-hidden />
              <div className="min-w-0 text-xs leading-tight">
                {fogGps === 'denied' ? (
                  <p className="font-semibold">Bật định vị để xua sương mù</p>
                ) : (
                  <>
                    <p className="font-semibold">
                      Đã khám phá{' '}
                      <span className="whitespace-nowrap">
                        {(exploration.overview?.areaKm2 ?? 0).toLocaleString('vi-VN')} km²
                      </span>
                    </p>
                    <p className="text-white/70">
                      {exploration.overview?.cellCount ?? 0} ô
                      {exploration.overview?.todayCount ? ` · +${exploration.overview.todayCount} hôm nay` : ''}
                      {fogGps === 'waiting' ? ' · đang lấy GPS…' : ''}
                    </p>
                  </>
                )}
              </div>
              {(exploration.overview?.cellCount ?? 0) > 0 && (
                <button
                  type="button"
                  onClick={() => {
                    if (window.confirm('Xoá toàn bộ vùng đã khám phá? Không hoàn tác được.')) {
                      void exploration.clear();
                    }
                  }}
                  className="grid size-7 shrink-0 place-items-center rounded-full text-white/60 hover:bg-white/10 hover:text-white"
                  aria-label="Xoá dữ liệu vùng đã khám phá"
                  title="Xoá dữ liệu vùng đã khám phá"
                >
                  <Trash2 className="size-4" aria-hidden />
                </button>
              )}
            </div>
            {exploration.unlocked.length > 0 && (
              <output
                className="flex w-full items-start gap-2 rounded-2xl border border-amber-300/40 bg-amber-400/95 px-3 py-2 text-xs text-slate-900 shadow-lg"
              >
                <Trophy className="mt-0.5 size-4 shrink-0" aria-hidden />
                <div className="min-w-0 flex-1">
                  <p className="font-semibold">Mở khoá mốc mới!</p>
                  {exploration.unlocked.map((milestone) => (
                    <p key={milestone.id} className="truncate">
                      {milestone.title} · {milestone.description}
                    </p>
                  ))}
                </div>
                <button
                  type="button"
                  onClick={exploration.dismissUnlocked}
                  className="grid size-5 shrink-0 place-items-center rounded-full hover:bg-black/10"
                  aria-label="Đóng thông báo mốc"
                >
                  <X className="size-3.5" aria-hidden />
                </button>
              </output>
            )}
            {exploration.pendingCount > 0 && (
              <div className="flex w-full items-center gap-2 rounded-2xl border border-white/10 bg-slate-900/90 px-3 py-1.5 text-[11px] text-white/80 shadow-lg backdrop-blur-md">
                <WifiOff className="size-3.5 shrink-0 text-amber-300" aria-hidden />
                {exploration.pendingCount} điểm chờ gửi — sẽ tự gửi khi có mạng
              </div>
            )}
            {fogGps !== 'denied' && (nextFogMilestone || (exploration.overview?.cellCount ?? 0) > 0) && (
              <div className="w-full rounded-2xl border border-slate-900/20 bg-slate-900/90 px-3 py-2 text-xs text-white shadow-lg backdrop-blur-md">
                {nextFogMilestone ? (
                  <>
                    <p className="flex items-center gap-1.5 font-semibold">
                      <Trophy className="size-3.5 shrink-0 text-amber-300" aria-hidden />
                      <span className="truncate">Mốc kế: {nextFogMilestone.title}</span>
                    </p>
                    <progress
                      className="mt-1.5 block h-1.5 w-full overflow-hidden rounded-full bg-white/15 [&::-moz-progress-bar]:bg-emerald-400 [&::-webkit-progress-bar]:bg-white/15 [&::-webkit-progress-value]:bg-emerald-400"
                      max={nextFogMilestone.goalKm2}
                      value={nextFogMilestone.progressKm2}
                      aria-label={nextFogMilestone.description}
                    />
                    <p className="mt-1 text-white/70">
                      {nextFogMilestone.progressKm2.toLocaleString('vi-VN')} / {nextFogMilestone.goalKm2.toLocaleString('vi-VN')} km²
                    </p>
                  </>
                ) : (
                  <p className="flex items-center gap-1.5 font-semibold">
                    <Trophy className="size-3.5 shrink-0 text-amber-300" aria-hidden />
                    Đã đạt mọi mốc khám phá
                  </p>
                )}
                {(exploration.overview?.cellCount ?? 0) > 0 && (
                  <>
                    <button
                      type="button"
                      onClick={() => setFogDistrictsOpen((open) => !open)}
                      aria-expanded={fogDistrictsOpen}
                      className="mt-2 flex w-full items-center justify-between border-t border-white/10 pt-2 text-white/80 hover:text-white"
                    >
                      <span>Theo quận</span>
                      {fogDistrictsOpen ? (
                        <ChevronUp className="size-4" aria-hidden />
                      ) : (
                        <ChevronDown className="size-4" aria-hidden />
                      )}
                    </button>
                    {fogDistrictsOpen && (
                      <ul className="mt-1.5 max-h-40 space-y-1 overflow-y-auto">
                        {!exploration.districts && <li className="text-white/60">Đang tính…</li>}
                        {exploration.districts?.districts.map((item) => (
                          <li key={item.district} className="flex justify-between gap-2">
                            <span className="truncate">{item.district}</span>
                            <span className="shrink-0 text-white/70">
                              {item.areaKm2.toLocaleString('vi-VN')} km² · {item.cellCount} ô
                            </span>
                          </li>
                        ))}
                        {!!exploration.districts?.unassignedCells && (
                          <li className="flex justify-between gap-2 text-white/50">
                            <span>Ngoài vùng có dữ liệu</span>
                            <span className="shrink-0">{exploration.districts.unassignedCells} ô</span>
                          </li>
                        )}
                      </ul>
                    )}
                  </>
                )}
              </div>
            )}
            {/* Cho sương mù một lý do để bật: chỗ hay gần nhất mà bạn chưa từng tới. */}
            {fogGps !== 'denied' && nextFogTarget && (
              <button
                type="button"
                onClick={() => spotlightPoi(nextFogTarget, 'recommendation')}
                className="flex w-full items-center gap-2 rounded-2xl border border-white/70 bg-white/95 px-3 py-2 text-left text-xs shadow-lg backdrop-blur-md active:bg-emerald-50 dark:border-white/10 dark:bg-card/95"
              >
                <Sparkles className="size-4 shrink-0 text-primary" aria-hidden />
                <span className="min-w-0">
                  <span className="block truncate font-semibold">Xua sương tại {nextFogTarget.name}</span>
                  <span className="text-muted-foreground">
                    Chưa từng tới · {formatMeters(nextFogTarget.distanceMeters)}
                  </span>
                </span>
              </button>
            )}
            </div>
          )}
          {/* Chỉ desktop: điện thoại đã chuyển màn bằng thanh tab dưới đáy. */}
          <button
            type="button"
            aria-label={mapExpanded ? 'Hiện bảng bên trái' : 'Ẩn bảng bên trái'}
            title={mapExpanded ? 'Hiện bảng bên trái' : 'Ẩn bảng bên trái để bản đồ to hơn'}
            aria-expanded={!mapExpanded}
            onClick={() => setMapExpanded((current) => !current)}
            className="absolute left-4 top-4 z-10 hidden size-10 place-items-center rounded-full border border-white/70 bg-white/90 text-foreground shadow-[0_8px_24px_rgb(14_68_48/14%)] backdrop-blur-md transition-colors hover:bg-white hover:text-primary lg:grid dark:border-white/10 dark:bg-card/90 dark:hover:bg-card"
          >
            {mapExpanded ? (
              <PanelLeftOpen className="size-5" />
            ) : (
              <PanelLeftClose className="size-5" />
            )}
          </button>
          {showDebugPanel && (
          <div className="absolute right-4 top-16 z-10 hidden w-[300px] rounded-2xl border border-white/75 bg-slate-950/88 p-4 text-white shadow-2xl backdrop-blur-xl xl:block">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-emerald-300">
                  Client & ingestion
                </p>
                <h2 className="mt-1 font-semibold">Bảng điều khiển tầng 1</h2>
              </div>
              <div className="relative grid size-9 place-items-center rounded-xl bg-emerald-400/15 text-emerald-300">
                <Radio className="size-4" />
                <span className="absolute right-1 top-1 size-1.5 animate-pulse rounded-full bg-emerald-300" />
              </div>
            </div>
            <div className="mt-4 space-y-3 text-xs">
              <div className="flex gap-3">
                <LocateFixed className="mt-0.5 size-4 shrink-0 text-sky-300" />
                <div className="min-w-0">
                  <p className="font-medium text-white">GPS & quyền riêng tư</p>
                  <p className="mt-0.5 truncate text-slate-300">{gpsStatus}</p>
                </div>
              </div>
              <div className="flex gap-3">
                <ShieldCheck className="mt-0.5 size-4 shrink-0 text-violet-300" />
                <div className="min-w-0">
                  <p className="font-medium text-white">API Gateway</p>
                  <p className="mt-0.5 truncate text-slate-300">
                    {gatewayStatus}
                  </p>
                </div>
              </div>
              <div className="flex gap-3">
                <Activity className="mt-0.5 size-4 shrink-0 text-amber-300" />
                <div className="min-w-0">
                  <p className="font-medium text-white">Geo-parser</p>
                  <p className="mt-0.5 truncate text-slate-300">
                    {parserStatus}
                  </p>
                </div>
              </div>
              <div className="flex gap-3">
                <DatabaseZap className="mt-0.5 size-4 shrink-0 text-emerald-300" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <p className="font-medium text-white">Event ingestion</p>
                    {telemetryState.transport === 'online' ? (
                      <CheckCircle2 className="size-3.5 text-emerald-300" />
                    ) : null}
                  </div>
                  <p className="mt-0.5 text-slate-300">
                    {telemetryState.delivered} đã gửi · {telemetryState.queued}{' '}
                    đang chờ ·{' '}
                    {telemetryState.transport === 'online'
                      ? 'Redis Stream'
                      : telemetryState.transport === 'fallback'
                        ? 'Postgres fallback'
                        : telemetryState.transport === 'offline'
                          ? 'ngoại tuyến'
                          : 'sẵn sàng'}
                  </p>
                </div>
              </div>
            </div>
            <div className="mt-4 rounded-xl bg-white/8 px-3 py-2 text-[10px] text-slate-300">
              Session{' '}
              {telemetryState.sessionId
                ? telemetryState.sessionId.slice(0, 8)
                : 'đang tạo'}{' '}
              · batch ≤ 50 events
            </div>
          </div>
          )}
          {selectedPoi && (
            <div
              className={cn(
                'absolute bottom-3 left-3 right-3 z-10 max-h-[42%] overflow-y-auto rounded-3xl border border-white/70 bg-white/92 p-3 shadow-[0_24px_60px_-12px_rgb(14_68_48/30%)] backdrop-blur-xl sm:bottom-5 sm:left-5 sm:right-auto sm:max-h-none sm:w-[360px] sm:overflow-visible sm:p-4 dark:border-white/10 dark:bg-card/95',
                directionsActive && directionsCollapsed && 'p-2 sm:w-[320px] sm:p-2.5',
              )}
            >
              {/* Hai chế độ tách hẳn nhau như Google Maps: chọn POI chỉ hiện
                  THÔNG TIN; bấm "Chỉ đường" (hoặc nút biểu tượng tuyến) mới
                  sang chế độ CHỈ ĐƯỜNG — chọn phương tiện, tính và vẽ tuyến. */}
              {directionsActive && directionsCollapsed ? (
                <div className="flex items-center gap-2">
                  <div className="grid size-8 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">
                    <Route className="size-4" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold">
                      {route && route.poiId === selectedPoi.id
                        ? `${route.durationMinutes} phút · ${formatMeters(route.distanceMeters)}`
                        : routeStatus === 'loading'
                          ? 'Đang tính đường đi…'
                          : 'Chỉ đường'}
                    </p>
                    <p className="truncate text-[11px] text-muted-foreground">
                      Tới {selectedPoi.name}
                    </p>
                  </div>
                  <button
                    type="button"
                    aria-label="Mở rộng thẻ chỉ đường"
                    title="Mở rộng"
                    aria-expanded={false}
                    onClick={() => setDirectionsCollapsed(false)}
                    className="grid size-8 shrink-0 place-items-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  >
                    <ChevronUp className="size-4" />
                  </button>
                  <button
                    type="button"
                    aria-label="Đóng chỉ đường"
                    onClick={() => {
                      setDirectionsPoiId(null);
                      setSelectedPoiId(null);
                    }}
                    className="grid size-8 shrink-0 place-items-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  >
                    <X className="size-4" />
                  </button>
                </div>
              ) : directionsActive ? (
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 items-start gap-2">
                    <button
                      type="button"
                      aria-label="Quay lại thông tin địa điểm"
                      title="Quay lại thông tin địa điểm"
                      onClick={() => setDirectionsPoiId(null)}
                      className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                    >
                      <ArrowLeft className="size-4" />
                    </button>
                    <div className="min-w-0">
                      <Badge variant="secondary">Chỉ đường</Badge>
                      <p className="mt-2 text-xs text-muted-foreground">
                        Từ vị trí của bạn tới
                      </p>
                      <h2 className="text-lg font-bold">{selectedPoi.name}</h2>
                      {directionsAddress && (
                        <p className="mt-0.5 text-sm text-muted-foreground">
                          {directionsAddress}
                        </p>
                      )}
                    </div>
                  </div>
                  <div className="flex shrink-0 items-start gap-1">
                    <button
                      type="button"
                      aria-label="Thu gọn thẻ chỉ đường"
                      title="Thu gọn để xem bản đồ"
                      aria-expanded
                      onClick={() => setDirectionsCollapsed(true)}
                      className="grid size-7 place-items-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                    >
                      <ChevronDown className="size-4" />
                    </button>
                    <button
                      type="button"
                      aria-label="Đóng chỉ đường"
                      onClick={() => {
                        setDirectionsPoiId(null);
                        setSelectedPoiId(null);
                      }}
                      className="grid size-7 place-items-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                    >
                      <X className="size-4" />
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <Badge variant="secondary">Đang chọn</Badge>
                      <h2 className="mt-2 text-lg font-bold">{selectedPoi.name}</h2>
                      <p className="mt-1 text-sm text-muted-foreground">
                        {selectedPoi.address}
                      </p>
                    </div>
                    <div className="flex shrink-0 items-start gap-1.5">
                      <button
                        type="button"
                        aria-label={`Chỉ đường tới ${selectedPoi.name}`}
                        title="Chỉ đường"
                        onClick={() => startNavigation(selectedPoi)}
                        className="grid max-sm:hidden size-10 place-items-center rounded-xl bg-primary text-primary-foreground shadow-sm transition-colors hover:bg-primary/90"
                      >
                        <Route className="size-5" />
                      </button>
                      <button
                        type="button"
                        aria-label="Đóng thẻ địa điểm"
                        onClick={() => setSelectedPoiId(null)}
                        className="grid size-7 place-items-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                      >
                        <X className="size-4" />
                      </button>
                    </div>
                  </div>
                  <div className="mt-3 flex items-center justify-between border-t border-border pt-3 text-sm">
                    <span className="font-medium text-amber-600">
                      {selectedPoi.rating === null
                        ? 'Chưa có đánh giá'
                        : `★ ${selectedPoi.rating.toFixed(1)}`}
                    </span>
                    <span>{formatMeters(selectedPoi.distanceMeters)}</span>
                    <Button size="sm" onClick={() => startNavigation(selectedPoi)}>
                      Chỉ đường
                    </Button>
                  </div>
                </>
              )}
              {directionsActive && !directionsCollapsed && (
                <>
                  {/* Chọn phương tiện — mỗi phương tiện gọi một đồ thị OSRM
                      riêng (car / foot / motorbike, xem docker-compose.yml). Đổi
                      lựa chọn tự kích hoạt lại effect tính tuyến ở trên
                      (transportMode nằm trong deps). */}
                  <div className="mt-3 flex gap-1.5 border-t border-border pt-3">
                    {TRANSPORT_MODES.map((item) => (
                      <button
                        key={item.value}
                        type="button"
                        onClick={() => setTransportMode(item.value)}
                        className={`flex-1 rounded-lg border px-2 py-1.5 text-xs font-medium transition-colors ${
                          transportMode === item.value
                            ? 'border-primary bg-primary/10 text-primary'
                            : 'border-border text-muted-foreground hover:bg-muted'
                        }`}
                      >
                        {item.icon} {item.label}
                      </button>
                    ))}
                  </div>
                  {/* Tuyến đường thật từ OSRM tự dựng. Ba trạng thái còn lại đều nói
                      rõ VÌ SAO chưa có tuyến, thay vì để ô trống — người dùng không
                      phân biệt được "đang tính" với "hỏng" nếu cả hai đều là khoảng
                      trắng. */}
                  {routeStatus === 'loading' && (
                    <p className="mt-3 border-t border-border pt-3 text-xs text-muted-foreground">
                      Đang tính đường đi…
                    </p>
                  )}
                  {routeStatus === 'off' && (
                    <p className="mt-3 border-t border-border pt-3 text-xs text-muted-foreground">
                      Chưa khởi động dữ liệu định tuyến nội bộ.
                    </p>
                  )}
                  {routeStatus === 'none' && (
                    <p className="mt-3 border-t border-border pt-3 text-xs text-muted-foreground">
                      Không tìm được đường bộ tới địa điểm này.
                    </p>
                  )}
                  {route && route.poiId === selectedPoi.id && (
                    <div className="mt-3 space-y-2 border-t border-border pt-3">
                      <div className="flex items-center gap-3">
                        <div className="grid size-9 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">
                          <Route className="size-4" />
                        </div>
                        <div className="min-w-0 flex-1">
                          <p className="text-sm font-semibold">
                            {route.durationMinutes} phút ·{' '}
                            {formatMeters(route.distanceMeters)}
                          </p>
                          {/* Nói rõ đây là ĐƯỜNG ĐI THẬT chứ không phải đường chim
                              bay — con số cũ (etaMinutes) tính bằng khoảng cách
                              thẳng chia vận tốc cố định nên luôn lạc quan.
                              `approximate` (backend bật khi phải mượn đồ thị ô tô)
                              xét TRƯỚC tên hồ sơ: im lặng ở đây là lừa người dùng
                              rằng hệ thống đo đúng phương tiện họ chọn. Phải có
                              nhánh 'motorbike' riêng — thiếu nó thì tuyến xe máy
                              THẬT bị ghi nhãn "hồ sơ ô tô", sai theo hướng ngược
                              lại với cảnh báo xấp xỉ. */}
                          <p className="text-[11px] text-muted-foreground">
                            {route.approximate
                              ? 'Tuyến ô tô (xấp xỉ cho xe máy)'
                              : route.mode === 'foot'
                                ? 'Theo đường thật, hồ sơ đi bộ'
                                : route.mode === 'motorbike'
                                  ? 'Theo đường thật, hồ sơ xe máy'
                                  : 'Theo đường thật, hồ sơ ô tô'}
                            {route.cached ? ' · từ cache' : ''}
                          </p>
                        </div>
                        {route.steps.length > 0 && (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setShowSteps((current) => !current)}
                          >
                            {showSteps ? 'Ẩn' : `${route.steps.length} bước`}
                          </Button>
                        )}
                      </div>
                      {showSteps && (
                        <ol className="max-h-44 overflow-y-auto pr-1 text-xs">
                          {route.steps.map((step, index) => {
                            const visual = stepVisual(step);
                            const StepIcon = visual.icon;
                            const last = index === route.steps.length - 1;
                            return (
                              <li
                                key={`${index}-${step.text}`}
                                className="relative flex items-center gap-2.5 py-1"
                              >
                                {/* Đường nối các icon thành một "dòng thời gian"
                                    chạy dọc từ điểm xuất phát tới nơi. */}
                                {!last && (
                                  <span
                                    aria-hidden
                                    className="absolute left-[13px] top-1/2 h-full w-0.5 bg-gradient-to-b from-primary/30 to-primary/10"
                                  />
                                )}
                                <span
                                  title={visual.label}
                                  className={`relative z-10 grid size-7 shrink-0 place-items-center rounded-full shadow-md ring-2 ring-background ${visual.tone}`}
                                >
                                  <StepIcon className="size-3.5" strokeWidth={2.5} />
                                </span>
                                <span className="flex min-w-0 flex-1 items-center gap-2 rounded-lg bg-muted/60 px-2.5 py-1.5">
                                  <span className="min-w-0 flex-1">{step.text}</span>
                                  {step.distanceMeters > 0 && (
                                    <span className="shrink-0 rounded-full bg-background/80 px-1.5 py-0.5 text-[10px] font-medium tabular-nums text-muted-foreground">
                                      {formatMeters(step.distanceMeters)}
                                    </span>
                                  )}
                                </span>
                              </li>
                            );
                          })}
                        </ol>
                      )}
                    </div>
                  )}
                </>
              )}
              {!directionsActive && (
                <>
                  {/* flex-wrap vì hai nút đều whitespace-nowrap (cva gốc của Button)
                      nên min-width:auto ghim sàn cả hàng ở ~263px, flex-1 co không
                      nổi. Thẻ chỉ rộng "viewport - 104px", tức máy 320-360px còn
                      216-256px: không cho xuống dòng là nút thò ra ngoài viền thẻ,
                      đè lên bản đồ rồi bị overflow-hidden của khung bản đồ cắt cụt
                      chữ. Từ ~367px trở lên vẫn nằm gọn một hàng như cũ. */}
                  {/* Điện thoại: bốn thao tác phụ xếp một hàng, biểu tượng trên nhãn
                      ngắn — thẻ thấp đi một hàng nên che bớt bản đồ. Từ sm trở lên
                      giữ hàng nút nhãn dài như cũ. */}
                  <div className="mt-2 grid grid-cols-4 gap-1.5 sm:flex sm:flex-wrap sm:items-center sm:justify-between sm:gap-2">
                    <Button
                      variant="secondary"
                      size="sm"
                      className="shrink-0 max-sm:h-auto max-sm:flex-col max-sm:gap-0.5 max-sm:py-1.5 max-sm:text-[11px]"
                      onClick={() => openDetail(selectedPoi.id, 'overlay')}
                    >
                      <Info data-icon="inline-start" />
                      <span className="sm:hidden">Chi tiết</span>
                      <span className="max-sm:hidden">Xem chi tiết</span>
                    </Button>
                    <Button
                      variant={
                        savedByPoi.has(selectedPoi.id) ? 'default' : 'outline'
                      }
                      size="sm"
                      className="shrink-0 max-sm:h-auto max-sm:flex-col max-sm:gap-0.5 max-sm:py-1.5 max-sm:text-[11px]"
                      title={
                        savedByPoi.has(selectedPoi.id)
                          ? 'Bỏ khỏi danh sách đã lưu'
                          : 'Lưu địa điểm này'
                      }
                      onClick={() => void toggleSaved(selectedPoi)}
                    >
                      {savedByPoi.has(selectedPoi.id) ? (
                        <BookmarkCheck data-icon="inline-start" />
                      ) : (
                        <Bookmark data-icon="inline-start" />
                      )}
                      {savedByPoi.has(selectedPoi.id) ? 'Đã lưu' : 'Lưu'}
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      className="shrink-0 max-sm:h-auto max-sm:flex-col max-sm:gap-0.5 max-sm:py-1.5 max-sm:text-[11px]"
                      title="Đặt địa điểm này làm nhà"
                      onClick={() => void toggleSaved(selectedPoi, 'home')}
                    >
                      <Home data-icon="inline-start" />
                      <span className="sm:hidden">Nhà</span>
                      <span className="max-sm:hidden">Đặt làm nhà</span>
                    </Button>
                    <Button
                      variant={
                        geofences.has(selectedPoi.id) ? 'default' : 'outline'
                      }
                      size="sm"
                      className="flex-1 max-sm:h-auto max-sm:flex-col max-sm:gap-0.5 max-sm:py-1.5 max-sm:text-[11px]"
                      onClick={() => void toggleGeofence(selectedPoi)}
                    >
                      {geofences.has(selectedPoi.id) ? (
                        <BellRing data-icon="inline-start" />
                      ) : (
                        <Bell data-icon="inline-start" />
                      )}
                      <span className="sm:hidden">
                        {geofences.has(selectedPoi.id) ? 'Đang nhắc' : 'Nhắc tôi'}
                      </span>
                      <span className="max-sm:hidden">
                        {geofences.has(selectedPoi.id)
                          ? 'Đang nhắc · 300 m'
                          : 'Nhắc tôi khi tới gần'}
                      </span>
                    </Button>
                  </div>
                  {geofences.size > 0 && (
                    <p className="mt-2 text-[11px] text-muted-foreground">
                      {proximity.connected
                        ? `Đang chờ thông báo · ${geofences.size} địa điểm`
                        : 'Kênh thông báo chưa kết nối'}
                      {proximity.permission === 'denied' &&
                        ' · trình duyệt đang chặn quyền thông báo'}
                    </p>
                  )}
                </>
              )}
            </div>
          )}
          {/* Panel chi tiết. z-30 để nằm trên "Bảng điều khiển tầng 1" và thẻ
              "Đang chọn" (cả hai z-10) — panel che gần nửa bản đồ, nếu bị hai
              lớp kia đè lên thì chữ chồng chữ. `inset-y-0` cho nó chiều cao xác
              định: panel bên trong dùng size-full + cột flex cuộn trong, thiếu
              chiều cao của cha là nó sập còn 0px.
              w-[92%] trên điện thoại: phủ kín 100% thì panel trông như đã
              chuyển sang một trang khác và người dùng đi tìm nút Lùi thay vì
              nút đóng ngay trên đầu panel. */}
          {detailPoiId && (
            <div className="poi-detail-slide poi-detail-mobile fixed inset-y-0 right-0 z-50 w-full border-l border-emerald-950/10 bg-white shadow-[-20px_0_60px_rgb(14_68_48/18%)] sm:absolute sm:z-30 sm:w-[420px] sm:max-w-full dark:border-white/10 dark:bg-card">
              <PoiDetailPanel
                key={detailPoiId}
                detail={poiDetail}
                photos={poiPhotos}
                loading={detailLoading}
                error={detailError}
                routeSummary={detailRouteSummary}
                isGeofenced={geofences.has(detailPoiId)}
                apiBaseUrl={API_BASE_URL}
                uiLanguage={uiLanguage.language}
                languages={uiLanguage.languages}
                sessionId={telemetryState.sessionId}
                onClose={closeDetail}
                onDirections={() => {
                  if (detailAsPoi) startNavigation(detailAsPoi);
                }}
                onToggleGeofence={() => {
                  if (detailAsPoi) void toggleGeofence(detailAsPoi);
                }}
                onFindParking={() => {
                  if (!poiDetail) return;
                  setParkingOpen(true);
                  // Khung gửi xe nằm ở màn Tìm kiếm trên điện thoại, mà panel
                  // chi tiết thì phủ kín màn hình — phải đóng nó mới thấy.
                  if (window.innerWidth < 1024) {
                    setMobileView('search');
                    if (window.innerWidth < 640) closeDetail();
                  }
                  setParkingRequest({
                    name: poiDetail.name,
                    latitude: poiDetail.latitude,
                    longitude: poiDetail.longitude,
                    nonce: Date.now(),
                  });
                }}
                onSelectSimilar={(poiId) => {
                  // Địa điểm tương tự thường KHÔNG nằm trong `pois` của lần tìm
                  // kiếm hiện tại, nên không gọi focusPoi được (nó tra cứu theo
                  // danh sách đó). Bay bản đồ bằng chính toạ độ panel đang giữ
                  // và để hook nạp phần còn lại.
                  const target = poiDetail?.similar.find(
                    (item) => item.id === poiId,
                  );
                  openDetail(poiId, 'similar');
                  if (target) {
                    mapRef.current?.flyTo({
                      center: [target.longitude, target.latitude],
                      zoom: 15.5,
                      essential: true,
                    });
                  } else {
                    flyToOnDetailRef.current = poiId;
                  }
                }}
                onReviewSubmitted={({ ratingMean, ratingCount }) => {
                  refreshPoiDetail();
                  const updateRating = (items: Poi[]) =>
                    items.map((item) =>
                      item.id === detailPoiId
                        ? {
                            ...item,
                            rating: ratingMean,
                            reviewCount: ratingCount,
                          }
                        : item,
                    );
                  setPois(updateRating);
                  setAreaPois(updateRating);
                  setStatus('Đánh giá của bạn đã được lưu');
                }}
              />
            </div>
          )}
        </section>
        {telemetryState.sessionId && (
          <ChatWidget
            apiBaseUrl={API_BASE_URL}
            sessionId={telemetryState.sessionId}
            position={position}
            accuracyMeters={positionAccuracy}
            language={uiLanguage.language}
            onViewPoi={(poiId) => openDetail(poiId, 'chat')}
            onDirections={directionsFromChat}
            onFocusLocation={(latitude, longitude) => {
              mapRef.current?.flyTo({ center: [longitude, latitude], zoom: 17, essential: true });
              showMapOnMobile();
            }}
            onMapOverlay={setAssistantOverlay}
            onPickOnMap={requestMapPick}
            onOpenVoice={() => setVoiceOpen(true)}
            onSimulatePosition={simulatePosition}
            onSavedChanged={() => void reloadSavedPlaces()}
            onOpenChange={setChatOpen}
          />
        )}
      </section>
      {arOpen && (
        <ArExplorer
          apiBaseUrl={API_BASE_URL}
          sessionId={telemetryState.sessionId}
          fallbackPosition={position}
          onPosition={(point) => void recordExploration(point)}
          onOpenDetail={(poiId) => {
            setArOpen(false);
            void exploration.refresh();
            flyToOnDetailRef.current = poiId;
            openDetail(poiId, 'ar');
          }}
          onClose={() => {
            setArOpen(false);
            // Check-in trong AR cũng mở ô — vẽ lại sương mù cho khớp.
            void exploration.refresh();
          }}
        />
      )}
      {voiceSearchOpen && (
        <VoiceSearch
          language={uiLanguage.language}
          onResult={(spoken) => {
            setQuery(spoken);
            setSuggestionsOpen(false);
            void runSearch(spoken, selectedCategory);
            if (window.innerWidth < 1024) setMobileView('results');
          }}
          onOpenFullMode={() => setVoiceOpen(true)}
          onClose={() => setVoiceSearchOpen(false)}
        />
      )}
      {voiceOpen && (
        <VoiceMode
          apiBaseUrl={API_BASE_URL}
          position={position}
          onClose={() => setVoiceOpen(false)}
          onMapOverlay={setAssistantOverlay}
        />
      )}
      {mapPicking && (
        <div className="fixed left-1/2 top-24 z-50 flex w-[calc(100%-2rem)] max-w-md -translate-x-1/2 items-center justify-between gap-3 rounded-xl bg-slate-900/90 px-4 py-2 text-sm font-medium text-white shadow-lg">
          Chạm lên bản đồ để đặt vị trí
          <button
            type="button"
            onClick={() => requestMapPick(null)}
            className="rounded-full bg-white/15 px-2.5 py-0.5 text-xs hover:bg-white/25"
          >
            Huỷ
          </button>
        </div>
      )}
      {/* Thanh tab dưới đáy (dưới lg) — vùng ngón cái chạm tới được bằng
          một tay. "Trợ lý" bấm hộ nút nổi của ChatWidget (nút đó bị ẩn trên
          màn hẹp, xem globals.css) để không phải kéo state mở/đóng ra ngoài. */}
      <nav
        aria-label="Điều hướng trên điện thoại"
        className="mobile-tabbar z-30 grid shrink-0 grid-cols-4 border-t border-emerald-950/10 bg-white/95 px-2 pt-1 pb-[max(0.25rem,env(safe-area-inset-bottom))] backdrop-blur-xl lg:hidden dark:border-white/10 dark:bg-background/90"
      >
        {(
          [
            { view: 'search', label: 'Tìm kiếm', Icon: Search },
            { view: 'map', label: 'Bản đồ', Icon: MapIcon },
            { view: 'results', label: 'Kết quả', Icon: List },
          ] as const
        ).map(({ view, label, Icon }) => {
          const active = mobileView === view;
          return (
            <button
              key={view}
              type="button"
              onClick={() => setMobileView(view)}
              aria-current={active ? 'page' : undefined}
              className={cn(
                'mobile-tab flex flex-col items-center justify-center gap-0.5 rounded-xl py-1 text-[11px] font-medium transition-colors',
                active ? 'text-primary' : 'text-muted-foreground',
              )}
            >
              <span
                className={cn(
                  'relative grid h-7 w-14 place-items-center rounded-full transition-colors',
                  active && 'bg-primary/12',
                )}
              >
                <Icon className="size-5" aria-hidden />
                {view === 'results' && pois.length > 0 && (
                  <span className="absolute -top-1 right-1.5 grid h-4 min-w-4 place-items-center rounded-full bg-primary px-1 text-[10px] font-bold leading-none text-primary-foreground">
                    {pois.length > 99 ? '99+' : pois.length}
                  </span>
                )}
              </span>
              {label}
            </button>
          );
        })}
        <button
          type="button"
          onClick={() => document.querySelector<HTMLButtonElement>('.chat-launcher')?.click()}
          // ChatWidget chỉ được dựng khi đã có sessionId — trước đó bấm vào
          // không có gì để mở, nên làm mờ thay vì để một nút "chết".
          disabled={!telemetryState.sessionId}
          className="mobile-tab flex flex-col items-center justify-center gap-0.5 rounded-xl py-1 text-[11px] font-medium text-muted-foreground disabled:opacity-40"
        >
          <span className="grid h-7 w-14 place-items-center rounded-full">
            <MessageCircle className="size-5" aria-hidden />
          </span>
          Trợ lý
        </button>
      </nav>
    </main>
  );
}

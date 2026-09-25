// Kiểu dữ liệu + định dạng dùng chung cho tính năng gửi xe — xem
// backend/app/parking.py.

export type Vehicle = 'motorbike' | 'car' | 'bicycle' | 'ev';
export type PriceUnit = 'turn' | 'hour' | 'day' | 'night' | 'month' | 'kwh';
export type Support = 'yes' | 'no' | 'unknown';

export type ParkingPrice = {
  tier: 'community' | 'openstreetmap' | 'published' | 'regulated' | 'reference' | 'unknown';
  amountVnd: number | null;
  /** có khi giá phụ thuộc khu vực/nhóm mà dữ liệu không nói rõ → hiện khoảng */
  amountMinVnd?: number;
  estimatedCostMin?: number;
  progressive?: boolean;
  unit: PriceUnit | null;
  estimatedCost: number | null;
  unitAssumed?: boolean;
  free?: boolean;
  reports?: number;
  agreement?: number;
  lastReportedAt?: string;
  raw?: string | null;
  period?: string;
  legalReference?: { document: string; status: string; url: string } | null;
};

export type ParkingHours = {
  raw: string | null;
  source: 'community' | 'openstreetmap' | null;
  openNow: boolean | null;
  closesInMinutes: number | null;
  opensInMinutes: number | null;
  openThroughout: boolean | null;
};

export type Socket = { type: string; count: number | null; powerKw: number | null };

export type ParkingResult = {
  id: string;
  name: string;
  address: string;
  category: string;
  latitude: number;
  longitude: number;
  distanceMeters: number;
  walkMeters: number;
  walkMinutes: number;
  kind: 'parking' | 'charging_station';
  vehicles: { motorbike: Support; car: Support; bicycle: Support };
  vehicleSupport: Support;
  evCharging: boolean;
  price: ParkingPrice;
  hours: ParkingHours;
  capacity: number | null;
  parkingType: string | null;
  operator: string | null;
  sockets: Socket[];
  reportCount: number;
  score: number;
  scoreBreakdown: { walk: number; cost: number; uncertainty: number };
};

export type ParkingSearchResponse = {
  vehicle: Vehicle;
  minutes: number;
  candidates: number;
  excludedClosed: number;
  results: ParkingResult[];
};

export type ParkingDetail = {
  poiId: string;
  kind: 'parking' | 'charging_station';
  vehicles: { motorbike: Support; car: Support; bicycle: Support };
  prices: Partial<Record<Vehicle, ParkingPrice>>;
  hours: ParkingHours;
  capacity: number | null;
  parkingType: string | null;
  access: string | null;
  operator: string | null;
  sockets: Socket[];
  priceRaw: string | null;
  dataSource: string;
  reportCount: number;
  minutes: number;
};

export const VEHICLE_LABELS: Record<Vehicle, string> = {
  motorbike: 'Xe máy',
  car: 'Ô tô',
  bicycle: 'Xe đạp',
  ev: 'Xe điện (sạc)',
};

export const UNIT_LABELS: Record<PriceUnit, string> = {
  turn: 'lượt',
  hour: 'giờ',
  day: 'ngày',
  night: 'đêm',
  month: 'tháng',
  kwh: 'kWh',
};

export const DURATION_OPTIONS = [
  { minutes: 30, label: '30 phút' },
  { minutes: 60, label: '1 giờ' },
  { minutes: 120, label: '2 giờ' },
  { minutes: 240, label: '4 giờ' },
  { minutes: 480, label: '8 giờ' },
  { minutes: 720, label: 'Qua đêm (12 giờ)' },
];

export const TIER_STYLES: Record<ParkingPrice['tier'], { label: string; className: string }> = {
  community: {
    label: 'Người dùng báo',
    className: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300',
  },
  openstreetmap: {
    label: 'Theo OpenStreetMap',
    className: 'bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300',
  },
  published: {
    label: 'Giá niêm yết',
    className: 'bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300',
  },
  regulated: {
    label: 'Phí theo quy định',
    className: 'bg-violet-100 text-violet-800 dark:bg-violet-950 dark:text-violet-300',
  },
  // QĐ 35/2018 đã bãi bỏ từ 16/01/2026 — nhãn phải nói rõ là tham khảo.
  reference: {
    label: 'Tham khảo (khung giá cũ, đã bãi bỏ)',
    className: 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300',
  },
  unknown: {
    label: 'Chưa rõ giá',
    className: 'bg-muted text-muted-foreground',
  },
};

export function formatVnd(amount: number): string {
  return `${amount.toLocaleString('vi-VN')}đ`;
}

function formatRange(min: number | undefined, max: number): string {
  return min !== undefined && min !== max
    ? `${min.toLocaleString('vi-VN')}–${formatVnd(max)}`
    : formatVnd(max);
}

/** "5.000đ/lượt", "4.000–6.000đ/lượt", "20.000–25.000đ/giờ đầu, lũy tiến", "Miễn phí". */
export function formatPrice(price: ParkingPrice): string {
  if (price.free) return 'Miễn phí';
  if (price.amountVnd === null || price.unit === null) return 'Chưa rõ giá';
  const amount = formatRange(price.amountMinVnd, price.amountVnd);
  if (price.progressive) return `${amount}/giờ đầu, lũy tiến`;
  return `${amount}/${UNIT_LABELS[price.unit]}`;
}

/** Tiền ước tính cho đúng lần gửi này — `null` khi không quy ra được. */
export function formatEstimatedCost(price: ParkingPrice): string | null {
  if (price.estimatedCost === null || price.estimatedCost === undefined || price.free) return null;
  return formatRange(price.estimatedCostMin, price.estimatedCost);
}

export function formatHours(hours: ParkingHours): string {
  if (hours.openThroughout === true) {
    return hours.raw === '24/7' ? 'Mở 24/7' : 'Mở suốt thời gian gửi';
  }
  if (hours.openThroughout === false) return 'Đóng cửa trong lúc gửi';
  if (hours.openNow === true) return 'Đang mở';
  return 'Chưa rõ giờ mở cửa';
}

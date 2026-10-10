'use client';

import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent } from 'react';
import {
  Camera,
  CameraOff,
  Coffee,
  Compass,
  Footprints,
  Landmark,
  LoaderCircle,
  MapPin,
  Palette,
  Smartphone,
  Star,
  Trees,
  Trophy,
  Utensils,
  X,
  type LucideIcon,
} from 'lucide-react';

import { useWakeLock } from '@/hooks/use-wake-lock';
import { distanceMeters, formatMeters } from '@/lib/assistant';
import { authHeaders } from '@/lib/auth';
import { cn } from '@/lib/utils';

/**
 * Chế độ "Khám phá AR": giơ camera sau lên là thấy thẻ địa điểm nổi đúng hướng.
 *
 * Không dùng WebXR (Safari iOS không có) — chỉ ghép ba thứ trình duyệt nào cũng
 * có: video camera làm nền, GPS cho vị trí, cảm biến hướng cho góc camera. Mỗi
 * POI đặt theo GÓC LỆCH giữa hướng camera và hướng tới POI, nên đây là AR "theo
 * vị trí" chứ không bám hình — GPS lệch 10-20 m và la bàn trôi vài độ, thẻ chỉ
 * chỉ đúng phía, không dính vào mặt tiền. Vì vậy chỉ đặt thẻ cho POI cách
 * >= MIN_AR_DISTANCE; gần hơn thì ghi "ngay quanh bạn" ở khay dưới.
 *
 * Máy không có cảm biến hướng (laptop) thì kéo màn hình để xoay — đủ để demo.
 *
 * Check-in: `POST /api/v1/checkins` (backend/app/checkins.py). SERVER đo khoảng
 * cách bằng PostGIS và quyết định — khoảng cách ở đây chỉ để hiển thị. Chỉ gửi
 * khi có GPS thật, không bao giờ gửi vị trí dự phòng của bản đồ. Huy hiệu do
 * server tính; check-in đi theo tài khoản nếu đã đăng nhập, như "Đã lưu".
 */

type ArPoi = {
  id: string;
  name: string;
  categoryLabel: string;
  latitude: number;
  longitude: number;
  rating: number | null;
  reviewCount: number;
};

type Position = { latitude: number; longitude: number };

type Placed = ArPoi & { distance: number; bearing: number };

type Badge = {
  id: string;
  title: string;
  description: string;
  icon: string;
  goal: number;
  progress: number;
  earned: boolean;
};

type CheckInSummary = {
  total: number;
  checkins: { poiId: string | null; name: string; categoryLabel: string; checkedInAt: string }[];
  badges: Badge[];
};

type CheckInResponse = Partial<CheckInSummary> & {
  status: 'checked_in' | 'already' | 'too_far' | 'not_allowed';
  distanceMeters?: number;
  allowedMeters?: number;
  unlocked?: Badge[];
};

const BADGE_ICONS: Record<string, LucideIcon> = {
  footprints: Footprints,
  coffee: Coffee,
  utensils: Utensils,
  landmark: Landmark,
  trees: Trees,
  palette: Palette,
  compass: Compass,
};

const RADIUS_OPTIONS = [300, 600, 1_200] as const;
const MIN_AR_DISTANCE = 25;
/** Bán kính check-in nhỏ nhất của server (`CHECKIN_RADIUS_METERS`) — chỉ để
 *  ghi trong lời giới thiệu; server mới là bên quyết định. */
const CHECKIN_RADIUS = 50;
/** Xa hơn mức này thì kể cả khu đất rộng nhất (công viên 350 m + sai số) cũng
 *  không đạt — khoá nút luôn, đỡ một request chắc chắn bị từ chối. */
const CHECKIN_HOPELESS_METERS = 400;
const REFETCH_AFTER_METERS = 40;
const MAX_CARDS = 14;
const LANE_HEIGHT = 70;
const LANE_GAP_PX = 150;
const MAX_LANES = 4;
const TOP_SAFE_PX = 72;
const BOTTOM_SAFE_PX = 170;
/** FOV ngang của cạnh DÀI cảm biến camera sau điện thoại phổ thông (độ). */
const CAMERA_LONG_FOV = 63;
const FALLBACK_FOV = 60;
/** Hệ số làm mượt hướng mỗi lần cảm biến báo — nhỏ thì êm nhưng trễ. */
const SMOOTHING = 0.18;

const toRad = (deg: number) => (deg * Math.PI) / 180;
const toDeg = (rad: number) => (rad * 180) / Math.PI;
const wrap360 = (deg: number) => ((deg % 360) + 360) % 360;
/** Góc lệch có dấu trong (-180, 180]. */
const wrap180 = (deg: number) => {
  const d = wrap360(deg);
  return d > 180 ? d - 360 : d;
};

function bearingBetween(from: Position, to: Position): number {
  const φ1 = toRad(from.latitude);
  const φ2 = toRad(to.latitude);
  const Δλ = toRad(to.longitude - from.longitude);
  const y = Math.sin(Δλ) * Math.cos(φ2);
  const x = Math.cos(φ1) * Math.sin(φ2) - Math.sin(φ1) * Math.cos(φ2) * Math.cos(Δλ);
  return wrap360(toDeg(Math.atan2(y, x)));
}

/**
 * Hướng và góc ngẩng của CAMERA SAU (trục -z của máy) từ alpha/beta/gamma.
 * Ma trận xoay Z-X'-Y'' theo spec DeviceOrientation; hệ trái đất x = đông,
 * y = bắc, z = lên. Khác `use-heading.ts`: hook đó lấy hướng ĐỈNH máy (cầm
 * nằm ngang), còn AR cầm máy dựng đứng nên phải lấy hướng mặt lưng.
 */
function cameraPose(alpha: number, beta: number, gamma: number) {
  const a = toRad(alpha);
  const b = toRad(beta);
  const g = toRad(gamma);
  const vx = -(Math.cos(a) * Math.sin(g) + Math.sin(a) * Math.sin(b) * Math.cos(g));
  const vy = -(Math.sin(a) * Math.sin(g) - Math.cos(a) * Math.sin(b) * Math.cos(g));
  const vz = -(Math.cos(b) * Math.cos(g));
  return {
    heading: wrap360(toDeg(Math.atan2(vx, vy))),
    pitch: toDeg(Math.asin(Math.max(-1, Math.min(1, vz)))),
  };
}

type Props = {
  apiBaseUrl: string;
  /** Phiên ẩn danh — chủ sở hữu check-in khi chưa đăng nhập. */
  sessionId: string | null;
  /** Vị trí bản đồ đang dùng — chỉ để hiện thẻ khi GPS chưa có/bị từ chối. */
  fallbackPosition: Position;
  /** Mỗi lần GPS thật báo vị trí — để bản đồ sương mù ghi ô đã đi qua. */
  onPosition?: (point: { latitude: number; longitude: number; accuracy: number }) => void;
  onOpenDetail: (poiId: string) => void;
  onClose: () => void;
};

export function ArExplorer({
  apiBaseUrl,
  sessionId,
  fallbackPosition,
  onPosition,
  onOpenDetail,
  onClose,
}: Props) {
  const [started, setStarted] = useState(false);
  const [cameraState, setCameraState] = useState<'off' | 'on' | 'denied'>('off');
  const [sensorMode, setSensorMode] = useState<'waiting' | 'device' | 'drag'>('waiting');
  const [gps, setGps] = useState<{ position: Position; accuracy: number } | null>(null);
  const [gpsDenied, setGpsError] = useState(false);
  const [pose, setPose] = useState({ heading: 0, pitch: 0 });
  const [radius, setRadius] = useState<(typeof RADIUS_OPTIONS)[number]>(600);
  const [pois, setPois] = useState<ArPoi[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [checkInSummary, setCheckInSummary] = useState<CheckInSummary | null>(null);
  const [checkingIn, setCheckingIn] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ text: string; tone: 'success' | 'info' } | null>(null);
  const [showBadges, setShowBadges] = useState(false);
  const [viewport, setViewport] = useState({ width: 390, height: 800, fov: FALLBACK_FOV });

  const rootRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  // Hướng làm mượt giữ dạng vector (sin, cos): trung bình thẳng trên độ thì
  // 359° và 1° ra 180° — thẻ quay ngược một vòng mỗi lần đi qua hướng bắc.
  const smoothRef = useRef<{ x: number; y: number; pitch: number } | null>(null);
  const dragRef = useRef<{ x: number; y: number; heading: number; pitch: number } | null>(null);
  const fetchedAtRef = useRef<Position | null>(null);

  useWakeLock(started);

  const gpsError = gpsDenied || (started && !navigator.geolocation);
  const position = gps?.position ?? fallbackPosition;
  const usingFallback = !gps;

  // --- Camera ---------------------------------------------------------------
  const startCamera = useCallback(async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      setCameraState('denied');
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 } },
        audio: false,
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => undefined);
      }
      setCameraState('on');
    } catch {
      setCameraState('denied');
    }
  }, []);

  useEffect(
    () => () => {
      streamRef.current?.getTracks().forEach((track) => track.stop());
    },
    [],
  );

  // --- Bắt đầu: phải nằm trong thao tác người dùng (iOS xin quyền la bàn) ---
  const start = useCallback(() => {
    const ask = (
      typeof DeviceOrientationEvent !== 'undefined'
        ? (DeviceOrientationEvent as unknown as { requestPermission?: () => Promise<string> })
            .requestPermission
        : undefined
    );
    void ask?.call(DeviceOrientationEvent).catch(() => undefined);
    setStarted(true);
    void startCamera();
  }, [startCamera]);

  // --- GPS ------------------------------------------------------------------
  // Qua ref: bên gọi truyền arrow function mới mỗi lần render, đưa thẳng vào
  // deps thì mỗi lần render lại huỷ rồi đăng ký lại watchPosition.
  const onPositionRef = useRef(onPosition);
  useEffect(() => {
    onPositionRef.current = onPosition;
  }, [onPosition]);

  useEffect(() => {
    if (!started || !navigator.geolocation) return;
    const id = navigator.geolocation.watchPosition(
      (pos) => {
        setGpsError(false);
        setGps({
          position: { latitude: pos.coords.latitude, longitude: pos.coords.longitude },
          accuracy: pos.coords.accuracy,
        });
        onPositionRef.current?.({
          latitude: pos.coords.latitude,
          longitude: pos.coords.longitude,
          accuracy: pos.coords.accuracy,
        });
      },
      () => setGpsError(true),
      { enableHighAccuracy: true, maximumAge: 2_000, timeout: 15_000 },
    );
    return () => navigator.geolocation.clearWatch(id);
  }, [started]);

  // --- Cảm biến hướng -------------------------------------------------------
  useEffect(() => {
    if (!started) return;
    let gotEvent = false;
    let hasAbsolute = false;

    const feed = (heading: number, pitch: number) => {
      gotEvent = true;
      const h = toRad(wrap360(heading + (screen.orientation?.angle ?? 0)));
      const prev = smoothRef.current;
      smoothRef.current = prev
        ? {
            x: prev.x + (Math.sin(h) - prev.x) * SMOOTHING,
            y: prev.y + (Math.cos(h) - prev.y) * SMOOTHING,
            pitch: prev.pitch + (pitch - prev.pitch) * SMOOTHING,
          }
        : { x: Math.sin(h), y: Math.cos(h), pitch };
    };

    // Chrome Android: alpha tuyệt đối (so với bắc thật).
    const onAbsolute = (event: Event) => {
      const { alpha, beta, gamma } = event as DeviceOrientationEvent;
      if (alpha == null || beta == null || gamma == null) return;
      hasAbsolute = true;
      const p = cameraPose(alpha, beta, gamma);
      feed(p.heading, p.pitch);
    };
    // Safari iOS: alpha tương đối, nhưng có webkitCompassHeading đã bù độ
    // nghiêng (cầm dựng đứng thì là hướng mặt lưng máy). Góc ngẩng không phụ
    // thuộc alpha nên vẫn tính từ beta/gamma được.
    const onOrientation = (event: Event) => {
      if (hasAbsolute) return;
      const e = event as DeviceOrientationEvent & { webkitCompassHeading?: number };
      if (e.beta == null || e.gamma == null) return;
      const pitch = cameraPose(0, e.beta, e.gamma).pitch;
      if (typeof e.webkitCompassHeading === 'number' && e.webkitCompassHeading >= 0) {
        feed(e.webkitCompassHeading, pitch);
      } else if (e.absolute && e.alpha != null) {
        feed(cameraPose(e.alpha, e.beta, e.gamma).heading, pitch);
      }
    };

    window.addEventListener('deviceorientationabsolute', onAbsolute);
    window.addEventListener('deviceorientation', onOrientation);
    // Không có sự kiện nào sau 1,5 s: máy không có cảm biến -> kéo để xoay.
    const timer = setTimeout(() => setSensorMode(gotEvent ? 'device' : 'drag'), 1_500);

    let frame = 0;
    const tick = () => {
      const s = smoothRef.current;
      if (s) {
        const heading = wrap360(toDeg(Math.atan2(s.x, s.y)));
        setPose((prev) =>
          Math.abs(wrap180(prev.heading - heading)) < 0.2 && Math.abs(prev.pitch - s.pitch) < 0.2
            ? prev
            : { heading, pitch: s.pitch },
        );
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);

    return () => {
      clearTimeout(timer);
      cancelAnimationFrame(frame);
      window.removeEventListener('deviceorientationabsolute', onAbsolute);
      window.removeEventListener('deviceorientation', onOrientation);
    };
  }, [started]);

  // Kéo để xoay (máy không có cảm biến).
  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (sensorMode !== 'drag') return;
    // Nhấn trúng nút (X, huy hiệu…) thì không kéo: đã capture pointer thì
    // trình duyệt gửi `click` cho lớp phủ chứ không cho nút — nút bấm không ăn.
    if ((event.target as Element).closest('button, a, input, select')) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = { x: event.clientX, y: event.clientY, heading: pose.heading, pitch: pose.pitch };
  };
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag || sensorMode !== 'drag') return;
    // Lỡ mất pointerup (thả chuột ngoài cửa sổ) thì di chuột không được xoay tiếp.
    if (event.buttons === 0) {
      dragRef.current = null;
      return;
    }
    const degPerPx = viewport.fov / viewport.width;
    const heading = wrap360(drag.heading - (event.clientX - drag.x) * degPerPx);
    const pitch = Math.max(-30, Math.min(30, drag.pitch + (event.clientY - drag.y) * degPerPx));
    const h = toRad(heading);
    smoothRef.current = { x: Math.sin(h), y: Math.cos(h), pitch };
  };
  const onPointerUp = () => {
    dragRef.current = null;
  };

  // --- Kích thước khung & FOV -----------------------------------------------
  useEffect(() => {
    if (!started) return;
    const measure = () => {
      const root = rootRef.current;
      if (!root) return;
      const width = root.clientWidth;
      const height = root.clientHeight;
      const video = videoRef.current;
      let fov = FALLBACK_FOV;
      if (cameraState === 'on' && video && video.videoWidth > 0) {
        const vw = video.videoWidth;
        const vh = video.videoHeight;
        const halfLong = toRad(CAMERA_LONG_FOV / 2);
        // FOV ngang của chính khung video (dọc thì cạnh ngang là cạnh ngắn).
        const videoH = vw >= vh ? halfLong : Math.atan(Math.tan(halfLong) * (vw / vh));
        // object-cover cắt bớt hai bên: phần nhìn thấy hẹp hơn khung video.
        const scale = Math.max(width / vw, height / vh);
        fov = 2 * toDeg(Math.atan(Math.tan(videoH) * (width / (vw * scale))));
      }
      setViewport({ width, height, fov });
    };
    measure();
    const video = videoRef.current;
    video?.addEventListener('loadedmetadata', measure);
    window.addEventListener('resize', measure);
    return () => {
      video?.removeEventListener('loadedmetadata', measure);
      window.removeEventListener('resize', measure);
    };
  }, [started, cameraState]);

  // --- Nạp POI quanh vị trí -------------------------------------------------
  const lat = position.latitude;
  const lng = position.longitude;
  useEffect(() => {
    if (!started) return;
    const last = fetchedAtRef.current;
    if (last && distanceMeters(last, { latitude: lat, longitude: lng }) < REFETCH_AFTER_METERS) return;
    const controller = new AbortController();
    setLoading(true);
    const params = new URLSearchParams({
      lat: lat.toFixed(6),
      lng: lng.toFixed(6),
      radius: String(radius),
      limit: '80',
    });
    fetch(`${apiBaseUrl}/api/pois/nearby?${params}`, { signal: controller.signal })
      .then((res) => (res.ok ? (res.json() as Promise<ArPoi[]>) : Promise.reject()))
      .then((data) => {
        fetchedAtRef.current = { latitude: lat, longitude: lng };
        setPois(data);
      })
      .catch(() => undefined)
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [apiBaseUrl, started, lat, lng, radius]);

  // Check-in & huy hiệu của người dùng — nạp một lần khi mở.
  useEffect(() => {
    if (!sessionId) return;
    const controller = new AbortController();
    fetch(`${apiBaseUrl}/api/v1/checkins`, {
      headers: { 'X-Session-ID': sessionId, ...authHeaders() },
      signal: controller.signal,
    })
      .then((res) => (res.ok ? (res.json() as Promise<CheckInSummary>) : Promise.reject()))
      .then(setCheckInSummary)
      // Không nạp được thì bộ đếm hiện 0 — check-in mới vẫn gửi bình thường.
      .catch(() => undefined);
    return () => controller.abort();
  }, [apiBaseUrl, sessionId]);

  // Đổi bán kính thì buộc nạp lại dù chưa đi đủ xa.
  const changeRadius = (next: (typeof RADIUS_OPTIONS)[number]) => {
    fetchedAtRef.current = null;
    setRadius(next);
  };

  const placed: Placed[] = useMemo(
    () =>
      pois
        .map((poi) => ({
          ...poi,
          distance: distanceMeters(position, poi),
          bearing: bearingBetween(position, poi),
        }))
        .filter((poi) => poi.distance <= radius)
        .sort((a, b) => a.distance - b.distance),
    [pois, position, radius],
  );

  const nearby = placed.filter((poi) => poi.distance < MIN_AR_DISTANCE);

  // Xếp thẻ: gần trước, mỗi thẻ vào làn thấp nhất chưa có thẻ nào chồng ngang.
  const cards = useMemo(() => {
    const { width, height, fov } = viewport;
    const pxPerDeg = width / fov;
    const horizonY = height / 2 + pose.pitch * pxPerDeg;
    const lanes: number[][] = [];
    const out: { poi: Placed; x: number; y: number; scale: number }[] = [];
    for (const poi of placed) {
      if (out.length >= MAX_CARDS) break;
      if (poi.distance < MIN_AR_DISTANCE) continue;
      const offset = wrap180(poi.bearing - pose.heading);
      if (Math.abs(offset) > fov / 2 + 4) continue;
      const x = width / 2 + offset * pxPerDeg;
      let lane = 0;
      while (lane < MAX_LANES && (lanes[lane] ?? []).some((other) => Math.abs(other - x) < LANE_GAP_PX)) {
        lane += 1;
      }
      if (lane >= MAX_LANES) continue;
      (lanes[lane] ??= []).push(x);
      // Xa thì nổi cao hơn đường chân trời một chút và nhỏ hơn — gợi phối cảnh.
      const t = Math.min(1, poi.distance / radius);
      // Kẹp giữa thanh trên và khay dưới: màn thấp (laptop, điện thoại ngang)
      // thì làn trên cùng chui xuống dưới header.
      const y = Math.max(
        TOP_SAFE_PX + 60,
        Math.min(height - BOTTOM_SAFE_PX, horizonY - 20 - t * 70 - lane * LANE_HEIGHT),
      );
      out.push({ poi, x, y, scale: 1 - t * 0.25 });
    }
    return out;
  }, [placed, pose, viewport, radius]);

  const selected = placed.find((poi) => poi.id === selectedId) ?? null;
  const checkedIds = useMemo(
    () => new Set((checkInSummary?.checkins ?? []).map((item) => item.poiId)),
    [checkInSummary],
  );
  const canCheckIn = (poi: Placed) =>
    !!gps && !!sessionId && poi.distance <= CHECKIN_HOPELESS_METERS && checkingIn === null;

  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(null), 4_000);
    return () => clearTimeout(timer);
  }, [notice]);

  const checkIn = async (poi: Placed) => {
    if (!gps || !sessionId) return;
    setCheckingIn(poi.id);
    try {
      const response = await fetch(`${apiBaseUrl}/api/v1/checkins`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Session-ID': sessionId, ...authHeaders() },
        body: JSON.stringify({
          poi_id: poi.id,
          latitude: gps.position.latitude,
          longitude: gps.position.longitude,
          accuracy_meters: gps.accuracy,
        }),
      });
      if (!response.ok) {
        setNotice({ text: 'Không check-in được lúc này — thử lại sau', tone: 'info' });
        return;
      }
      const result = (await response.json()) as CheckInResponse;
      if (result.badges && result.checkins && result.total != null) {
        setCheckInSummary({ total: result.total, checkins: result.checkins, badges: result.badges });
      }
      if (result.status === 'checked_in') {
        navigator.vibrate?.(result.unlocked?.length ? [60, 80, 120] : 60);
        const badge = result.unlocked?.[0];
        setNotice({
          text: badge ? `🏆 Mở khoá huy hiệu "${badge.title}"!` : `Đã check-in ${poi.name}`,
          tone: 'success',
        });
      } else if (result.status === 'already') {
        setNotice({ text: 'Bạn đã check-in nơi này rồi', tone: 'info' });
      } else if (result.status === 'too_far') {
        const left = Math.max(1, (result.distanceMeters ?? 0) - (result.allowedMeters ?? 0));
        setNotice({ text: `Còn cách khoảng ${formatMeters(left)} — đi gần thêm rồi thử lại`, tone: 'info' });
      } else if (result.status === 'not_allowed') {
        setNotice({ text: 'Loại địa điểm này không tính check-in', tone: 'info' });
      }
    } catch {
      setNotice({ text: 'Mất kết nối — check-in chưa được ghi', tone: 'info' });
    } finally {
      setCheckingIn(null);
    }
  };

  const discovered = checkInSummary?.total ?? 0;
  const flatPhone = sensorMode === 'device' && pose.pitch < -50;

  return (
    <div
      ref={rootRef}
      className="fixed inset-0 z-[60] touch-none select-none overflow-hidden bg-slate-950 text-white"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      // Lớp phủ toàn màn hình như VoiceMode, không dùng <dialog> gốc.
      // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role
      role="dialog"
      aria-modal="true"
      aria-label="Khám phá AR"
    >
      <video
        ref={videoRef}
        className={cn('absolute inset-0 size-full object-cover', cameraState !== 'on' && 'hidden')}
        playsInline
        muted
        autoPlay
      />
      {cameraState !== 'on' && (
        <div
          className="absolute inset-0 bg-[radial-gradient(ellipse_at_50%_120%,#0f8a62_0%,#0b2b22_45%,#020617_100%)]"
          aria-hidden
        />
      )}

      {/* Thanh trên */}
      <div className="absolute inset-x-0 top-0 z-20 flex items-center gap-2 bg-gradient-to-b from-black/70 to-transparent px-4 pt-[max(0.75rem,env(safe-area-inset-top))] pb-6">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <span className="grid size-9 shrink-0 place-items-center rounded-full bg-white/15 backdrop-blur">
            <Compass className="size-5" style={{ transform: `rotate(${-pose.heading}deg)` }} aria-hidden />
          </span>
          <div className="min-w-0 leading-tight">
            <p className="text-sm font-semibold">Khám phá AR</p>
            <p className="truncate text-xs text-white/70">
              {Math.round(pose.heading)}° ·{' '}
              {usingFallback
                ? gpsError
                  ? 'Không có GPS — dùng vị trí bản đồ'
                  : 'Đang lấy GPS…'
                : `GPS ±${Math.round(gps.accuracy)} m`}
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => {
            setSelectedId(null);
            setShowBadges((open) => !open);
          }}
          aria-pressed={showBadges}
          className="flex items-center gap-1 rounded-full bg-amber-400/90 px-2.5 py-1 text-xs font-bold text-amber-950 hover:bg-amber-300"
          aria-label={`Đã check-in ${discovered} địa điểm — xem huy hiệu`}
        >
          <Trophy className="size-3.5" aria-hidden />
          {discovered}
        </button>
        <button
          type="button"
          onClick={onClose}
          className="grid size-9 place-items-center rounded-full bg-white/15 backdrop-blur hover:bg-white/25"
          aria-label="Thoát chế độ AR"
        >
          <X className="size-5" />
        </button>
      </div>

      {!started ? (
        <div className="absolute inset-0 z-30 grid place-items-center p-6">
          <div className="w-full max-w-sm rounded-3xl bg-white/10 p-6 text-center backdrop-blur-xl">
            <span className="mx-auto grid size-14 place-items-center rounded-2xl bg-emerald-500/25 text-emerald-300">
              <Camera className="size-7" aria-hidden />
            </span>
            <h2 className="mt-4 text-lg font-semibold">Giơ điện thoại lên để khám phá</h2>
            <p className="mt-2 text-sm text-white/75">
              Địa điểm quanh bạn sẽ hiện đúng hướng trên camera. Đi tới gần (≤ {CHECKIN_RADIUS} m) để check-in,
              mở khoá huy hiệu và xua sương mù trên bản đồ.
            </p>
            <p className="mt-3 text-xs text-white/55">
              Cần quyền camera, vị trí và cảm biến hướng. Ảnh camera chỉ hiện trên máy bạn, không gửi đi đâu.
            </p>
            <button
              type="button"
              onClick={start}
              className="mt-5 w-full rounded-full bg-emerald-500 py-3 text-sm font-semibold text-white shadow-lg hover:bg-emerald-400"
            >
              Bắt đầu khám phá
            </button>
          </div>
        </div>
      ) : (
        <>
          {/* Thẻ địa điểm */}
          <div className="pointer-events-none absolute inset-0 z-10">
            {cards.map(({ poi, x, y, scale }) => {
              const done = checkedIds.has(poi.id);
              return (
                <button
                  key={poi.id}
                  type="button"
                  onPointerDown={(event) => event.stopPropagation()}
                  onClick={() => {
                    setShowBadges(false);
                    setSelectedId(poi.id);
                  }}
                  aria-label={`${poi.name}, ${formatMeters(poi.distance)}`}
                  className="pointer-events-auto absolute flex max-w-[150px] origin-bottom flex-col items-center"
                  style={{ left: x, top: y, transform: `translate(-50%, -100%) scale(${scale})` }}
                >
                  <span
                    className={cn(
                      'w-full rounded-2xl px-3 py-1.5 text-left shadow-lg ring-1 backdrop-blur-md',
                      selectedId === poi.id
                        ? 'bg-emerald-500/90 ring-white/60'
                        : done
                          ? 'bg-amber-500/80 ring-amber-200/50'
                          : 'bg-black/55 ring-white/20',
                    )}
                  >
                    <span className="block truncate text-[13px] font-semibold leading-tight">{poi.name}</span>
                    <span className="flex items-center gap-1.5 text-[11px] text-white/80">
                      <span className="truncate">{poi.categoryLabel}</span>
                      <span className="shrink-0 font-semibold text-white">{formatMeters(poi.distance)}</span>
                    </span>
                  </span>
                  <span className="h-3 w-px bg-white/70" aria-hidden />
                  <span className="size-2 rounded-full bg-white shadow" aria-hidden />
                </button>
              );
            })}
          </div>

          {/* Gợi ý */}
          <div className="pointer-events-none absolute inset-x-0 bottom-44 z-20 flex flex-col items-center gap-2 px-4 text-center">
            {notice && (
              <output
                className={cn(
                  'rounded-2xl px-4 py-2 text-sm font-semibold shadow-lg backdrop-blur',
                  notice.tone === 'success' ? 'bg-amber-400/95 text-amber-950' : 'bg-black/75 text-white',
                )}
              >
                {notice.text}
              </output>
            )}
            {flatPhone && (
              <span className="flex items-center gap-2 rounded-full bg-black/60 px-3 py-1.5 text-xs backdrop-blur">
                <Smartphone className="size-4" aria-hidden /> Dựng điện thoại lên để nhìn quanh
              </span>
            )}
            {sensorMode === 'drag' && (
              <span className="rounded-full bg-black/60 px-3 py-1.5 text-xs backdrop-blur">
                Máy không có la bàn — kéo màn hình để xoay
              </span>
            )}
            {cameraState === 'denied' && (
              <span className="flex items-center gap-2 rounded-full bg-black/60 px-3 py-1.5 text-xs backdrop-blur">
                <CameraOff className="size-4" aria-hidden /> Không mở được camera — vẫn xem được hướng
              </span>
            )}
            {loading && (
              <span className="flex items-center gap-2 rounded-full bg-black/60 px-3 py-1.5 text-xs backdrop-blur">
                <LoaderCircle className="size-4 animate-spin" aria-hidden /> Đang tìm địa điểm quanh bạn…
              </span>
            )}
            {!loading && placed.length === 0 && (
              <span className="rounded-full bg-black/60 px-3 py-1.5 text-xs backdrop-blur">
                Không có địa điểm nào trong {formatMeters(radius)}
              </span>
            )}
          </div>

          {/* Khay dưới: radar + bán kính + "ngay quanh bạn" */}
          <div
            className="absolute inset-x-0 bottom-0 z-20 bg-gradient-to-t from-black/80 via-black/50 to-transparent px-4 pt-10 pb-[max(1rem,env(safe-area-inset-bottom))]"
            onPointerDown={(event) => event.stopPropagation()}
          >
            {showBadges ? (
              <BadgePanel
                summary={checkInSummary}
                signedIn={Object.keys(authHeaders()).length > 0}
                onClose={() => setShowBadges(false)}
              />
            ) : selected ? (
              <div className="rounded-3xl bg-white p-4 text-slate-900 shadow-2xl dark:bg-slate-900 dark:text-white">
                <div className="flex items-start gap-3">
                  <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-emerald-500/15 text-emerald-600 dark:text-emerald-300">
                    <MapPin className="size-5" aria-hidden />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-semibold">{selected.name}</p>
                    <p className="text-xs text-slate-500 dark:text-slate-400">
                      {selected.categoryLabel} · {formatMeters(selected.distance)} ·{' '}
                      {compassWord(selected.bearing)}
                      {selected.rating != null && (
                        <>
                          {' · '}
                          <Star className="inline size-3 -translate-y-px fill-amber-400 text-amber-400" />{' '}
                          {selected.rating.toFixed(1)}
                        </>
                      )}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setSelectedId(null)}
                    className="grid size-8 place-items-center rounded-full hover:bg-slate-100 dark:hover:bg-white/10"
                    aria-label="Đóng"
                  >
                    <X className="size-4" />
                  </button>
                </div>
                <div className="mt-3 grid grid-cols-2 gap-2">
                  {checkedIds.has(selected.id) ? (
                    <span className="flex items-center justify-center gap-1.5 rounded-full bg-amber-100 py-2.5 text-sm font-semibold text-amber-800 dark:bg-amber-500/20 dark:text-amber-200">
                      <Trophy className="size-4" aria-hidden /> Đã khám phá
                    </span>
                  ) : (
                    <button
                      type="button"
                      disabled={!canCheckIn(selected)}
                      onClick={() => void checkIn(selected)}
                      className="flex items-center justify-center gap-1.5 rounded-full bg-amber-500 py-2.5 text-sm font-semibold text-white disabled:bg-slate-200 disabled:text-slate-500 dark:disabled:bg-white/10 dark:disabled:text-white/50"
                      title={usingFallback ? 'Cần GPS thật để check-in' : 'Đứng tại địa điểm rồi bấm để check-in'}
                    >
                      {checkingIn === selected.id ? (
                        <LoaderCircle className="size-4 animate-spin" aria-hidden />
                      ) : usingFallback ? (
                        'Cần GPS để check-in'
                      ) : selected.distance > CHECKIN_HOPELESS_METERS ? (
                        `Còn ${formatMeters(selected.distance)}`
                      ) : (
                        'Check-in'
                      )}
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => onOpenDetail(selected.id)}
                    className="rounded-full bg-emerald-600 py-2.5 text-sm font-semibold text-white hover:bg-emerald-500"
                  >
                    Xem chi tiết
                  </button>
                </div>
              </div>
            ) : (
              <div className="flex items-end gap-3">
                <Radar placed={placed} heading={pose.heading} fov={viewport.fov} radius={radius} checked={checkedIds} />
                <div className="min-w-0 flex-1 space-y-2">
                  {nearby.length > 0 && (
                    <div className="space-y-1">
                      <p className="text-[11px] font-semibold uppercase tracking-wider text-white/60">Ngay quanh bạn</p>
                      <div className="flex gap-1.5 overflow-x-auto">
                        {nearby.slice(0, 6).map((poi) => (
                          <button
                            key={poi.id}
                            type="button"
                            onClick={() => setSelectedId(poi.id)}
                            className="shrink-0 rounded-full bg-white/15 px-3 py-1 text-xs backdrop-blur hover:bg-white/25"
                          >
                            {poi.name}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                  <div className="flex items-center gap-1.5">
                    <span className="text-[11px] whitespace-nowrap text-white/60 max-[380px]:sr-only">Bán kính</span>
                    {RADIUS_OPTIONS.map((option) => (
                      <button
                        key={option}
                        type="button"
                        onClick={() => changeRadius(option)}
                        aria-pressed={radius === option}
                        className={cn(
                          'rounded-full px-2.5 py-1 text-xs font-medium whitespace-nowrap backdrop-blur',
                          radius === option ? 'bg-emerald-500 text-white' : 'bg-white/15 hover:bg-white/25',
                        )}
                      >
                        {formatMeters(option)}
                      </button>
                    ))}
                  </div>
                  <p className="text-[11px] text-white/55">
                    {placed.length} địa điểm · {cards.length} trong khung hình
                  </p>
                </div>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

const COMPASS_WORDS = ['bắc', 'đông bắc', 'đông', 'đông nam', 'nam', 'tây nam', 'tây', 'tây bắc'];
function compassWord(bearing: number) {
  return `hướng ${COMPASS_WORDS[Math.round(wrap360(bearing) / 45) % 8]}`;
}

/** Radar nhỏ: đỉnh = hướng đang nhìn, nêm sáng = vùng camera thấy. */
function Radar({
  placed,
  heading,
  fov,
  radius,
  checked,
}: {
  placed: Placed[];
  heading: number;
  fov: number;
  radius: number;
  checked: Set<string | null>;
}) {
  const size = 104;
  const r = size / 2 - 4;
  const half = toRad(fov / 2);
  const wedge = `M ${size / 2} ${size / 2} L ${size / 2 + r * Math.sin(-half)} ${size / 2 - r * Math.cos(half)} A ${r} ${r} 0 0 1 ${size / 2 + r * Math.sin(half)} ${size / 2 - r * Math.cos(half)} Z`;
  return (
    <svg width={size} height={size} className="shrink-0" aria-hidden>
      <circle cx={size / 2} cy={size / 2} r={r} fill="rgb(0 0 0 / 45%)" stroke="rgb(255 255 255 / 35%)" />
      <circle cx={size / 2} cy={size / 2} r={r / 2} fill="none" stroke="rgb(255 255 255 / 15%)" />
      <path d={wedge} fill="rgb(16 185 129 / 30%)" />
      {placed.map((poi) => {
        const angle = toRad(poi.bearing - heading);
        const d = Math.min(1, poi.distance / radius) * r;
        return (
          <circle
            key={poi.id}
            cx={size / 2 + d * Math.sin(angle)}
            cy={size / 2 - d * Math.cos(angle)}
            r={2.5}
            fill={checked.has(poi.id) ? '#fbbf24' : '#ffffff'}
          />
        );
      })}
      <circle cx={size / 2} cy={size / 2} r={4} fill="#38bdf8" stroke="#fff" strokeWidth={1.5} />
      <text
        x={size / 2 + r * Math.sin(toRad(-heading))}
        y={size / 2 - r * Math.cos(toRad(-heading)) + 3.5}
        textAnchor="middle"
        fontSize="10"
        fontWeight="700"
        fill="#f87171"
      >
        B
      </text>
    </svg>
  );
}

/** Danh sách huy hiệu — đã đạt lên trước, chưa đạt kèm thanh tiến độ. */
function BadgePanel({
  summary,
  signedIn,
  onClose,
}: {
  summary: CheckInSummary | null;
  signedIn: boolean;
  onClose: () => void;
}) {
  const badges = [...(summary?.badges ?? [])].sort((a, b) => Number(b.earned) - Number(a.earned));
  const earned = badges.filter((badge) => badge.earned).length;
  return (
    <div className="max-h-[60dvh] overflow-y-auto rounded-3xl bg-white p-4 text-slate-900 shadow-2xl dark:bg-slate-900 dark:text-white">
      <div className="flex items-center gap-3">
        <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-amber-400/20 text-amber-600 dark:text-amber-300">
          <Trophy className="size-5" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <p className="font-semibold">Huy hiệu khám phá</p>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {summary ? `${summary.total} nơi đã check-in · ${earned}/${badges.length} huy hiệu` : 'Đang tải…'}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="grid size-8 place-items-center rounded-full hover:bg-slate-100 dark:hover:bg-white/10"
          aria-label="Đóng"
        >
          <X className="size-4" />
        </button>
      </div>
      <ul className="mt-3 space-y-2">
        {badges.map((badge) => {
          const Icon = BADGE_ICONS[badge.icon] ?? Trophy;
          return (
            <li
              key={badge.id}
              className={cn(
                'flex items-center gap-3 rounded-2xl px-3 py-2',
                badge.earned ? 'bg-amber-50 dark:bg-amber-500/10' : 'bg-slate-50 dark:bg-white/5',
              )}
            >
              <span
                className={cn(
                  'grid size-9 shrink-0 place-items-center rounded-full',
                  badge.earned
                    ? 'bg-amber-400 text-amber-950'
                    : 'bg-slate-200 text-slate-400 dark:bg-white/10 dark:text-white/40',
                )}
              >
                <Icon className="size-4" aria-hidden />
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold">{badge.title}</p>
                <p className="truncate text-xs text-slate-500 dark:text-slate-400">{badge.description}</p>
                {!badge.earned && (
                  <div className="mt-1 flex items-center gap-2">
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-200 dark:bg-white/10">
                      <div
                        className="h-full rounded-full bg-emerald-500"
                        style={{ width: `${(badge.progress / badge.goal) * 100}%` }}
                      />
                    </div>
                    <span className="text-[11px] tabular-nums text-slate-500 dark:text-slate-400">
                      {badge.progress}/{badge.goal}
                    </span>
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ul>
      {!signedIn && (
        <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">
          Đăng nhập để giữ huy hiệu khi đổi máy — check-in trên máy này sẽ tự chuyển sang tài khoản.
        </p>
      )}
    </div>
  );
}

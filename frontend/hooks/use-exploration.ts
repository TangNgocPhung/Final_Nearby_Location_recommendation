'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { distanceMeters } from '@/lib/assistant';

/**
 * Bản đồ sương mù — xem backend/app/exploration.py.
 *
 * Hook này giữ tổng quan vùng đã khám phá và gửi vị trí lên khi người dùng di
 * chuyển. Không tự bật GPS: nơi gọi (chế độ sương mù trên bản đồ, màn AR) quyết
 * định khi nào được ghi, rồi đưa điểm vào `record`.
 */

export type ExplorationMilestone = {
  id: string;
  title: string;
  description: string;
  goalKm2: number;
  progressKm2: number;
  earned: boolean;
};

export type ExplorationOverview = {
  resolution: number;
  cellCount: number;
  areaKm2: number;
  todayCount: number;
  shape: GeoJSON.Polygon | GeoJSON.MultiPolygon | null;
  milestones: ExplorationMilestone[];
};

export type DistrictStats = {
  districts: { district: string; cellCount: number; areaKm2: number }[];
  districtCount: number;
  /** Ô xa mọi POI nên không gán được quận — tổng các quận cộng số này khớp `cellCount`. */
  unassignedCells: number;
};

export type ExplorationPoint = { latitude: number; longitude: number; accuracy: number | null };

/** Giống `MAX_ACCURACY_METERS` của server — điểm tệ hơn thì gửi cũng bị bỏ. */
const MAX_ACCURACY_METERS = 60;
/** Ô r9 rộng ~340 m; đi chưa tới 40 m thì gần như chắc chắn vẫn ô cũ. */
const MIN_MOVE_METERS = 40;
/** Giống `MAX_POINTS_PER_REQUEST` của server — gửi quá là cả lô bị từ chối. */
const MAX_BATCH = 200;
/** Hàng đợi chỉ nằm trong bộ nhớ trang: toạ độ thô không được ghi xuống đĩa
 * (server cũng chỉ giữ ô — xem migration 0033). Đóng tab lúc mất mạng thì mất. */
const MAX_PENDING = 500;
/** Báo mốc mới đủ lâu để đọc, rồi tự tắt. */
const UNLOCK_BANNER_MS = 8000;

type Options = {
  apiBaseUrl: string;
  sessionId: string | null;
  authToken: string | null;
  /** Chỉ nạp tổng quan khi có ai cần xem (bật sương mù). */
  active: boolean;
};

export function useExploration({ apiBaseUrl, sessionId, authToken, active }: Options) {
  const [overview, setOverview] = useState<ExplorationOverview | null>(null);
  const [districts, setDistricts] = useState<DistrictStats | null>(null);
  const [unlocked, setUnlocked] = useState<ExplorationMilestone[]>([]);
  const [pendingCount, setPendingCount] = useState(0);
  // Điểm đã nhận nhưng chưa được server xác nhận. Mất mạng thì giữ lại, lần gửi
  // sau (hoặc khi mạng về) gửi gộp một lô thay vì rơi mất đoạn đường ở giữa.
  const pendingRef = useRef<ExplorationPoint[]>([]);
  const lastAcceptedRef = useRef<ExplorationPoint | null>(null);
  const sendingRef = useRef(false);
  const unlockTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const headers = useCallback((): Record<string, string> => {
    const result: Record<string, string> = {};
    if (sessionId) result['X-Session-ID'] = sessionId;
    if (authToken) result.Authorization = `Bearer ${authToken}`;
    return result;
  }, [sessionId, authToken]);

  const refresh = useCallback(async () => {
    if (!sessionId) return;
    try {
      const response = await fetch(`${apiBaseUrl}/api/v1/exploration`, { headers: headers() });
      if (response.ok) setOverview((await response.json()) as ExplorationOverview);
    } catch {
      // Mất mạng: giữ sương mù đang vẽ, đừng xoá trắng như thể chưa đi đâu.
    }
  }, [apiBaseUrl, sessionId, headers]);

  const loadDistricts = useCallback(async () => {
    if (!sessionId) return;
    try {
      const response = await fetch(`${apiBaseUrl}/api/v1/exploration/districts`, { headers: headers() });
      if (response.ok) setDistricts((await response.json()) as DistrictStats);
    } catch {
      // Giữ bảng quận đang hiện.
    }
  }, [apiBaseUrl, sessionId, headers]);

  useEffect(() => {
    if (!active) return;
    // Fetch rồi setState — đồng bộ với hệ thống ngoài, đúng mẫu effect hợp lệ.
    // oxlint-disable-next-line react/react-compiler
    void refresh();
  }, [active, refresh]);

  const dismissUnlocked = useCallback(() => {
    if (unlockTimerRef.current) clearTimeout(unlockTimerRef.current);
    unlockTimerRef.current = null;
    setUnlocked([]);
  }, []);

  useEffect(
    () => () => {
      if (unlockTimerRef.current) clearTimeout(unlockTimerRef.current);
    },
    [],
  );

  const announce = useCallback((milestones: ExplorationMilestone[]) => {
    setUnlocked((current) => [...current, ...milestones]);
    if (unlockTimerRef.current) clearTimeout(unlockTimerRef.current);
    unlockTimerRef.current = setTimeout(() => setUnlocked([]), UNLOCK_BANNER_MS);
  }, []);

  /** Gửi một lô. `retry` = giữ lô lại (mất mạng / 5xx); 4xx gửi lại y nguyên
   * cũng vậy nên bỏ, giữ lại chỉ làm kẹt hàng đợi mãi. */
  const postBatch = useCallback(
    async (batch: ExplorationPoint[]) => {
      try {
        const response = await fetch(`${apiBaseUrl}/api/v1/exploration`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...headers() },
          body: JSON.stringify({
            points: batch.map((point) => ({
              latitude: point.latitude,
              longitude: point.longitude,
              accuracy_meters: point.accuracy,
            })),
          }),
        });
        if (response.status >= 500) return { retry: true, result: null };
        if (!response.ok) return { retry: false, result: null };
        const result = (await response.json()) as ExplorationOverview & {
          added: number;
          unlocked?: ExplorationMilestone[];
        };
        return { retry: false, result };
      } catch {
        return { retry: true, result: null };
      }
    },
    [apiBaseUrl, headers],
  );

  const flush = useCallback(async () => {
    // `record` chỉ xếp hàng khi đã có phiên, nên hàng đợi rỗng = không có gì để gửi.
    if (sendingRef.current) return;
    sendingRef.current = true;
    while (pendingRef.current.length > 0) {
      const batch = pendingRef.current.slice(0, MAX_BATCH);
      const { retry, result } = await postBatch(batch);
      if (retry) break; // Giữ nguyên hàng đợi, đợi lần di chuyển kế hoặc sự kiện `online`.
      pendingRef.current = pendingRef.current.filter((point) => !batch.includes(point));
      setPendingCount(pendingRef.current.length);
      if (!result) continue;
      if (result.added > 0) setOverview(result);
      if (result.unlocked?.length) announce(result.unlocked);
    }
    sendingRef.current = false;
  }, [postBatch, announce]);

  // Mạng về thì gửi bù ngay, không đợi người dùng đi thêm 40 m.
  useEffect(() => {
    const onOnline = () => void flush();
    window.addEventListener('online', onOnline);
    return () => window.removeEventListener('online', onOnline);
  }, [flush]);

  const record = useCallback(
    async (point: ExplorationPoint) => {
      if (!sessionId) return;
      if (point.accuracy != null && point.accuracy > MAX_ACCURACY_METERS) return;
      const last = lastAcceptedRef.current;
      if (last && distanceMeters(last, point) < MIN_MOVE_METERS) return;
      lastAcceptedRef.current = point;
      pendingRef.current.push(point);
      // Trần phòng thủ: ngoại tuyến cả buổi thì bỏ điểm CŨ nhất, giữ đoạn mới.
      if (pendingRef.current.length > MAX_PENDING) {
        pendingRef.current = pendingRef.current.slice(-MAX_PENDING);
      }
      setPendingCount(pendingRef.current.length);
      await flush();
    },
    [sessionId, flush],
  );

  const clear = useCallback(async () => {
    if (!sessionId) return false;
    try {
      const response = await fetch(`${apiBaseUrl}/api/v1/exploration`, {
        method: 'DELETE',
        headers: headers(),
      });
      if (!response.ok) return false;
      lastAcceptedRef.current = null;
      pendingRef.current = [];
      setPendingCount(0);
      setDistricts(null);
      await refresh();
      return true;
    } catch {
      return false;
    }
  }, [apiBaseUrl, sessionId, headers, refresh]);

  return {
    overview,
    districts,
    unlocked,
    pendingCount,
    record,
    refresh,
    loadDistricts,
    dismissUnlocked,
    clear,
  };
}

type Ring = GeoJSON.Position[];

/** Diện tích có dấu (shoelace): dương = ngược chiều kim đồng hồ. */
function signedArea(ring: Ring): number {
  let sum = 0;
  for (let i = 0; i < ring.length - 1; i += 1) {
    sum += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1];
  }
  return sum / 2;
}

const withWinding = (ring: Ring, ccw: boolean): Ring =>
  signedArea(ring) > 0 === ccw ? ring : [...ring].reverse();

// Không tới ±90: Web Mercator không vẽ được cực, vòng chạm cực bị cắt méo.
const WORLD: Ring = [
  [-180, -85],
  [180, -85],
  [180, 85],
  [-180, 85],
  [-180, -85],
];

/**
 * Lớp sương: một tấm phủ cả thế giới, đục lỗ đúng vùng đã khám phá.
 *
 * MapLibre phân biệt vòng ngoài/lỗ bằng CHIỀU quay của vòng (không theo thứ tự
 * trong mảng), nên phải tự ép chiều: tấm phủ ngược chiều kim đồng hồ, lỗ cùng
 * chiều kim đồng hồ. Vùng chưa tới nằm LỌT GIỮA vùng đã khám phá (lỗ của
 * đường bao) thì phủ sương lại bằng polygon riêng — không thì nó sáng oan.
 */
export function fogGeometry(shape: ExplorationOverview['shape']): GeoJSON.MultiPolygon {
  const polygons = !shape ? [] : shape.type === 'Polygon' ? [shape.coordinates] : shape.coordinates;
  const holes = polygons.map((rings) => withWinding(rings[0], false));
  const pockets = polygons.flatMap((rings) => rings.slice(1).map((ring) => [withWinding(ring, true)]));
  return { type: 'MultiPolygon', coordinates: [[withWinding(WORLD, true), ...holes], ...pockets] };
}

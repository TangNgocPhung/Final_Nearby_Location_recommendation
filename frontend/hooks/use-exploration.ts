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

export type ExplorationOverview = {
  resolution: number;
  cellCount: number;
  areaKm2: number;
  todayCount: number;
  shape: GeoJSON.Polygon | GeoJSON.MultiPolygon | null;
};

export type ExplorationPoint = { latitude: number; longitude: number; accuracy: number | null };

/** Giống `MAX_ACCURACY_METERS` của server — điểm tệ hơn thì gửi cũng bị bỏ. */
const MAX_ACCURACY_METERS = 60;
/** Ô r9 rộng ~340 m; đi chưa tới 40 m thì gần như chắc chắn vẫn ô cũ. */
const MIN_MOVE_METERS = 40;

type Options = {
  apiBaseUrl: string;
  sessionId: string | null;
  authToken: string | null;
  /** Chỉ nạp tổng quan khi có ai cần xem (bật sương mù). */
  active: boolean;
};

export function useExploration({ apiBaseUrl, sessionId, authToken, active }: Options) {
  const [overview, setOverview] = useState<ExplorationOverview | null>(null);
  const lastSentRef = useRef<ExplorationPoint | null>(null);

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

  useEffect(() => {
    if (!active) return;
    // Fetch rồi setState — đồng bộ với hệ thống ngoài, đúng mẫu effect hợp lệ.
    // oxlint-disable-next-line react/react-compiler
    void refresh();
  }, [active, refresh]);

  const record = useCallback(
    async (point: ExplorationPoint) => {
      if (!sessionId) return;
      if (point.accuracy != null && point.accuracy > MAX_ACCURACY_METERS) return;
      const last = lastSentRef.current;
      if (last && distanceMeters(last, point) < MIN_MOVE_METERS) return;
      lastSentRef.current = point;
      try {
        const response = await fetch(`${apiBaseUrl}/api/v1/exploration`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...headers() },
          body: JSON.stringify({
            points: [
              { latitude: point.latitude, longitude: point.longitude, accuracy_meters: point.accuracy },
            ],
          }),
        });
        if (!response.ok) return;
        const next = (await response.json()) as ExplorationOverview & { added: number };
        if (next.added > 0) setOverview(next);
      } catch {
        // Gửi hụt thì lần di chuyển kế tiếp gửi lại: cho phép gửi lại từ điểm này.
        lastSentRef.current = last;
      }
    },
    [apiBaseUrl, sessionId, headers],
  );

  const clear = useCallback(async () => {
    if (!sessionId) return false;
    try {
      const response = await fetch(`${apiBaseUrl}/api/v1/exploration`, {
        method: 'DELETE',
        headers: headers(),
      });
      if (!response.ok) return false;
      lastSentRef.current = null;
      await refresh();
      return true;
    } catch {
      return false;
    }
  }, [apiBaseUrl, sessionId, headers, refresh]);

  return { overview, record, refresh, clear };
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

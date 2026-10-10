'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { distanceMeters } from '@/lib/assistant';
import type { ExploreOverview, ExplorePlace } from '@/lib/explore';

/**
 * Địa danh Săn địa danh Sài Gòn ở gần người dùng — dùng chung cho thẻ trên trang
 * chính, lớp marker trên bản đồ và nhắc khi tới gần.
 *
 * Dữ liệu lấy từ cùng `/api/v1/explore` mà màn "Săn địa danh" dùng, nên trạng thái
 * "đã khám phá" luôn khớp giữa hai nơi. Danh sách chỉ tải khi có phiên và khi gọi
 * `refresh()`; khoảng cách được tính lại tại chỗ mỗi khi vị trí đổi.
 */

type Position = { latitude: number; longitude: number };

export type NearbyLandmark = ExplorePlace;

export function useNearbyLandmarks({
  apiBaseUrl,
  sessionId,
  position,
}: {
  apiBaseUrl: string;
  sessionId: string;
  position: Position;
}) {
  const [overview, setOverview] = useState<ExploreOverview | null>(null);
  const [failed, setFailed] = useState(false);
  // Đọc vị trí qua ref để `refresh` không đổi danh tính mỗi lần GPS nhích.
  const positionRef = useRef(position);
  useEffect(() => {
    positionRef.current = position;
  }, [position]);

  const refresh = useCallback(async () => {
    if (!sessionId) return;
    try {
      const params = new URLSearchParams({
        lat: String(positionRef.current.latitude),
        lng: String(positionRef.current.longitude),
      });
      const res = await fetch(`${apiBaseUrl}/api/v1/explore?${params}`, {
        headers: { 'X-Session-ID': sessionId },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setOverview((await res.json()) as ExploreOverview);
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [apiBaseUrl, sessionId]);

  useEffect(() => {
    // Nạp dữ liệu từ server khi có phiên — đồng bộ với hệ thống bên ngoài.
    // oxlint-disable-next-line react/react-compiler
    void refresh();
  }, [refresh]);

  const landmarks = useMemo<NearbyLandmark[]>(() => {
    if (!overview) return [];
    return overview.places
      .map((place) => ({
        ...place,
        distanceMeters: distanceMeters(position, place),
      }))
      .sort((a, b) => a.distanceMeters - b.distanceMeters);
  }, [overview, position]);

  return {
    landmarks,
    total: overview?.total ?? 0,
    discovered: overview?.discovered ?? 0,
    loaded: overview !== null,
    failed,
    refresh,
  };
}

// --- Nhắc khi tới gần ----------------------------------------------------------

const ALERT_STORAGE_KEY = 'nearby-landmark-alerts';
const ALERTED_STORAGE_KEY = 'nearby-landmark-alerted';
/** Tới trong khoảng này (m) thì nhắc — đủ xa để kịp rẽ vào, đủ gần để còn đúng nghĩa "gần". */
export const LANDMARK_ALERT_METERS = 200;
/** Cùng một địa danh không nhắc lại trong khoảng này, kể cả khi người dùng đi qua đi lại. */
const ALERT_COOLDOWN_MS = 6 * 60 * 60 * 1000;

export type LandmarkAlert = { landmark: NearbyLandmark; at: number };

function readAlerted(): Record<string, number> {
  try {
    return JSON.parse(
      window.localStorage.getItem(ALERTED_STORAGE_KEY) ?? '{}',
    ) as Record<string, number>;
  } catch {
    return {};
  }
}

function writeAlerted(value: Record<string, number>) {
  try {
    window.localStorage.setItem(ALERTED_STORAGE_KEY, JSON.stringify(value));
  } catch {
    // Storage bị chặn: chỉ mất phần nhớ cooldown giữa các lần tải trang.
  }
}

/**
 * Nhắc khi người dùng (GPS thật) tới trong `LANDMARK_ALERT_METERS` của một địa
 * danh CHƯA khám phá. Chỉ chạy khi người dùng chủ động bật — xin quyền thông báo
 * lúc tải trang là cách nhanh nhất để bị từ chối vĩnh viễn.
 *
 * Dùng chung Service Worker của thông báo tới gần (`/sw.js`, tin nhắn
 * `nearby:proximity`) để thông báo hiện được cả khi tab ở nền và bấm vào sẽ mở
 * đúng địa điểm.
 */
export function useLandmarkAlerts({
  landmarks,
  hasRealGps,
}: {
  landmarks: NearbyLandmark[];
  /** Chỉ vị trí GPS thật mới đáng tin để nhắc; vị trí mô phỏng/mặc định thì không. */
  hasRealGps: boolean;
}) {
  const [enabled, setEnabled] = useState(false);
  const [permission, setPermission] = useState<
    NotificationPermission | 'unsupported'
  >('default');
  const [alert, setAlert] = useState<LandmarkAlert | null>(null);
  const registrationRef = useRef<ServiceWorkerRegistration | null>(null);

  // Khôi phục lựa chọn đã lưu sau khi mount (đọc storage là API trình duyệt).
  useEffect(() => {
    if (typeof window === 'undefined' || !('Notification' in window)) {
      // oxlint-disable-next-line react/react-compiler
      setPermission('unsupported');
      return;
    }
    setPermission(Notification.permission);
    try {
      if (
        window.localStorage.getItem(ALERT_STORAGE_KEY) === '1' &&
        Notification.permission === 'granted'
      ) {
        setEnabled(true);
        void navigator.serviceWorker
          ?.register('/sw.js')
          .then((registration) => {
            registrationRef.current = registration;
          })
          .catch(() => {});
      }
    } catch {
      // Storage bị chặn: bắt đầu ở trạng thái tắt.
    }
  }, []);

  /** Gọi từ một cú bấm của người dùng. Trả về `true` nếu đã bật. */
  const enable = useCallback(async () => {
    if (typeof window === 'undefined' || !('Notification' in window)) {
      setPermission('unsupported');
      return false;
    }
    let granted = Notification.permission;
    if (granted === 'default') granted = await Notification.requestPermission();
    setPermission(granted);
    if (granted !== 'granted') return false;
    if ('serviceWorker' in navigator) {
      try {
        registrationRef.current =
          await navigator.serviceWorker.register('/sw.js');
      } catch {
        registrationRef.current = null;
      }
    }
    try {
      window.localStorage.setItem(ALERT_STORAGE_KEY, '1');
    } catch {
      // Không lưu được thì lần sau phải bật lại, không sao.
    }
    setEnabled(true);
    return true;
  }, []);

  const disable = useCallback(() => {
    try {
      window.localStorage.removeItem(ALERT_STORAGE_KEY);
    } catch {
      // Bỏ qua.
    }
    setEnabled(false);
    setAlert(null);
  }, []);

  const dismiss = useCallback(() => setAlert(null), []);

  useEffect(() => {
    if (!enabled || !hasRealGps) return;
    const alerted = readAlerted();
    const now = Date.now();
    const target = landmarks.find(
      (place) =>
        !place.discovered &&
        place.distanceMeters <= LANDMARK_ALERT_METERS &&
        now - (alerted[place.poiId] ?? 0) > ALERT_COOLDOWN_MS,
    );
    if (!target) return;

    writeAlerted({ ...alerted, [target.poiId]: now });
    // Ghi nhận một lần cho mỗi địa danh rồi mới hiện banner/thông báo.
    // oxlint-disable-next-line react/react-compiler
    setAlert({ landmark: target, at: now });

    const payload = {
      poiId: target.poiId,
      title: target.name,
      subscriptionId: `landmark-${target.poiId}`,
      distanceMeters: target.distanceMeters,
      address: 'Chụp một tấm ảnh để mở khoá câu chuyện',
    };
    const registration = registrationRef.current;
    if (registration?.active) {
      registration.active.postMessage({ type: 'nearby:proximity', payload });
    } else if (Notification.permission === 'granted') {
      try {
        new Notification(`Bạn đang ở gần ${target.name}`, {
          body: `Cách khoảng ${Math.round(target.distanceMeters)} m · chụp ảnh để mở khoá câu chuyện`,
          tag: `nearby-landmark-${target.poiId}`,
        });
      } catch {
        // Một số trình duyệt di động chỉ cho phép qua Service Worker; banner trong trang vẫn hiện.
      }
    }
  }, [enabled, hasRealGps, landmarks]);

  return { enabled, permission, alert, enable, disable, dismiss };
}

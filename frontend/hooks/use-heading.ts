'use client';

import { useCallback, useEffect, useRef } from 'react';

/**
 * Hướng người dùng đang quay mặt (độ, 0 = bắc, theo chiều kim đồng hồ), để chỉ
 * đường theo MẶT ĐỒNG HỒ ("hướng 2 giờ") thay vì "hướng đông bắc" — người khiếm
 * thị không biết đâu là đông.
 *
 * Hai nguồn, ưu tiên theo thứ tự:
 * 1. Hướng di chuyển từ GPS (`reportGps`), khi đang đi đủ nhanh: đúng hướng
 *    người đang bước kể cả khi điện thoại nằm trong túi.
 * 2. La bàn điện thoại: `deviceorientationabsolute` (Chrome Android) hoặc
 *    `webkitCompassHeading` (Safari iOS — phải xin quyền trong một thao tác
 *    người dùng, xem `requestPermission`).
 *
 * Số liệu cũ quá vài giây coi như không có — nói sai hướng còn tệ hơn nói la bàn.
 */

const COMPASS_FRESH_MS = 3_000;
const GPS_FRESH_MS = 5_000;
const WALKING_SPEED = 0.6; // m/s; chậm hơn thì hướng GPS nhảy lung tung

type Reading = { value: number; at: number };

function screenAngle(): number {
  if (typeof screen === 'undefined') return 0;
  return screen.orientation?.angle ?? 0;
}

export function useHeading() {
  const compassRef = useRef<Reading | null>(null);
  const gpsRef = useRef<Reading | null>(null);
  const askedRef = useRef(false);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const set = (degrees: number) => {
      compassRef.current = { value: (((degrees + screenAngle()) % 360) + 360) % 360, at: Date.now() };
    };
    const onAbsolute = (event: Event) => {
      const { alpha } = event as DeviceOrientationEvent;
      if (alpha != null) set(360 - alpha);
    };
    const onOrientation = (event: Event) => {
      const ios = (event as DeviceOrientationEvent & { webkitCompassHeading?: number }).webkitCompassHeading;
      if (typeof ios === 'number' && ios >= 0) set(ios);
    };
    window.addEventListener('deviceorientationabsolute', onAbsolute);
    window.addEventListener('deviceorientation', onOrientation);
    return () => {
      window.removeEventListener('deviceorientationabsolute', onAbsolute);
      window.removeEventListener('deviceorientation', onOrientation);
    };
  }, []);

  /** Gọi trong một thao tác người dùng (nhấn nút, phím): iOS mới cho đọc la bàn. */
  const requestPermission = useCallback(() => {
    if (askedRef.current || typeof DeviceOrientationEvent === 'undefined') return;
    askedRef.current = true;
    const ask = (DeviceOrientationEvent as unknown as { requestPermission?: () => Promise<string> }).requestPermission;
    void ask?.().catch(() => undefined);
  }, []);

  const reportGps = useCallback((heading: number | null, speed: number | null) => {
    if (heading != null && !Number.isNaN(heading) && speed != null && speed >= WALKING_SPEED) {
      gpsRef.current = { value: heading % 360, at: Date.now() };
    }
  }, []);

  const read = useCallback((): number | null => {
    const now = Date.now();
    const gps = gpsRef.current;
    if (gps && now - gps.at < GPS_FRESH_MS) return gps.value;
    const compass = compassRef.current;
    if (compass && now - compass.at < COMPASS_FRESH_MS) return compass.value;
    return null;
  }, []);

  return { read, requestPermission, reportGps };
}

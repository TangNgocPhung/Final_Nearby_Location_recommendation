'use client';

import { useEffect } from 'react';

/**
 * Giữ màn hình sáng khi `active` — đang dẫn đường mà điện thoại tắt màn hình thì
 * trình duyệt ngừng GPS và giọng đọc, người dùng mất chỉ dẫn giữa đường.
 *
 * Trình duyệt tự nhả khoá khi chuyển tab/khoá máy, nên xin lại khi trang hiện ra.
 */
export function useWakeLock(active: boolean) {
  useEffect(() => {
    if (!active || typeof navigator === 'undefined' || !('wakeLock' in navigator)) return;
    let sentinel: WakeLockSentinel | null = null;
    let cancelled = false;
    const request = async () => {
      try {
        const lock = await navigator.wakeLock.request('screen');
        if (cancelled) void lock.release();
        else sentinel = lock;
      } catch {
        // Pin yếu / trình duyệt từ chối: dẫn đường vẫn chạy, chỉ là màn hình có thể tắt.
      }
    };
    const onVisible = () => {
      if (document.visibilityState === 'visible' && (!sentinel || sentinel.released)) void request();
    };
    void request();
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      cancelled = true;
      document.removeEventListener('visibilitychange', onVisible);
      void sentinel?.release().catch(() => undefined);
    };
  }, [active]);
}

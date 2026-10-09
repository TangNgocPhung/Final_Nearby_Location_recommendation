import { useEffect, type RefObject } from 'react';

/**
 * Độ to giọng nói từ micro → biến CSS `--mic-level` (0..1) trên `target`, để
 * vòng sóng quanh nút micro phồng theo giọng — người dùng thấy máy ĐANG nghe
 * thấy mình, không chỉ "đang mở micro".
 *
 * Ghi thẳng vào style (không qua state) vì giá trị đổi mỗi khung hình.
 *
 * Chỉ bật trên máy có chuột: điện thoại Android mở `getUserMedia` song song với
 * SpeechRecognition thì lượt nhận dạng có thể mất micro. Ở đó (và khi bị từ
 * chối quyền) `--mic-level` để trống — CSS dùng hiệu ứng thở thay thế.
 */
export function useMicLevel(active: boolean, target: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const element = target.current;
    if (!active || !element || typeof window === 'undefined') return;
    if (!window.matchMedia?.('(pointer: fine)').matches || !navigator.mediaDevices?.getUserMedia) return;

    let cancelled = false;
    let frame = 0;
    let stream: MediaStream | null = null;
    let context: AudioContext | null = null;

    void navigator.mediaDevices
      .getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } })
      .then((media) => {
        if (cancelled) {
          media.getTracks().forEach((track) => track.stop());
          return;
        }
        stream = media;
        context = new AudioContext();
        const analyser = context.createAnalyser();
        analyser.fftSize = 512;
        analyser.smoothingTimeConstant = 0.6;
        context.createMediaStreamSource(media).connect(analyser);
        const samples = new Uint8Array(analyser.fftSize);
        let level = 0;
        element.dataset.micLevel = 'live';
        const tick = () => {
          analyser.getByteTimeDomainData(samples);
          let sum = 0;
          for (const sample of samples) sum += ((sample - 128) / 128) ** 2;
          // RMS giọng nói thường 0.02-0.2: kéo giãn để nói bình thường đã thấy rõ.
          const rms = Math.min(1, Math.sqrt(sum / samples.length) * 5);
          // Lên nhanh, xuống chậm — vòng sóng không giật theo từng âm tiết.
          level = rms > level ? rms : level * 0.88;
          element.style.setProperty('--mic-level', level.toFixed(3));
          frame = requestAnimationFrame(tick);
        };
        tick();
      })
      .catch(() => undefined);

    return () => {
      cancelled = true;
      cancelAnimationFrame(frame);
      stream?.getTracks().forEach((track) => track.stop());
      void context?.close().catch(() => undefined);
      element.style.removeProperty('--mic-level');
      delete element.dataset.micLevel;
    };
  }, [active, target]);
}

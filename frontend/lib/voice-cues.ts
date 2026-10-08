/**
 * Âm báo + rung cho chế độ giọng nói. Người khiếm thị không thấy nút micro đổi
 * màu — họ cần NGHE được lúc máy bắt đầu nghe, lúc đã nghe xong, lúc sắp rẽ.
 *
 * Âm tạo bằng Web Audio (vài nốt sine ngắn), không cần tải file. Rung dùng
 * `navigator.vibrate` (Android; iOS bỏ qua lặng lẽ).
 */

export type Cue = 'listen' | 'heard' | 'nothing' | 'tick' | 'turnAhead' | 'turnNow' | 'arrive' | 'offRoute' | 'error';

// [tần số Hz, bắt đầu sau (giây), dài (giây)]
type Tone = [number, number, number];

const TONES: Record<Cue, Tone[]> = {
  listen: [[660, 0, 0.08], [990, 0.08, 0.12]], // đi lên: mời nói
  heard: [[990, 0, 0.08], [660, 0.08, 0.12]], // đi xuống: đã nghe xong
  nothing: [[440, 0, 0.1], [440, 0.16, 0.1]], // hai tiếng trầm: không nghe thấy gì
  tick: [[1200, 0, 0.03]], // tích tắc khi đang tìm
  turnAhead: [[740, 0, 0.15]],
  turnNow: [[740, 0, 0.1], [740, 0.15, 0.1]],
  arrive: [[523, 0, 0.15], [659, 0.15, 0.15], [784, 0.3, 0.3]],
  offRoute: [[330, 0, 0.25], [262, 0.25, 0.3]],
  error: [[300, 0, 0.3]],
};

const VOLUME: Partial<Record<Cue, number>> = { tick: 0.05 };

const VIBRATION: Partial<Record<Cue, number[]>> = {
  turnAhead: [120],
  turnNow: [120, 80, 120],
  arrive: [400, 120, 400],
  offRoute: [250, 100, 250, 100, 250],
};

export class VoiceCues {
  private context: AudioContext | null = null;

  private audio(): AudioContext | null {
    if (typeof window === 'undefined') return null;
    if (!this.context) {
      const Ctor =
        window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!Ctor) return null;
      this.context = new Ctor();
    }
    // Trình duyệt treo AudioContext tới khi có thao tác người dùng.
    if (this.context.state === 'suspended') void this.context.resume().catch(() => undefined);
    return this.context;
  }

  play(cue: Cue): void {
    const pattern = VIBRATION[cue];
    if (pattern && typeof navigator !== 'undefined' && 'vibrate' in navigator) navigator.vibrate(pattern);
    const context = this.audio();
    if (!context) return;
    const volume = VOLUME[cue] ?? 0.18;
    for (const [frequency, at, duration] of TONES[cue]) {
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      const start = context.currentTime + at;
      oscillator.type = 'sine';
      oscillator.frequency.value = frequency;
      // Lên/xuống âm lượng thật nhanh để không có tiếng "bụp" ở đầu và cuối nốt.
      gain.gain.setValueAtTime(0.0001, start);
      gain.gain.exponentialRampToValueAtTime(volume, start + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
      oscillator.connect(gain).connect(context.destination);
      oscillator.start(start);
      oscillator.stop(start + duration + 0.02);
    }
  }

  close(): void {
    void this.context?.close().catch(() => undefined);
    this.context = null;
  }
}

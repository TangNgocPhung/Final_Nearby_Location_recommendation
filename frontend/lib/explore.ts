/**
 * Săn địa danh Sài Gòn — kiểu dữ liệu khớp backend/app/explore.py, cộng tiện
 * ích thu nhỏ ảnh trước khi gửi.
 */

export type ExploreCollection = {
  id: string;
  title: string;
  icon: string;
  description: string;
  total: number;
  discovered: number;
  completed: boolean;
};

export type ExplorePlace = {
  poiId: string;
  name: string;
  category: string;
  categoryLabel: string;
  address: string | null;
  latitude: number;
  longitude: number;
  distanceMeters: number;
  radiusMeters: number;
  contentType: string;
  collections: string[];
  teaser: string;
  discovered: boolean;
  discoveredAt: string | null;
  /** data URL ảnh của CHÍNH người chơi (kể cả ảnh chưa công khai) */
  photoThumb: string | null;
  photoStatus: 'verified' | 'pending' | null;
};

export type ExploreOverview = {
  total: number;
  discovered: number;
  collections: ExploreCollection[];
  places: ExplorePlace[];
};

/** Một claim có nguồn — cùng dạng `poi_knowledge.historical_events` / `interesting_facts`. */
export type ExploreClaim = {
  title?: string | null;
  description: string;
  source?: string | null;
};

export type ExploreStory = {
  contentType: string;
  contentTypeLabel: string;
  intro: string | null;
  specialty: string | null;
  historicalContext: string | null;
  historicalEvents: ExploreClaim[];
  interestingFacts: ExploreClaim[];
  source: string | null;
};

export type ExploreVerification = {
  match: 'yes' | 'no' | 'unsure';
  confidence: number;
  seen: string;
} | null;

export type DiscoverResult =
  | {
      status: 'too_far';
      poiId: string;
      name: string;
      distanceMeters: number;
      allowedMeters: number;
    }
  | {
      status: 'bad_image';
      poiId: string;
      name: string;
      detail: string;
      distanceMeters: number;
      allowedMeters: number;
    }
  | {
      status: 'photo_rejected';
      poiId: string;
      name: string;
      distanceMeters: number;
      allowedMeters: number;
      verification: ExploreVerification;
    }
  | {
      status: 'discovered' | 'rediscovered';
      poiId: string;
      name: string;
      distanceMeters: number;
      allowedMeters: number;
      photo: { id: string; status: 'verified' | 'pending'; isPublic: boolean; url: string | null };
      verification: ExploreVerification;
      story: ExploreStory;
      progress: { total: number; discovered: number };
      collections: ExploreCollection[];
      completedCollections: ExploreCollection[];
    };

const MAX_SIDE = 1280;
const JPEG_QUALITY = 0.85;

/**
 * Ảnh chụp từ điện thoại (4000 px, 3-8 MB) → JPEG ≤ 1280 px, trả chuỗi base64.
 *
 * Thu nhỏ Ở TRÌNH DUYỆT: gửi nguyên ảnh qua 4G tốn cả chục giây và vượt trần
 * body của gateway. Vẽ lại qua canvas còn bỏ luôn EXIF (có toạ độ GPS) — backend
 * vẫn mã hoá lại lần nữa, nhưng dữ liệu riêng tư không rời máy thì tốt hơn.
 */
export async function resizeImage(file: File): Promise<{ base64: string; previewUrl: string }> {
  // createImageBitmap tự xoay ảnh theo thẻ EXIF Orientation ở trình duyệt mới.
  const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' });
  const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
  const width = Math.round(bitmap.width * scale);
  const height = Math.round(bitmap.height * scale);
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext('2d');
  if (!context) throw new Error('Trình duyệt không hỗ trợ xử lý ảnh');
  context.drawImage(bitmap, 0, 0, width, height);
  bitmap.close();
  const dataUrl = canvas.toDataURL('image/jpeg', JPEG_QUALITY);
  return { base64: dataUrl.split(',', 2)[1] ?? '', previewUrl: dataUrl };
}

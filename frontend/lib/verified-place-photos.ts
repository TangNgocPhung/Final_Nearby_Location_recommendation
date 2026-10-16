import type { PoiDetail, PoiPhoto } from '@/components/poi-detail-panel';

// Curated photographs are matched by both identity and location. A similar
// name elsewhere must never inherit another place's photograph.
const BINH_TAY_PHOTOS: PoiPhoto[] = [{
  id: 'commons-binh-tay-facade-2008',
  url: '/images/places/binh-tay-market.jpg',
  thumbUrl: '/images/places/binh-tay-market.jpg',
  width: 3296,
  height: 2472,
  title: 'Chợ Bình Tây · ảnh mặt tiền năm 2008',
  confidence: 'place',
  distanceMeters: null,
  source: 'wikimedia',
  sourceUrl: 'https://commons.wikimedia.org/wiki/File:Ch%E1%BB%A3_B%C3%ACnh_T%C3%A2y.jpg',
  license: 'CC BY 3.0',
  licenseUrl: 'https://creativecommons.org/licenses/by/3.0/',
  attribution: 'Bùi Thụy Đào Nguyên',
}];

function normalizeName(name: string): string {
  return name.normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .replace(/đ/gi, 'd').toLowerCase().trim().replace(/\s+/g, ' ');
}

export function verifiedPlacePhotos(
  place: Pick<PoiDetail, 'name' | 'category' | 'latitude' | 'longitude'> | null,
): PoiPhoto[] {
  if (!place || place.category !== 'market') return [];
  if (!['cho binh tay', 'binh tay market'].includes(normalizeName(place.name))) return [];
  if (!Number.isFinite(place.latitude) || !Number.isFinite(place.longitude)) return [];
  // Includes the OSM building and the older seed point, about 275 m away.
  const north = (place.latitude - 10.749375) * 111_320;
  const east = (place.longitude - 106.651078) * 111_320 * Math.cos(10.749375 * Math.PI / 180);
  return Math.hypot(north, east) <= 350 ? BINH_TAY_PHOTOS : [];
}

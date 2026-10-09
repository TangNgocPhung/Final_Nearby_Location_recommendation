/** Tên đường sát địa điểm, ước lượng từ bản đồ đường (OSRM /nearest) — xem
 * `nearest_streets` ở backend/app/directions.py. Hai tên = địa điểm ở góc giao lộ. */
export type StreetAddress = { streets: string[]; distanceMeters: number };

// Tên đường OSM ở VN lúc có lúc không kèm loại đường ("Đường số 7", "Quốc lộ
// 1A" vs "Nguyễn Thị Nhỏ"). Chỉ thêm chữ "Đường" khi tên chưa tự nói loại đường.
const ROAD_PREFIX = /^(đường|hẻm|ngõ|kiệt|quốc lộ|tỉnh lộ|xa lộ|đại lộ|cầu|ql|tl|dt|đt)\b/i;

function withRoadWord(name: string): string {
  return ROAD_PREFIX.test(name) ? name : `Đường ${name}`;
}

export function formatStreetAddress(street: StreetAddress): string {
  const [first, second] = street.streets;
  if (second) return `Góc ${first} – ${second}`;
  return withRoadWord(first);
}

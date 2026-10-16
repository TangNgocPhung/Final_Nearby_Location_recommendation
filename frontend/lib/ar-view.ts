/** Signed camera offset, or null when the place is outside the camera view.
 * Distance/category must not bypass this: nearby schools follow the camera too.
 */
export function arViewOffset(bearing: number, heading: number, fov: number): number | null {
  const offset = ((((bearing - heading) % 360) + 540) % 360) - 180;
  return Math.abs(offset) <= fov / 2 + 4 ? offset : null;
}

/** Only GPS uncertainty defines the immediate arrival hint, not campus size. */
export function arArrivalDistance(accuracy: number): number {
  return Math.min(40, Math.max(15, accuracy + 15));
}

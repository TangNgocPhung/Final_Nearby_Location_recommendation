'use client';

import {
  Bell,
  BellOff,
  CheckCircle2,
  Landmark,
  Layers,
  MapPin,
  X,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  LANDMARK_ALERT_METERS,
  type LandmarkAlert,
  type NearbyLandmark,
} from '@/hooks/use-nearby-landmarks';
import { cn, formatMeters } from '@/lib/utils';

const VISIBLE_COUNT = 3;

/**
 * Thẻ "Địa danh gần bạn" trên trang chính: 2–3 địa danh gần nhất chưa khám phá,
 * kèm khoảng cách. Bấm một dòng để bay tới đó trên bản đồ và mở chi tiết.
 */
export function NearbyLandmarksCard({
  landmarks,
  discovered,
  total,
  loaded,
  failed,
  hasRealGps,
  layerOn,
  onToggleLayer,
  alertsEnabled,
  alertsPermission,
  onToggleAlerts,
  alert,
  onDismissAlert,
  onOpen,
}: {
  landmarks: NearbyLandmark[];
  discovered: number;
  total: number;
  loaded: boolean;
  failed: boolean;
  /** `false` khi vị trí là mô phỏng/mặc định: khoảng cách tính từ điểm đang chọn, không phải từ bạn. */
  hasRealGps: boolean;
  layerOn: boolean;
  onToggleLayer: () => void;
  alertsEnabled: boolean;
  alertsPermission: NotificationPermission | 'unsupported';
  onToggleAlerts: () => void;
  alert: LandmarkAlert | null;
  onDismissAlert: () => void;
  onOpen: (landmark: NearbyLandmark) => void;
}) {
  // Ưu tiên chỗ chưa tới; khi đã khám phá hết thì vẫn hiện vài nơi gần nhất để thẻ không trống.
  const pending = landmarks.filter((place) => !place.discovered);
  const shown = (pending.length > 0 ? pending : landmarks).slice(
    0,
    VISIBLE_COUNT,
  );
  const allDone = loaded && total > 0 && discovered >= total;

  if (failed && !loaded) return null;
  if (loaded && landmarks.length === 0) return null;

  const alertsBlocked =
    alertsPermission === 'denied' || alertsPermission === 'unsupported';

  return (
    <section
      aria-label="Địa danh gần bạn"
      className="glass-card shrink-0 space-y-3 rounded-3xl p-4"
    >
      <div className="flex items-center gap-2">
        <span className="grid size-8 shrink-0 place-items-center rounded-xl bg-amber-50 text-amber-600 ring-1 ring-amber-600/10 dark:bg-amber-500/15 dark:text-amber-300">
          <Landmark className="size-4" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-sm leading-tight font-semibold">
            Địa danh gần bạn
          </h2>
          <p className="truncate text-xs text-muted-foreground">
            {hasRealGps ? 'Quanh vị trí của bạn' : 'Quanh vị trí đang chọn'}
            {loaded && ` · đã khám phá ${discovered}/${total}`}
          </p>
        </div>
        <Button
          type="button"
          variant={layerOn ? 'default' : 'outline'}
          size="icon"
          className="size-8 rounded-full"
          onClick={onToggleLayer}
          aria-pressed={layerOn}
          aria-label={
            layerOn ? 'Ẩn địa danh trên bản đồ' : 'Hiện địa danh trên bản đồ'
          }
          title={
            layerOn ? 'Ẩn địa danh trên bản đồ' : 'Hiện địa danh trên bản đồ'
          }
        >
          <Layers className="size-4" />
        </Button>
        <Button
          type="button"
          variant={alertsEnabled ? 'default' : 'outline'}
          size="icon"
          className="size-8 rounded-full"
          onClick={onToggleAlerts}
          disabled={alertsBlocked && !alertsEnabled}
          aria-pressed={alertsEnabled}
          aria-label={
            alertsEnabled
              ? 'Tắt nhắc khi tới gần địa danh'
              : 'Nhắc tôi khi tới gần địa danh'
          }
          title={
            alertsPermission === 'denied'
              ? 'Thông báo đang bị chặn trong trình duyệt'
              : alertsPermission === 'unsupported'
                ? 'Trình duyệt không hỗ trợ thông báo'
                : alertsEnabled
                  ? `Đang nhắc khi cách địa danh chưa ghé dưới ${LANDMARK_ALERT_METERS} m`
                  : `Nhắc tôi khi tới trong ${LANDMARK_ALERT_METERS} m (bật theo dõi vị trí)`
          }
        >
          {alertsEnabled ? (
            <Bell className="size-4" />
          ) : (
            <BellOff className="size-4" />
          )}
        </Button>
      </div>

      {alert && (
        <output className="flex items-start gap-2 rounded-2xl border border-amber-300/60 bg-amber-50 p-3 text-sm dark:border-amber-500/30 dark:bg-amber-500/10">
          <MapPin
            className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-300"
            aria-hidden
          />
          <div className="min-w-0 flex-1">
            <p className="font-semibold">
              Bạn đang ở gần {alert.landmark.name}!
            </p>
            <p className="text-xs text-muted-foreground">
              Cách {formatMeters(alert.landmark.distanceMeters)} · chụp ảnh ở đó
              để mở khoá câu chuyện.
            </p>
            <button
              type="button"
              onClick={() => onOpen(alert.landmark)}
              className="mt-1 text-xs font-semibold text-primary underline-offset-2 hover:underline"
            >
              Xem địa danh
            </button>
          </div>
          <button
            type="button"
            onClick={onDismissAlert}
            aria-label="Đóng nhắc nhở"
            className="grid size-6 shrink-0 place-items-center rounded-full text-muted-foreground hover:bg-black/5"
          >
            <X className="size-3.5" />
          </button>
        </output>
      )}

      {!loaded ? (
        <div className="space-y-2" aria-hidden>
          {Array.from({ length: VISIBLE_COUNT }, (_, index) => (
            <div
              key={index}
              className="h-12 animate-pulse rounded-2xl bg-muted/60"
            />
          ))}
        </div>
      ) : (
        <ul className="grid grid-cols-1 gap-2">
          {shown.map((place) => {
            const inside = place.distanceMeters <= place.radiusMeters;
            return (
              <li key={place.poiId}>
                <button
                  type="button"
                  onClick={() => onOpen(place)}
                  className="flex w-full items-center gap-3 rounded-2xl border border-border/70 bg-white/70 px-3 py-2.5 text-left transition-colors hover:border-primary/30 hover:bg-white dark:bg-card/60"
                >
                  <span
                    className={cn(
                      'grid size-8 shrink-0 place-items-center rounded-full text-sm font-bold',
                      place.discovered
                        ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-300'
                        : 'bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-300',
                    )}
                    aria-hidden
                  >
                    {place.discovered ? (
                      <CheckCircle2 className="size-4" />
                    ) : (
                      '?'
                    )}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold">
                      {place.name}
                    </span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {place.categoryLabel}
                      {inside &&
                        !place.discovered &&
                        ' · bạn đang ở đây — chụp ảnh để mở khoá'}
                    </span>
                  </span>
                  <span className="shrink-0 text-sm font-semibold text-primary tabular-nums">
                    {formatMeters(place.distanceMeters)}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}

      {allDone && (
        <p className="text-xs text-muted-foreground">
          Bạn đã khám phá hết địa danh — đây là các nơi gần nhất.
        </p>
      )}
    </section>
  );
}

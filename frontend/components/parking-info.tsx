'use client';

import { useCallback, useEffect, useState } from 'react';
import { CircleParking, ExternalLink, LoaderCircle, Send } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  TIER_STYLES,
  UNIT_LABELS,
  VEHICLE_LABELS,
  formatEstimatedCost,
  formatHours,
  formatPrice,
  type ParkingDetail,
  type PriceUnit,
  type Vehicle,
} from '@/lib/parking';
import { cn } from '@/lib/utils';

const REPORT_UNITS: PriceUnit[] = ['turn', 'hour', 'day', 'night', 'month', 'kwh'];

/**
 * Mục "Thông tin gửi xe" trong panel chi tiết của bãi xe / trạm sạc: giá từng
 * loại xe (mỗi giá ghi rõ nguồn và mức tin cậy), giờ mở cửa, sức chứa, cổng
 * sạc — và form để người dùng báo giá/giờ thực tế (crowdsource), vì >99% bãi
 * xe trên OSM không có giá. Xem backend/app/parking.py.
 */
export function ParkingInfo({
  apiBaseUrl,
  poiId,
  sessionId,
}: {
  apiBaseUrl: string;
  poiId: string;
  sessionId: string;
}) {
  const [detail, setDetail] = useState<ParkingDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [formOpen, setFormOpen] = useState(false);
  const [vehicle, setVehicle] = useState<Vehicle>('motorbike');
  const [amount, setAmount] = useState('');
  const [unit, setUnit] = useState<PriceUnit>('turn');
  const [hours, setHours] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch(`${apiBaseUrl}/api/v1/parking/${poiId}`);
      const data = res.ok ? ((await res.json()) as ParkingDetail) : null;
      setDetail(data);
      if (data) {
        const first = Object.keys(data.prices)[0] as Vehicle | undefined;
        if (first) setVehicle(first);
        if (data.kind === 'charging_station') setUnit('kwh');
      }
    } catch {
      setDetail(null);
    } finally {
      setLoading(false);
    }
  }, [apiBaseUrl, poiId]);

  useEffect(() => {
    // Tải dữ liệu từ API (hệ thống bên ngoài) khi mở panel — cùng mẫu với
    // use-poi-detail.ts.
    // oxlint-disable-next-line react/react-compiler
    void load();
  }, [load]);

  const submit = async (event: React.SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    const amountVnd = amount.trim() ? Number(amount.replace(/[.,\s]/g, '')) : null;
    if (amountVnd === null && !hours.trim()) {
      setMessage({ ok: false, text: 'Hãy nhập giá hoặc giờ mở cửa.' });
      return;
    }
    if (amountVnd !== null && (!Number.isFinite(amountVnd) || amountVnd < 0)) {
      setMessage({ ok: false, text: 'Giá phải là một số tiền hợp lệ.' });
      return;
    }
    setSubmitting(true);
    setMessage(null);
    try {
      const res = await fetch(`${apiBaseUrl}/api/v1/parking/${poiId}/reports`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          vehicle,
          amount_vnd: amountVnd,
          unit: amountVnd === null ? null : unit,
          opening_hours: hours.trim() || null,
        }),
      });
      if (res.status === 409) {
        setMessage({ ok: false, text: 'Hôm nay bạn đã báo cho bãi này rồi, cảm ơn bạn!' });
      } else if (res.status === 422) {
        setMessage({ ok: false, text: 'Giờ mở cửa cần có dạng 06:00-22:00 hoặc 24/7.' });
      } else if (!res.ok) {
        setMessage({ ok: false, text: 'Chưa gửi được, bạn thử lại sau nhé.' });
      } else {
        setDetail((await res.json()) as ParkingDetail);
        setMessage({ ok: true, text: 'Cảm ơn bạn! Giá của bạn đã được ghi nhận.' });
        setAmount('');
        setHours('');
        setFormOpen(false);
      }
    } catch {
      setMessage({ ok: false, text: 'Chưa gửi được, bạn thử lại sau nhé.' });
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 px-4 py-3 text-sm text-muted-foreground">
        <LoaderCircle className="size-4 animate-spin" /> Đang tải thông tin gửi xe…
      </div>
    );
  }
  if (!detail) return null;

  const vehicles = Object.keys(detail.prices) as Vehicle[];

  return (
    <section className="space-y-3 px-4 py-4">
      <h3 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground">
        <CircleParking className="size-4" />
        {detail.kind === 'charging_station' ? 'THÔNG TIN SẠC XE' : 'THÔNG TIN GỬI XE'}
      </h3>

      <ul className="space-y-2">
        {vehicles.map((item) => {
          const price = detail.prices[item];
          if (!price) return null;
          const estimate = formatEstimatedCost(price);
          return (
            <li key={item} className="rounded-lg border border-border p-2.5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-sm font-medium">
                  {VEHICLE_LABELS[item]}
                  {item !== 'ev' && detail.vehicles[item as 'motorbike' | 'car' | 'bicycle'] === 'unknown' && (
                    <span className="ml-1 text-xs font-normal text-muted-foreground">(chưa chắc nhận)</span>
                  )}
                </span>
                <span
                  className={cn('rounded-full px-2 py-0.5 text-xs font-semibold', TIER_STYLES[price.tier].className)}
                >
                  {formatPrice(price)}
                </span>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                {TIER_STYLES[price.tier].label}
                {price.reports ? ` · ${price.reports} lượt báo` : ''}
                {price.unitAssumed ? ' · đơn vị "lượt" là giả định' : ''}
                {estimate && ` · ≈ ${estimate} nếu gửi ${Math.round(detail.minutes / 60)} giờ`}
              </p>
              {price.legalReference && (
                <a
                  href={price.legalReference.url}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-0.5 flex items-center gap-1 text-xs text-muted-foreground underline-offset-2 hover:underline"
                >
                  {price.legalReference.document} — {price.legalReference.status}
                  <ExternalLink className="size-3" />
                </a>
              )}
            </li>
          );
        })}
      </ul>

      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
        <dt className="text-muted-foreground">Giờ mở cửa</dt>
        <dd>
          {detail.hours.raw ?? 'Chưa rõ'}
          <span className="ml-1 text-xs text-muted-foreground">
            ({formatHours(detail.hours)}
            {detail.hours.source === 'community' ? ' · người dùng báo' : ''})
          </span>
        </dd>
        {detail.capacity !== null && (
          <>
            <dt className="text-muted-foreground">Sức chứa</dt>
            <dd>{detail.capacity} chỗ</dd>
          </>
        )}
        {detail.operator && (
          <>
            <dt className="text-muted-foreground">Đơn vị</dt>
            <dd>{detail.operator}</dd>
          </>
        )}
        {detail.sockets.length > 0 && (
          <>
            <dt className="text-muted-foreground">Cổng sạc</dt>
            <dd>
              {detail.sockets
                .map((s) => `${s.type}${s.count ? ` ×${s.count}` : ''}${s.powerKw ? ` · ${s.powerKw} kW` : ''}`)
                .join(', ')}
            </dd>
          </>
        )}
        {detail.priceRaw && (
          <>
            <dt className="text-muted-foreground">Ghi chú gốc</dt>
            <dd className="text-xs text-muted-foreground">&ldquo;{detail.priceRaw}&rdquo; (OpenStreetMap)</dd>
          </>
        )}
      </dl>

      {message && (
        <p className={cn('text-sm', message.ok ? 'text-emerald-600 dark:text-emerald-400' : 'text-destructive')}>
          {message.text}
        </p>
      )}

      {formOpen ? (
        <form onSubmit={(event) => void submit(event)} className="space-y-2 rounded-lg border border-border p-3">
          <p className="text-sm font-medium">Bạn vừa gửi xe ở đây? Báo giá thực tế giúp mọi người</p>
          <div className="flex flex-wrap gap-2">
            <select
              value={vehicle}
              onChange={(event) => setVehicle(event.target.value as Vehicle)}
              aria-label="Loại xe"
              className="h-9 rounded-md border border-input bg-background px-2 text-sm"
            >
              {vehicles.map((item) => (
                <option key={item} value={item}>
                  {VEHICLE_LABELS[item]}
                </option>
              ))}
            </select>
            <input
              inputMode="numeric"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
              placeholder="Giá, vd 5000"
              aria-label="Giá (đồng)"
              className="h-9 w-28 rounded-md border border-input bg-background px-2 text-sm"
            />
            <select
              value={unit}
              onChange={(event) => setUnit(event.target.value as PriceUnit)}
              aria-label="Đơn vị tính"
              className="h-9 rounded-md border border-input bg-background px-2 text-sm"
            >
              {REPORT_UNITS.map((item) => (
                <option key={item} value={item}>
                  / {UNIT_LABELS[item]}
                </option>
              ))}
            </select>
          </div>
          <input
            value={hours}
            onChange={(event) => setHours(event.target.value)}
            placeholder="Giờ mở cửa (không bắt buộc), vd 06:00-22:00 hoặc 24/7"
            aria-label="Giờ mở cửa"
            className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm"
          />
          <div className="flex gap-2">
            <Button type="submit" size="sm" disabled={submitting}>
              {submitting ? <LoaderCircle className="size-4 animate-spin" /> : <Send className="size-4" />}
              Gửi
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setFormOpen(false)}>
              Huỷ
            </Button>
          </div>
        </form>
      ) : (
        <Button type="button" size="sm" variant="outline" onClick={() => setFormOpen(true)}>
          Báo giá / giờ mở cửa thực tế
          {detail.reportCount > 0 && (
            <span className="text-xs text-muted-foreground">({detail.reportCount} lượt báo)</span>
          )}
        </Button>
      )}
    </section>
  );
}

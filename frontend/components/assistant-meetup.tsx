'use client';

import { useEffect, useRef, useState } from 'react';
import {
  ArrowLeft,
  CircleParking,
  Crosshair,
  LoaderCircle,
  LocateFixed,
  Plus,
  Star,
  Trash2,
  Users,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  formatMeters,
  type AssistantOverlay,
  type MeetupPlan,
  type MeetupResult,
} from '@/lib/assistant';
import { authHeaders } from '@/lib/auth';
import { cn } from '@/lib/utils';

type Participant = {
  key: string;
  label: string;
  query: string;
  place: { name: string; latitude: number; longitude: number } | null;
  isMe: boolean;
};

type SuggestItem = { id: string; name: string; address?: string | null; latitude: number; longitude: number };

const CATEGORIES = [
  { value: 'cafe', label: 'Cà phê' },
  { value: 'food', label: 'Ăn uống' },
  { value: 'bar', label: 'Bar / pub' },
] as const;

const LETTERS = 'ABCDEF';

let nextKey = 0;
function newParticipant(label: string, isMe = false): Participant {
  nextKey += 1;
  return { key: `p${nextKey}`, label, query: '', place: null, isMe };
}

/**
 * Điểm hẹn công bằng — xem backend/app/assistant.plan_meetup. Mỗi người là một
 * dòng: "Vị trí của tôi", gõ tên một địa điểm (gợi ý từ POI thật), hoặc chạm
 * lên bản đồ.
 */
export function AssistantMeetup({
  apiBaseUrl,
  position,
  onBack,
  onViewPoi,
  onMapOverlay,
  onPickOnMap,
}: {
  apiBaseUrl: string;
  position: { latitude: number; longitude: number };
  onBack: () => void;
  onViewPoi: (poiId: string) => void;
  onMapOverlay: (overlay: AssistantOverlay | null) => void;
  /** chờ người dùng chạm lên bản đồ; `null` nghĩa là huỷ */
  onPickOnMap: (callback: ((latitude: number, longitude: number) => void) | null) => void;
}) {
  const [people, setPeople] = useState<Participant[]>(() => [
    newParticipant('Tôi', true),
    newParticipant('Bạn B'),
    newParticipant('Bạn C'),
  ]);
  const [category, setCategory] = useState<(typeof CATEGORIES)[number]['value']>('cafe');
  const [needParking, setNeedParking] = useState(false);
  const [plan, setPlan] = useState<MeetupPlan | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [picking, setPicking] = useState<string | null>(null);
  const [focusKey, setFocusKey] = useState<string | null>(null);
  const [options, setOptions] = useState<SuggestItem[]>([]);
  const suggestAbort = useRef<AbortController | null>(null);

  const located = people.map((person) =>
    person.isMe
      ? { ...person, place: { name: 'Vị trí của tôi', ...position } }
      : person,
  );
  const readyPeople = located.filter((person) => person.place);

  useEffect(
    () => () => {
      onMapOverlay(null);
      onPickOnMap(null);
    },
    [onMapOverlay, onPickOnMap],
  );

  // Vẽ người trong nhóm (và kết quả, nếu có) lên bản đồ.
  useEffect(() => {
    const points: AssistantOverlay['points'] = located.flatMap((person, index) =>
      person.place
        ? [
            {
              id: person.key,
              latitude: person.place.latitude,
              longitude: person.place.longitude,
              label: LETTERS[index] ?? '?',
              tone: 'person' as const,
              title: `${person.label}: ${person.place.name}`,
            },
          ]
        : [],
    );
    for (const [index, result] of (plan?.results ?? []).entries()) {
      points.push({
        id: result.poiId,
        latitude: result.latitude,
        longitude: result.longitude,
        label: String(index + 1),
        tone: 'result',
        title: result.name,
        poiId: result.poiId,
      });
    }
    onMapOverlay(points.length ? { line: null, points } : null);
    // `located` dựng lại mỗi render — phụ thuộc vào dữ liệu gốc của nó.
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [people, plan, position.latitude, position.longitude, onMapOverlay]);

  const update = (key: string, patch: Partial<Participant>) =>
    setPeople((prev) => prev.map((person) => (person.key === key ? { ...person, ...patch } : person)));

  const searchPlaces = async (key: string, text: string) => {
    update(key, { query: text, place: null });
    setFocusKey(key);
    suggestAbort.current?.abort();
    if (text.trim().length < 2) {
      setOptions([]);
      return;
    }
    const controller = new AbortController();
    suggestAbort.current = controller;
    try {
      const params = new URLSearchParams({
        q: text.trim(),
        lat: String(position.latitude),
        lng: String(position.longitude),
        limit: '5',
      });
      const res = await fetch(`${apiBaseUrl}/api/v1/pois/suggest?${params}`, { signal: controller.signal });
      if (res.ok) setOptions((await res.json()) as SuggestItem[]);
    } catch {
      /* gõ tiếp thì request cũ bị huỷ — bỏ qua */
    }
  };

  const pickOnMap = (key: string) => {
    setPicking(key);
    onPickOnMap((latitude, longitude) => {
      update(key, {
        place: { name: `Điểm chọn trên bản đồ`, latitude, longitude },
        query: 'Điểm chọn trên bản đồ',
      });
      setPicking(null);
    });
  };

  const submit = async () => {
    if (readyPeople.length < 2) {
      setError('Cần ít nhất 2 người có vị trí.');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${apiBaseUrl}/api/v1/assistant/meetup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          participants: readyPeople.map((person) => ({
            label: person.label,
            latitude: person.place!.latitude,
            longitude: person.place!.longitude,
          })),
          category,
          need_parking: needParking,
        }),
      });
      if (res.status === 401) {
        setError('Phiên đăng nhập đã hết hạn, bạn đăng nhập lại để dùng Hẹn nhóm nhé.');
        return;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setPlan((await res.json()) as MeetupPlan);
    } catch {
      setError('Chưa tìm được điểm hẹn, bạn thử lại sau nhé.');
    } finally {
      setLoading(false);
    }
  };

  const best = plan?.results[0];
  const baseline = plan?.baseline;
  const baselineWorse =
    best && baseline && baseline.poiId !== best.poiId && baseline.maxMinutes > best.maxMinutes;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2">
        <Button type="button" size="icon" variant="ghost" onClick={onBack} aria-label="Quay lại trò chuyện">
          <ArrowLeft className="size-4" />
        </Button>
        <Users className="size-4 text-primary" aria-hidden />
        <p className="text-sm font-semibold">Hẹn nhóm — quán công bằng</p>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3 text-sm">
        <p className="text-xs text-muted-foreground">
          Chọn quán mà người đi <b>xa nhất</b> cũng không phải đi quá lâu — tính theo thời gian chạy xe
          máy trên đường thật (OSRM), không phải đường chim bay.
        </p>

        <div className="space-y-2">
          {located.map((person, index) => (
            <div key={person.key} className="relative">
              <div className="flex items-center gap-1.5">
                <span className="grid size-6 shrink-0 place-items-center rounded-full bg-sky-600 text-[11px] font-bold text-white">
                  {LETTERS[index]}
                </span>
                {person.isMe ? (
                  <p className="flex flex-1 items-center gap-1 rounded-md border border-border bg-muted/50 px-2.5 py-1.5 text-xs">
                    <LocateFixed className="size-3.5 text-primary" aria-hidden /> Vị trí của tôi
                  </p>
                ) : (
                  <Input
                    value={person.query}
                    onChange={(event) => void searchPlaces(person.key, event.target.value)}
                    onFocus={() => setFocusKey(person.key)}
                    placeholder={`${person.label} ở đâu? (vd: Gò Vấp, Landmark 81)`}
                    className={cn('h-8 text-xs', person.place && 'border-emerald-500')}
                  />
                )}
                {!person.isMe && (
                  <>
                    <button
                      type="button"
                      onClick={() => pickOnMap(person.key)}
                      aria-label={`Chọn vị trí ${person.label} trên bản đồ`}
                      title="Chạm lên bản đồ"
                      className={cn(
                        'grid size-8 shrink-0 place-items-center rounded-md border border-border hover:bg-muted',
                        picking === person.key && 'border-primary bg-primary/10 text-primary',
                      )}
                    >
                      <Crosshair className="size-4" />
                    </button>
                    {people.length > 2 && (
                      <button
                        type="button"
                        onClick={() => setPeople((prev) => prev.filter((item) => item.key !== person.key))}
                        aria-label={`Bỏ ${person.label}`}
                        className="grid size-8 shrink-0 place-items-center rounded-md text-muted-foreground hover:bg-muted"
                      >
                        <Trash2 className="size-3.5" />
                      </button>
                    )}
                  </>
                )}
              </div>
              {picking === person.key && (
                <p className="mt-1 pl-8 text-[11px] font-medium text-primary">
                  Chạm lên bản đồ để đặt vị trí của {person.label}…
                </p>
              )}
              {focusKey === person.key && !person.place && options.length > 0 && (
                <ul className="absolute inset-x-8 top-9 z-10 overflow-hidden rounded-md border border-border bg-popover shadow-lg">
                  {options.map((option) => (
                    <li key={option.id}>
                      <button
                        type="button"
                        onClick={() => {
                          update(person.key, {
                            query: option.name,
                            place: { name: option.name, latitude: option.latitude, longitude: option.longitude },
                          });
                          setOptions([]);
                          setFocusKey(null);
                        }}
                        className="block w-full truncate px-2.5 py-1.5 text-left text-xs hover:bg-muted"
                      >
                        {option.name}
                        {option.address ? <span className="text-muted-foreground"> · {option.address}</span> : null}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
          {people.length < 6 && (
            <button
              type="button"
              onClick={() =>
                setPeople((prev) => [...prev, newParticipant(`Bạn ${LETTERS[prev.length] ?? ''}`)])
              }
              className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
            >
              <Plus className="size-3.5" /> Thêm người
            </button>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          {CATEGORIES.map((item) => (
            <button
              key={item.value}
              type="button"
              onClick={() => setCategory(item.value)}
              className={cn(
                'rounded-full border px-3 py-1 text-xs font-medium transition',
                category === item.value
                  ? 'border-primary bg-primary text-primary-foreground'
                  : 'border-border hover:bg-muted',
              )}
            >
              {item.label}
            </button>
          ))}
          <label className="ml-auto flex items-center gap-1 text-xs">
            <input
              type="checkbox"
              checked={needParking}
              onChange={(event) => setNeedParking(event.target.checked)}
            />
            Có bãi xe gần
          </label>
        </div>

        <Button type="button" className="w-full" disabled={loading} onClick={() => void submit()}>
          {loading ? <LoaderCircle className="size-4 animate-spin" /> : <Users className="size-4" />}
          Tìm quán công bằng ({readyPeople.length} người)
        </Button>
        {error && <p className="text-xs text-destructive">{error}</p>}

        {plan?.status === 'none' && (
          <p className="rounded-lg bg-muted px-3 py-2 text-xs text-muted-foreground">
            Chưa tìm thấy quán phù hợp quanh điểm giữa của nhóm{needParking ? ' có bãi xe gần' : ''}. Thử bỏ
            bớt điều kiện hoặc đổi loại quán.
          </p>
        )}

        {plan?.status === 'ready' && best && (
          <>
            {baselineWorse && baseline && (
              <div className="rounded-lg border border-emerald-600/20 bg-emerald-50 px-3 py-2 text-xs dark:bg-emerald-950/30">
                Nếu chọn quán ngay <b>điểm giữa trên bản đồ</b> ({baseline.name}), người xa nhất mất{' '}
                <b>{baseline.maxMinutes} phút</b>. Quán gợi ý số 1 chỉ <b>{best.maxMinutes} phút</b> — nhanh
                hơn {baseline.maxMinutes - best.maxMinutes} phút cho người thiệt nhất.
              </div>
            )}
            <ol className="space-y-1.5">
              {plan.results.map((result, index) => (
                <MeetupCard
                  key={result.poiId}
                  index={index}
                  result={result}
                  labels={readyPeople.map((person) => person.label)}
                  onView={onViewPoi}
                />
              ))}
            </ol>
            {plan.approximate ? (
              // Máy chủ định tuyến không trả lời: số phút là khoảng cách chim bay
              // × hệ số — phải nói thẳng, không để người đọc tưởng là giờ chạy thật.
              <p className="rounded-md bg-amber-100 px-2 py-1.5 text-[11px] text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
                ⚠️ Máy chủ định tuyến đang tắt nên số phút hiện là <b>ước tính</b> từ khoảng cách đường chim bay,
                chưa phải thời gian chạy xe thật. Đã xét {plan.candidateCount} quán quanh điểm giữa của nhóm.
              </p>
            ) : (
              <p className="text-[11px] text-muted-foreground">
                Thời gian xe máy theo đường thật (OSRM, hồ sơ xe máy riêng, chưa tính kẹt xe). Đã xét{' '}
                {plan.candidateCount} quán quanh điểm giữa của nhóm.
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function MeetupCard({
  index,
  result,
  labels,
  onView,
}: {
  index: number;
  result: MeetupResult;
  labels: string[];
  onView: (poiId: string) => void;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={() => onView(result.poiId)}
        className="w-full rounded-lg border border-border px-2.5 py-2 text-left transition hover:bg-muted"
      >
        <div className="flex items-center gap-2">
          <span className="grid size-6 shrink-0 place-items-center rounded-full bg-orange-500 text-[11px] font-bold text-white">
            {index + 1}
          </span>
          <span className="min-w-0 flex-1 truncate font-medium">{result.name}</span>
          {result.rating != null && (
            <span className="flex shrink-0 items-center gap-0.5 text-xs text-muted-foreground">
              <Star className="size-3 fill-current" /> {result.rating.toFixed(1)}
            </span>
          )}
        </div>
        <p className="mt-1 pl-8 text-xs">
          <b>Tối đa {result.maxMinutes} phút</b>
          <span className="text-muted-foreground"> · chênh {result.spreadMinutes} phút giữa các người</span>
        </p>
        <div className="mt-1 flex flex-wrap gap-1 pl-8">
          {result.minutes.map((minutes, i) => (
            <span
              key={i}
              className={cn(
                'rounded-full px-1.5 py-0.5 text-[10px] font-medium',
                minutes === result.maxMinutes ? 'bg-amber-500/15 text-amber-700 dark:text-amber-400' : 'bg-muted',
              )}
            >
              {labels[i] ?? LETTERS[i]} {minutes}′
            </span>
          ))}
          {result.parking && (
            <span className="inline-flex items-center gap-0.5 rounded-full bg-sky-500/10 px-1.5 py-0.5 text-[10px] font-medium text-sky-700 dark:text-sky-400">
              <CircleParking className="size-3" /> {result.parking.name || 'Bãi xe'} {formatMeters(result.parking.distanceMeters)}
            </span>
          )}
        </div>
      </button>
    </li>
  );
}

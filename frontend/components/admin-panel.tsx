'use client';

import {
  type ReactNode,
  type SyntheticEvent,
  useCallback,
  useEffect,
  useState,
} from 'react';
import {
  Activity,
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  Clock3,
  Download,
  KeyRound,
  LoaderCircle,
  Lock,
  LockOpen,
  MapPin,
  MessageSquare,
  RefreshCw,
  Search,
  ShieldCheck,
  ShieldMinus,
  Star,
  Trash2,
  Users,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { LandmarksTab } from '@/components/admin-landmarks';
import { Switch } from '@/components/ui/switch';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { apiRequest, type UserRole } from '@/lib/auth';
import { cn } from '@/lib/utils';

type DailyActivity = {
  date: string;
  events: number;
  sessions: number;
  searches: number;
  navigations: number;
};

type Overview = {
  periodDays: number;
  users: number;
  admins: number;
  lockedUsers: number;
  newUsers7d: number;
  newUsersPeriod: number;
  pois: number;
  reviews: number;
  reviews7d: number;
  reviewsPeriod: number;
  savedPlaces: number;
  events24h: number;
  activeUsers7d: number;
  activeUsersPeriod: number;
  sessions24h: number;
  sessions7d: number;
  sessionsPeriod: number;
  eventsPending: number;
  eventsFailed: number;
  lastEventAt: string | null;
  dailyActivity: DailyActivity[];
  eventTypes7d: { type: string; count: number }[];
  eventTypesPeriod: { type: string; count: number }[];
  topPois30d: {
    id: string;
    name: string;
    category: string;
    clicks: number;
    navigations: number;
    dwells: number;
  }[];
  topPoisPeriod: {
    id: string;
    name: string;
    category: string;
    clicks: number;
    navigations: number;
    dwells: number;
  }[];
  poiCategories: { label: string; count: number }[];
  poiCoverage: {
    withRating: number;
    withContact: number;
    withHours: number;
    withPhotos: number;
    withKnowledge: number;
    withVideos: number;
    sponsored: number;
  };
  ratingDistribution: { rating: number; count: number }[];
  averageRating: number | null;
  savedByKind: { home: number; work: number; saved: number };
  recentUsers: AdminUser[];
};

const EVENT_LABELS: Record<string, string> = {
  search: 'Tìm kiếm',
  location_ping: 'Cập nhật vị trí',
  poi_impression: 'Hiển thị địa điểm',
  poi_dwell: 'Xem lâu một địa điểm',
  poi_click: 'Mở chi tiết địa điểm',
  navigation_start: 'Bắt đầu chỉ đường',
  review: 'Gửi đánh giá',
};

type AdminUser = {
  id: string;
  username: string;
  displayName: string | null;
  role: UserRole;
  isActive: boolean;
  createdAt: string;
  lastLoginAt: string | null;
  savedCount: number;
  reviewCount: number;
};

type AdminReview = {
  id: string;
  poiId: string;
  poiName: string;
  authorName: string | null;
  username: string | null;
  anonymous: boolean;
  rating: number;
  title: string | null;
  body: string;
  updatedAt: string;
};

const numberFormat = new Intl.NumberFormat('vi-VN');
const dateFormat = new Intl.DateTimeFormat('vi-VN', {
  dateStyle: 'short',
  timeStyle: 'short',
});

function formatDate(value: string | null) {
  return value ? dateFormat.format(new Date(value)) : '—';
}

function ErrorLine({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p
      role="alert"
      className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive"
    >
      {message}
    </p>
  );
}

/** Trang quản trị — chỉ gắn vào cây khi tài khoản là admin, và mọi API phía
 * sau đều tự kiểm lại quyền (`auth.require_admin`). */
export function AdminPanel({
  open,
  onOpenChange,
  apiBaseUrl,
  currentUserId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  apiBaseUrl: string;
  currentUserId: string;
}) {
  const [tab, setTab] = useState('overview');

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[calc(100dvh-1rem)] w-[calc(100%-1rem)] flex-col gap-4 overflow-hidden rounded-2xl border border-emerald-500/20 bg-background p-3 shadow-2xl sm:max-h-[92dvh] sm:w-[92vw] sm:max-w-[1600px] sm:gap-5 sm:p-6">
        <DialogHeader className="rounded-2xl border border-emerald-500/15 bg-gradient-to-r from-emerald-500/12 via-emerald-500/5 to-transparent p-4 pr-10 sm:p-5 sm:pr-12">
          <DialogTitle className="flex items-center gap-3 text-lg sm:text-xl">
            <span className="flex size-9 items-center justify-center rounded-xl bg-emerald-500/10">
              <ShieldCheck className="size-5 text-emerald-600 dark:text-emerald-400" />
            </span>
            Trang quản trị
          </DialogTitle>
          <DialogDescription>
            Quản lý tài khoản, phân quyền, kiểm duyệt đánh giá và địa danh cho
            Săn địa danh.
          </DialogDescription>
        </DialogHeader>
        <Tabs
          value={tab}
          onValueChange={(value) => setTab(String(value))}
          className="min-h-0 flex-1 gap-3"
        >
          <TabsList className="h-11 w-full justify-start gap-1 overflow-x-auto rounded-xl bg-muted/80 p-1 sm:h-12 sm:gap-2">
            <TabsTrigger value="overview">Tổng quan</TabsTrigger>
            <TabsTrigger value="users">Người dùng</TabsTrigger>
            <TabsTrigger value="reviews">Đánh giá</TabsTrigger>
            <TabsTrigger value="landmarks">Địa danh</TabsTrigger>
          </TabsList>
          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain pr-1">
            {open && (
              <>
                <TabsContent value="overview">
                  <OverviewTab apiBaseUrl={apiBaseUrl} onNavigate={setTab} />
                </TabsContent>
                <TabsContent value="users">
                  <UsersTab
                    apiBaseUrl={apiBaseUrl}
                    currentUserId={currentUserId}
                  />
                </TabsContent>
                <TabsContent value="reviews">
                  <ReviewsTab apiBaseUrl={apiBaseUrl} />
                </TabsContent>
                <TabsContent value="landmarks">
                  <LandmarksTab apiBaseUrl={apiBaseUrl} />
                </TabsContent>
              </>
            )}
          </div>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}

function OverviewTab({
  apiBaseUrl,
  onNavigate,
}: {
  apiBaseUrl: string;
  onNavigate: (tab: string) => void;
}) {
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadedAt, setLoadedAt] = useState<Date | null>(null);
  const [loading, setLoading] = useState(false);
  const [period, setPeriod] = useState(14);
  const [autoRefresh, setAutoRefresh] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(
        await apiRequest<Overview>(
          apiBaseUrl,
          `/api/v1/admin/overview?days=${period}`,
        ),
      );
      setLoadedAt(new Date());
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : 'Không tải được thống kê',
      );
    } finally {
      setLoading(false);
    }
  }, [apiBaseUrl, period]);

  useEffect(() => {
    // oxlint-disable-next-line react/react-compiler
    void load();
  }, [load]);

  useEffect(() => {
    if (!autoRefresh) return;
    const timer = window.setInterval(() => {
      if (!document.hidden) void load();
    }, 30_000);
    return () => window.clearInterval(timer);
  }, [autoRefresh, load]);

  if (!data) {
    return error ? (
      <ErrorLine message={error} />
    ) : (
      <LoaderCircle className="mx-auto my-8 size-6 animate-spin text-muted-foreground" />
    );
  }

  const tiles = [
    {
      label: 'Tài khoản',
      value: data.users,
      hint: `+${data.newUsersPeriod} trong ${period} ngày · ${data.activeUsersPeriod} đang hoạt động`,
      icon: Users,
      accent: 'text-sky-600 dark:text-sky-400',
    },
    {
      label: 'Quản trị viên',
      value: data.admins,
      hint: `${data.lockedUsers} tài khoản bị khoá`,
      icon: ShieldCheck,
      accent: 'text-violet-600 dark:text-violet-400',
    },
    {
      label: 'Đánh giá',
      value: data.reviews,
      hint:
        `+${data.reviewsPeriod} trong ${period} ngày` +
        (data.averageRating !== null
          ? ` · TB ${data.averageRating.toFixed(1)}★`
          : ''),
      icon: MessageSquare,
      accent: 'text-amber-600 dark:text-amber-400',
    },
    {
      label: 'Địa điểm đã lưu',
      value: data.savedPlaces,
      hint: `${data.savedByKind.home} nhà · ${data.savedByKind.work} công ty · ${data.savedByKind.saved} khác`,
      icon: Star,
      accent: 'text-orange-600 dark:text-orange-400',
    },
    {
      label: 'Địa điểm (POI)',
      value: data.pois,
      hint: `${data.poiCategories.length} nhóm danh mục`,
      icon: MapPin,
      accent: 'text-rose-600 dark:text-rose-400',
    },
    {
      label: 'Sự kiện 24 giờ',
      value: data.events24h,
      hint: `${data.sessions24h} phiên truy cập · ${data.sessionsPeriod} phiên / ${period} ngày`,
      icon: Activity,
      accent: 'text-emerald-600 dark:text-emerald-400',
    },
  ];

  const eventTotal = data.eventTypesPeriod.reduce(
    (sum, item) => sum + item.count,
    0,
  );
  const coverage = [
    { label: 'Có điểm đánh giá', value: data.poiCoverage.withRating },
    { label: 'Có giờ mở cửa', value: data.poiCoverage.withHours },
    { label: 'Có điện thoại / website', value: data.poiCoverage.withContact },
    { label: 'Có ảnh', value: data.poiCoverage.withPhotos },
    { label: 'Có bài giới thiệu', value: data.poiCoverage.withKnowledge },
    { label: 'Có video', value: data.poiCoverage.withVideos },
    { label: 'Đang được tài trợ', value: data.poiCoverage.sponsored },
  ];
  const ratingTotal = data.ratingDistribution.reduce(
    (sum, item) => sum + item.count,
    0,
  );
  const coveredFields = coverage
    .slice(0, 6)
    .reduce((sum, item) => sum + item.value, 0);
  const coverageScore = data.pois ? coveredFields / (data.pois * 6) : 0;
  const lastEventAgeMinutes = data.lastEventAt
    ? Math.max(
        0,
        Math.round(
          ((loadedAt?.getTime() ?? new Date(data.lastEventAt).getTime()) -
            new Date(data.lastEventAt).getTime()) /
            60_000,
        ),
      )
    : null;
  const telemetryStale =
    lastEventAgeMinutes === null || lastEventAgeMinutes > 120;
  const systemStatus = data.eventsFailed
    ? { label: 'Cần xử lý', tone: 'destructive' as const, icon: AlertTriangle }
    : telemetryStale
      ? { label: 'Thiếu dữ liệu mới', tone: 'warning' as const, icon: Clock3 }
      : data.eventsPending
        ? { label: 'Đang xử lý', tone: 'warning' as const, icon: Clock3 }
        : {
            label: 'Hoạt động tốt',
            tone: 'success' as const,
            icon: CheckCircle2,
          };
  const alerts = [
    data.eventsFailed > 0
      ? `${numberFormat.format(data.eventsFailed)} sự kiện xử lý lỗi cần kiểm tra`
      : null,
    data.eventsPending > 0
      ? `${numberFormat.format(data.eventsPending)} sự kiện đang nằm trong hàng đợi`
      : null,
    telemetryStale
      ? data.lastEventAt
        ? `Chưa nhận sự kiện mới trong ${numberFormat.format(lastEventAgeMinutes ?? 0)} phút`
        : 'Chưa ghi nhận sự kiện hệ thống nào'
      : null,
    data.lockedUsers > 0
      ? `${numberFormat.format(data.lockedUsers)} tài khoản đang bị khoá`
      : null,
  ].filter((item): item is string => Boolean(item));

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-3 rounded-xl border border-border/70 bg-muted/25 p-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <p className="text-sm font-medium">Trung tâm điều hành</p>
          <p className="text-xs text-muted-foreground">
            {loadedAt && `Cập nhật lúc ${dateFormat.format(loadedAt)}`}
            {data.lastEventAt &&
              ` · sự kiện gần nhất ${formatDate(data.lastEventAt)}`}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex h-8 items-center gap-2 rounded-lg border bg-background px-2.5 text-xs">
            Khoảng thời gian
            <select
              value={period}
              onChange={(event) => setPeriod(Number(event.target.value))}
              className="bg-transparent font-medium outline-none"
              aria-label="Khoảng thời gian thống kê"
            >
              <option value={7}>7 ngày</option>
              <option value={14}>14 ngày</option>
              <option value={30}>30 ngày</option>
            </select>
          </label>
          <div className="flex h-8 items-center gap-2 rounded-lg border bg-background px-2.5 text-xs">
            <Switch
              id="admin-auto-refresh"
              size="sm"
              checked={autoRefresh}
              onCheckedChange={(checked) => setAutoRefresh(Boolean(checked))}
              aria-label="Tự động làm mới mỗi 30 giây"
            />
            <label htmlFor="admin-auto-refresh">Tự làm mới</label>
          </div>
          <Button
            size="sm"
            variant="outline"
            onClick={() => downloadOverviewReport(data, loadedAt ?? new Date())}
          >
            <Download />
            Xuất CSV
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={loading}
            onClick={() => void load()}
          >
            <RefreshCw className={cn(loading && 'animate-spin')} />
            Tải lại
          </Button>
        </div>
      </div>
      <ErrorLine message={error} />

      <div className="grid gap-3 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1.9fr)]">
        <section
          className={cn(
            'rounded-xl border p-4',
            systemStatus.tone === 'destructive' &&
              'border-destructive/30 bg-destructive/[0.04]',
            systemStatus.tone === 'warning' &&
              'border-amber-500/30 bg-amber-500/[0.05]',
            systemStatus.tone === 'success' &&
              'border-emerald-500/30 bg-emerald-500/[0.05]',
          )}
        >
          <div className="flex items-start gap-3">
            <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-background shadow-sm ring-1 ring-border/70">
              <systemStatus.icon
                className={cn(
                  'size-5',
                  systemStatus.tone === 'destructive' && 'text-destructive',
                  systemStatus.tone === 'warning' &&
                    'text-amber-600 dark:text-amber-400',
                  systemStatus.tone === 'success' &&
                    'text-emerald-600 dark:text-emerald-400',
                )}
              />
            </span>
            <div className="min-w-0">
              <p className="text-xs font-medium text-muted-foreground">
                Trạng thái hệ thống
              </p>
              <p className="text-lg font-semibold">{systemStatus.label}</p>
              <p className="mt-1 text-xs text-muted-foreground">
                {alerts.length > 0
                  ? `${alerts.length} mục cần chú ý`
                  : 'Không phát hiện vấn đề vận hành trong dữ liệu hiện tại.'}
              </p>
            </div>
          </div>
        </section>

        <section className="rounded-xl border border-border/70 bg-card p-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-xs font-medium text-muted-foreground">
                Chất lượng dữ liệu POI
              </p>
              <p className="text-lg font-semibold">
                {formatShare(coverageScore)} hoàn thiện trung bình
              </p>
            </div>
            <span className="text-2xl font-semibold text-emerald-600 tabular-nums dark:text-emerald-400">
              {numberFormat.format(data.pois)}
            </span>
          </div>
          <Meter share={coverageScore} />
          <p className="mt-2 text-xs text-muted-foreground">
            Tính trên đánh giá, liên hệ, giờ mở cửa, ảnh, bài giới thiệu và
            video.
          </p>
        </section>
      </div>

      {alerts.length > 0 && (
        <section className="rounded-xl border border-amber-500/25 bg-amber-500/[0.04] p-3">
          <div className="flex items-center gap-2 text-sm font-medium">
            <AlertTriangle className="size-4 text-amber-600 dark:text-amber-400" />
            Cần chú ý
          </div>
          <ul className="mt-2 grid gap-1 text-xs text-muted-foreground md:grid-cols-2">
            {alerts.map((alert) => (
              <li key={alert} className="flex gap-2">
                <span aria-hidden>•</span>
                <span>{alert}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        {tiles.map((tile) => (
          <div
            key={tile.label}
            className="group rounded-xl border border-border/70 bg-card p-3 transition-colors hover:border-emerald-500/35 hover:bg-emerald-500/[0.025] sm:p-4"
          >
            <div className="flex items-center justify-between gap-2">
              <p className="text-xs font-medium text-muted-foreground">
                {tile.label}
              </p>
              <tile.icon className={cn('size-4', tile.accent)} />
            </div>
            <p className="mt-1 text-2xl font-semibold tracking-tight tabular-nums sm:text-3xl">
              {numberFormat.format(tile.value)}
            </p>
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
              {tile.hint}
            </p>
          </div>
        ))}
      </div>

      <section className="rounded-xl border border-border/70 bg-card p-3 sm:p-4">
        <div className="mb-3 flex items-center gap-2">
          <BarChart3 className="size-4 text-emerald-600 dark:text-emerald-400" />
          <h3 className="text-sm font-medium">Thao tác nhanh</h3>
        </div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          <QuickAction
            icon={Users}
            title="Quản lý người dùng"
            description="Phân quyền, khoá và đặt lại mật khẩu"
            onClick={() => onNavigate('users')}
          />
          <QuickAction
            icon={MessageSquare}
            title="Kiểm duyệt đánh giá"
            description={`${numberFormat.format(data.reviewsPeriod)} đánh giá mới trong kỳ`}
            onClick={() => onNavigate('reviews')}
          />
          <QuickAction
            icon={MapPin}
            title="Quản lý địa danh"
            description="Thêm, sửa hoặc gỡ bài giới thiệu"
            onClick={() => onNavigate('landmarks')}
          />
        </div>
      </section>

      <Section
        title={`Hoạt động ${data.dailyActivity.length} ngày qua`}
        hint="Số sự kiện mỗi ngày (giờ Việt Nam) — rê chuột hoặc chạm vào cột để xem chi tiết"
      >
        <ActivityChart days={data.dailyActivity} />
      </Section>

      <div className="grid gap-4 md:grid-cols-2">
        <Section
          title={`Loại sự kiện (${period} ngày)`}
          hint={`${numberFormat.format(eventTotal)} sự kiện`}
        >
          {data.eventTypesPeriod.length === 0 ? (
            <EmptyLine />
          ) : (
            <BarList
              items={data.eventTypesPeriod.map((item) => ({
                label: EVENT_LABELS[item.type] ?? item.type,
                value: item.count,
              }))}
              total={eventTotal}
            />
          )}
          <div className="mt-3 flex flex-wrap gap-2 text-xs">
            <Badge variant={data.eventsPending > 0 ? 'secondary' : 'outline'}>
              {numberFormat.format(data.eventsPending)} đang chờ xử lý
            </Badge>
            <Badge variant={data.eventsFailed > 0 ? 'destructive' : 'outline'}>
              {numberFormat.format(data.eventsFailed)} xử lý lỗi
            </Badge>
          </div>
        </Section>

        <Section
          title="Địa điểm theo danh mục"
          hint={`${numberFormat.format(data.pois)} POI`}
        >
          <BarList
            items={data.poiCategories.map((item) => ({
              label: item.label,
              value: item.count,
            }))}
            total={data.pois}
          />
        </Section>
      </div>

      <Section
        title={`Địa điểm được quan tâm nhất (${period} ngày)`}
        hint="Xếp theo tổng lượt mở chi tiết, chỉ đường và xem lâu"
      >
        {data.topPoisPeriod.length === 0 ? (
          <EmptyLine />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="py-2 pr-2 font-normal">#</th>
                  <th className="py-2 pr-2 font-normal">Địa điểm</th>
                  <th className="py-2 pr-2 text-right font-normal">
                    Mở chi tiết
                  </th>
                  <th className="py-2 pr-2 text-right font-normal">
                    Chỉ đường
                  </th>
                  <th className="py-2 text-right font-normal">Xem lâu</th>
                </tr>
              </thead>
              <tbody>
                {data.topPoisPeriod.map((poi, index) => (
                  <tr key={poi.id} className="border-b last:border-0">
                    <td className="py-2 pr-2 text-muted-foreground tabular-nums">
                      {index + 1}
                    </td>
                    <td className="py-2 pr-2">
                      <span className="font-medium">{poi.name}</span>
                      <span className="ml-2 text-xs text-muted-foreground">
                        {poi.category}
                      </span>
                    </td>
                    <td className="py-2 pr-2 text-right tabular-nums">
                      {poi.clicks}
                    </td>
                    <td className="py-2 pr-2 text-right tabular-nums">
                      {poi.navigations}
                    </td>
                    <td className="py-2 text-right tabular-nums">
                      {poi.dwells}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <div className="grid gap-4 md:grid-cols-2">
        <Section
          title="Độ đầy đủ dữ liệu POI"
          hint="Tỉ lệ địa điểm có từng loại thông tin"
        >
          <ul className="flex flex-col gap-2.5">
            {coverage.map((item) => {
              const share = data.pois ? item.value / data.pois : 0;
              return (
                <li key={item.label}>
                  <div className="flex justify-between gap-2 text-xs">
                    <span>{item.label}</span>
                    <span className="text-muted-foreground tabular-nums">
                      {numberFormat.format(item.value)} · {formatShare(share)}
                    </span>
                  </div>
                  <Meter share={share} />
                </li>
              );
            })}
          </ul>
        </Section>

        <div className="flex flex-col gap-4">
          <Section
            title="Phân bố điểm đánh giá"
            hint={
              data.averageRating !== null
                ? `Trung bình ${data.averageRating.toFixed(2)}★ trên ${ratingTotal} đánh giá`
                : 'Chưa có đánh giá của người dùng'
            }
          >
            <BarList
              items={data.ratingDistribution.map((item) => ({
                label: `${item.rating}★`,
                value: item.count,
              }))}
              total={ratingTotal}
              compact
            />
          </Section>

          <Section title="Tài khoản mới nhất">
            {data.recentUsers.length === 0 ? (
              <EmptyLine />
            ) : (
              <ul className="flex flex-col divide-y">
                {data.recentUsers.map((user) => (
                  <li
                    key={user.id}
                    className="flex items-center gap-2 py-2 first:pt-0 last:pb-0"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">
                        {user.displayName || user.username}
                        <span className="ml-1.5 text-xs font-normal text-muted-foreground">
                          @{user.username}
                        </span>
                      </p>
                      <p className="text-xs text-muted-foreground">
                        tạo {formatDate(user.createdAt)} · đăng nhập{' '}
                        {formatDate(user.lastLoginAt)}
                      </p>
                    </div>
                    {user.role === 'admin' && <Badge>Admin</Badge>}
                    {!user.isActive && (
                      <Badge variant="destructive">Đã khoá</Badge>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Section>
        </div>
      </div>
    </div>
  );
}

const percentFormat = new Intl.NumberFormat('vi-VN', {
  style: 'percent',
  maximumFractionDigits: 1,
});
const dayFormat = new Intl.DateTimeFormat('vi-VN', {
  day: '2-digit',
  month: '2-digit',
});
const weekdayFormat = new Intl.DateTimeFormat('vi-VN', {
  weekday: 'long',
  day: '2-digit',
  month: '2-digit',
});

function formatShare(share: number) {
  // Tỉ lệ rất nhỏ nhưng khác 0 vẫn phải thấy được, không làm tròn thành "0%".
  return share > 0 && share < 0.001 ? '<0,1%' : percentFormat.format(share);
}

/** Ngày "YYYY-MM-DD" từ backend là ngày theo lịch, không phải thời điểm —
 * dựng bằng giờ địa phương để không bị lùi một ngày ở múi giờ âm. */
function parseDay(value: string) {
  const [year, month, day] = value.split('-').map(Number);
  return new Date(year, month - 1, day);
}

function csvCell(value: string | number) {
  return `"${String(value).replaceAll('"', '""')}"`;
}

function downloadOverviewReport(data: Overview, loadedAt: Date) {
  const rows: (string | number)[][] = [
    ['Báo cáo dashboard quản trị'],
    ['Thời điểm xuất', dateFormat.format(loadedAt)],
    ['Khoảng thời gian', `${data.periodDays} ngày`],
    [],
    ['CHỈ SỐ TỔNG QUAN', 'Giá trị'],
    ['Tài khoản', data.users],
    [`Tài khoản mới / ${data.periodDays} ngày`, data.newUsersPeriod],
    [`Người dùng hoạt động / ${data.periodDays} ngày`, data.activeUsersPeriod],
    ['Quản trị viên', data.admins],
    ['Tài khoản bị khoá', data.lockedUsers],
    ['Địa điểm POI', data.pois],
    ['Đánh giá', data.reviews],
    [`Đánh giá mới / ${data.periodDays} ngày`, data.reviewsPeriod],
    ['Địa điểm đã lưu', data.savedPlaces],
    ['Sự kiện / 24 giờ', data.events24h],
    [`Phiên / ${data.periodDays} ngày`, data.sessionsPeriod],
    ['Sự kiện đang chờ', data.eventsPending],
    ['Sự kiện lỗi', data.eventsFailed],
    [],
    ['HOẠT ĐỘNG THEO NGÀY', 'Sự kiện', 'Phiên', 'Tìm kiếm', 'Chỉ đường'],
    ...data.dailyActivity.map((day) => [
      day.date,
      day.events,
      day.sessions,
      day.searches,
      day.navigations,
    ]),
    [],
    ['LOẠI SỰ KIỆN', 'Số lượng'],
    ...data.eventTypesPeriod.map((item) => [
      EVENT_LABELS[item.type] ?? item.type,
      item.count,
    ]),
    [],
    ['POI ĐƯỢC QUAN TÂM', 'Danh mục', 'Mở chi tiết', 'Chỉ đường', 'Xem lâu'],
    ...data.topPoisPeriod.map((poi) => [
      poi.name,
      poi.category,
      poi.clicks,
      poi.navigations,
      poi.dwells,
    ]),
  ];
  const csv = `\uFEFF${rows.map((row) => row.map(csvCell).join(',')).join('\r\n')}`;
  const url = URL.createObjectURL(
    new Blob([csv], { type: 'text/csv;charset=utf-8' }),
  );
  const link = document.createElement('a');
  link.href = url;
  link.download = `nearby-dashboard-${new Date().toISOString().slice(0, 10)}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

function QuickAction({
  icon: Icon,
  title,
  description,
  onClick,
}: {
  icon: typeof Users;
  title: string;
  description: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="group flex items-center gap-3 rounded-xl border border-border/70 bg-muted/20 p-3 text-left transition-colors hover:border-emerald-500/35 hover:bg-emerald-500/[0.05] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-background text-emerald-600 shadow-sm ring-1 ring-border/70 dark:text-emerald-400">
        <Icon className="size-4" />
      </span>
      <span className="min-w-0">
        <span className="block text-sm font-medium">{title}</span>
        <span className="block truncate text-xs text-muted-foreground">
          {description}
        </span>
      </span>
    </button>
  );
}

function Section({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-xl border border-border/70 bg-card p-3 sm:p-4">
      <header className="mb-3">
        <h3 className="text-sm font-medium">{title}</h3>
        {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      </header>
      {children}
    </section>
  );
}

function EmptyLine() {
  return (
    <p className="py-3 text-center text-sm text-muted-foreground">
      Chưa có dữ liệu.
    </p>
  );
}

function Meter({ share }: { share: number }) {
  return (
    <div className="mt-1 h-2 overflow-hidden rounded-full bg-muted">
      <div
        className="h-full rounded-full bg-emerald-600 dark:bg-emerald-500"
        // Giữ một vạch tối thiểu cho giá trị khác 0 để không lẫn với "không có".
        style={{ width: share > 0 ? `max(${share * 100}%, 3px)` : 0 }}
      />
    </div>
  );
}

function BarList({
  items,
  total,
  compact = false,
}: {
  items: { label: string; value: number }[];
  total: number;
  compact?: boolean;
}) {
  const max = Math.max(1, ...items.map((item) => item.value));
  return (
    <ul className={cn('flex flex-col', compact ? 'gap-1.5' : 'gap-2')}>
      {items.map((item) => (
        <li
          key={item.label}
          className={cn(
            'grid items-center gap-2 text-xs',
            compact
              ? 'grid-cols-[2rem_minmax(0,1fr)_auto]'
              : 'grid-cols-[minmax(0,7rem)_minmax(0,1fr)_auto] sm:grid-cols-[minmax(0,9rem)_minmax(0,1fr)_auto]',
          )}
        >
          <span className="truncate" title={item.label}>
            {item.label}
          </span>
          <div className="h-2 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-emerald-600 dark:bg-emerald-500"
              style={{
                width:
                  item.value > 0 ? `max(${(item.value / max) * 100}%, 3px)` : 0,
              }}
            />
          </div>
          <span className="text-right text-muted-foreground tabular-nums">
            {numberFormat.format(item.value)}
            {total > 0 && ` · ${formatShare(item.value / total)}`}
          </span>
        </li>
      ))}
    </ul>
  );
}

type ActivityMetric = 'events' | 'sessions' | 'searches' | 'navigations';

const ACTIVITY_METRICS: { key: ActivityMetric; label: string; unit: string }[] =
  [
    { key: 'events', label: 'Sự kiện', unit: 'sự kiện' },
    { key: 'sessions', label: 'Phiên', unit: 'phiên' },
    { key: 'searches', label: 'Tìm kiếm', unit: 'lượt tìm kiếm' },
    { key: 'navigations', label: 'Chỉ đường', unit: 'lượt chỉ đường' },
  ];

function ActivityChart({ days }: { days: DailyActivity[] }) {
  const [active, setActive] = useState<number | null>(null);
  const [metric, setMetric] = useState<ActivityMetric>('events');
  const metricInfo =
    ACTIVITY_METRICS.find((item) => item.key === metric) ?? ACTIVITY_METRICS[0];
  const max = Math.max(1, ...days.map((day) => day[metric]));
  const total = days.reduce((sum, day) => sum + day[metric], 0);
  const shown = active === null ? null : days[active];

  return (
    <div>
      <fieldset className="mb-3 flex flex-wrap gap-1 rounded-lg bg-muted/60 p-1">
        <legend className="sr-only">Chỉ số biểu đồ</legend>
        {ACTIVITY_METRICS.map((item) => (
          <button
            key={item.key}
            type="button"
            aria-pressed={metric === item.key}
            onClick={() => setMetric(item.key)}
            className={cn(
              'rounded-md px-2.5 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
              metric === item.key
                ? 'bg-background text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {item.label}
          </button>
        ))}
      </fieldset>
      <div className="mb-2 min-h-10 text-xs">
        {shown ? (
          <>
            <p className="font-medium capitalize">
              {weekdayFormat.format(parseDay(shown.date))}
            </p>
            <p className="text-muted-foreground tabular-nums">
              {numberFormat.format(shown.events)} sự kiện · {shown.sessions}{' '}
              phiên · {shown.searches} tìm kiếm · {shown.navigations} chỉ đường
            </p>
          </>
        ) : (
          <>
            <p className="font-medium tabular-nums">
              {numberFormat.format(total)} {metricInfo.unit}
            </p>
            <p className="text-muted-foreground">
              trung bình{' '}
              {numberFormat.format(
                Math.round(total / Math.max(1, days.length)),
              )}{' '}
              / ngày
            </p>
          </>
        )}
      </div>
      <div
        className="relative flex h-36 items-end gap-0.5 border-b"
        onMouseLeave={() => setActive(null)}
      >
        {/* Vạch lưới mờ ở mức cao nhất để đọc được thang đo. */}
        <span className="pointer-events-none absolute inset-x-0 top-0 border-t border-dashed border-border" />
        <span className="pointer-events-none absolute top-0 right-0 -translate-y-full pb-0.5 text-[10px] text-muted-foreground tabular-nums">
          {numberFormat.format(max)}
        </span>
        {days.map((day, index) => (
          <button
            key={day.date}
            type="button"
            className="admin-chart-bar group flex h-full min-w-0 flex-1 items-end focus-visible:outline-none"
            onMouseEnter={() => setActive(index)}
            onFocus={() => setActive(index)}
            onBlur={() => setActive(null)}
            aria-label={`${weekdayFormat.format(parseDay(day.date))}: ${day[metric]} ${metricInfo.unit}`}
          >
            <span
              className={cn(
                'w-full rounded-t-[4px] bg-emerald-600 transition-colors dark:bg-emerald-500',
                active !== null &&
                  active !== index &&
                  'bg-emerald-600/40 dark:bg-emerald-500/40',
                'group-focus-visible:ring-2 group-focus-visible:ring-ring',
              )}
              style={{
                height:
                  day[metric] > 0
                    ? `max(${(day[metric] / max) * 100}%, 2px)`
                    : 0,
              }}
            />
          </button>
        ))}
      </div>
      <div className="mt-1 flex gap-0.5 text-[10px] text-muted-foreground tabular-nums">
        {days.map((day, index) => (
          <span key={day.date} className="relative h-3 min-w-0 flex-1">
            {/* Nhãn nằm tuyệt đối giữa cột để không đẩy cột rộng ra trên màn
                hẹp; ở đó chỉ hiện cách ngày cho khỏi chồng lên nhau. */}
            <span
              className={cn(
                'absolute left-1/2 -translate-x-1/2 whitespace-nowrap',
                index % 2 === 1 && 'max-sm:invisible',
              )}
            >
              {dayFormat.format(parseDay(day.date))}
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}

function UsersTab({
  apiBaseUrl,
  currentUserId,
}: {
  apiBaseUrl: string;
  currentUserId: string;
}) {
  const [query, setQuery] = useState('');
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);

  const load = useCallback(
    async (search: string) => {
      setError(null);
      try {
        const params = new URLSearchParams({ limit: '100' });
        if (search.trim()) params.set('q', search.trim());
        const result = await apiRequest<{ users: AdminUser[]; total: number }>(
          apiBaseUrl,
          `/api/v1/admin/users?${params}`,
        );
        setUsers(result.users);
        setTotal(result.total);
      } catch (caught) {
        setError(
          caught instanceof Error ? caught.message : 'Không tải được danh sách',
        );
      }
    },
    [apiBaseUrl],
  );

  useEffect(() => {
    // Fetch rồi setState — cùng mẫu với reloadSavedPlaces ở location-explorer.
    // oxlint-disable-next-line react/react-compiler
    void load('');
  }, [load]);

  async function update(
    user: AdminUser,
    change: Record<string, unknown>,
    message: string,
  ) {
    setPendingId(user.id);
    setError(null);
    setNotice(null);
    try {
      const result = await apiRequest<{ user: AdminUser }>(
        apiBaseUrl,
        `/api/v1/admin/users/${user.id}`,
        { method: 'PATCH', body: JSON.stringify(change) },
      );
      setUsers(
        (current) =>
          current?.map((item) => (item.id === user.id ? result.user : item)) ??
          null,
      );
      setNotice(message);
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : 'Không cập nhật được',
      );
    } finally {
      setPendingId(null);
    }
  }

  function resetPassword(user: AdminUser) {
    const password = window.prompt(
      `Mật khẩu mới cho @${user.username} (ít nhất 8 ký tự):`,
    );
    if (!password) return;
    if (password.length < 8) {
      setError('Mật khẩu cần ít nhất 8 ký tự');
      return;
    }
    void update(
      user,
      { password },
      `Đã đặt lại mật khẩu cho @${user.username}`,
    );
  }

  function onSearch(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    void load(query);
  }

  return (
    <div className="flex flex-col gap-3">
      <form className="flex gap-2" onSubmit={onSearch}>
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Tìm theo tên đăng nhập hoặc tên hiển thị"
            className="pl-8"
            aria-label="Tìm tài khoản"
          />
        </div>
        <Button type="submit" variant="outline">
          Tìm
        </Button>
      </form>
      <ErrorLine message={error} />
      {notice && (
        <p className="rounded-md bg-emerald-500/10 px-3 py-2 text-sm text-emerald-700 dark:text-emerald-400">
          {notice}
        </p>
      )}
      {users === null ? (
        !error && (
          <LoaderCircle className="mx-auto my-8 size-6 animate-spin text-muted-foreground" />
        )
      ) : users.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">
          Không có tài khoản nào.
        </p>
      ) : (
        <>
          <p className="text-xs text-muted-foreground">
            Hiển thị {numberFormat.format(users.length)} /{' '}
            {numberFormat.format(total)} tài khoản
          </p>
          <ul className="flex flex-col gap-2">
            {users.map((user) => {
              const isSelf = user.id === currentUserId;
              const busy = pendingId === user.id;
              const isAdmin = user.role === 'admin';
              return (
                <li
                  key={user.id}
                  className={cn(
                    'flex flex-col gap-3 rounded-xl border border-border/70 bg-card p-3 transition-colors hover:border-emerald-500/30 sm:flex-row sm:items-center sm:p-4',
                    !user.isActive && 'opacity-70',
                  )}
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="truncate font-medium">
                        {user.displayName || user.username}
                      </span>
                      <Badge variant={isAdmin ? 'default' : 'secondary'}>
                        {isAdmin ? 'Quản trị viên' : 'Người dùng'}
                      </Badge>
                      {!user.isActive && (
                        <Badge variant="destructive">Đã khoá</Badge>
                      )}
                      {isSelf && <Badge variant="outline">Bạn</Badge>}
                    </div>
                    <p className="mt-0.5 truncate text-xs text-muted-foreground">
                      @{user.username} · tạo {formatDate(user.createdAt)} · đăng
                      nhập {formatDate(user.lastLoginAt)} · {user.savedCount} đã
                      lưu · {user.reviewCount} đánh giá
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {busy && (
                      <LoaderCircle className="size-4 animate-spin self-center" />
                    )}
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busy || isSelf}
                      title={
                        isSelf
                          ? 'Không thể tự đổi quyền của chính mình'
                          : undefined
                      }
                      onClick={() =>
                        void update(
                          user,
                          { role: isAdmin ? 'user' : 'admin' },
                          isAdmin
                            ? `Đã hạ @${user.username} xuống Người dùng`
                            : `Đã nâng @${user.username} lên Quản trị viên`,
                        )
                      }
                    >
                      {isAdmin ? <ShieldMinus /> : <ShieldCheck />}
                      {isAdmin ? 'Hạ quyền' : 'Cấp admin'}
                    </Button>
                    <Button
                      size="sm"
                      variant={user.isActive ? 'destructive' : 'outline'}
                      disabled={busy || isSelf}
                      onClick={() =>
                        void update(
                          user,
                          { is_active: !user.isActive },
                          user.isActive
                            ? `Đã khoá @${user.username}`
                            : `Đã mở khoá @${user.username}`,
                        )
                      }
                    >
                      {user.isActive ? <Lock /> : <LockOpen />}
                      {user.isActive ? 'Khoá' : 'Mở khoá'}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={busy}
                      onClick={() => resetPassword(user)}
                    >
                      <KeyRound />
                      Đặt lại mật khẩu
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </div>
  );
}

function ReviewsTab({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [reviews, setReviews] = useState<AdminReview[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const result = await apiRequest<{
        reviews: AdminReview[];
        total: number;
      }>(apiBaseUrl, '/api/v1/admin/reviews?limit=100');
      setReviews(result.reviews);
      setTotal(result.total);
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : 'Không tải được đánh giá',
      );
    }
  }, [apiBaseUrl]);

  useEffect(() => {
    // oxlint-disable-next-line react/react-compiler
    void load();
  }, [load]);

  async function remove(review: AdminReview) {
    if (
      !window.confirm(
        `Gỡ đánh giá ${review.rating}★ về "${review.poiName}"? Điểm của địa điểm sẽ được tính lại.`,
      )
    ) {
      return;
    }
    setPendingId(review.id);
    setError(null);
    try {
      await apiRequest(apiBaseUrl, `/api/v1/admin/reviews/${review.id}`, {
        method: 'DELETE',
      });
      setReviews(
        (current) => current?.filter((item) => item.id !== review.id) ?? null,
      );
      setTotal((value) => Math.max(0, value - 1));
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : 'Không gỡ được đánh giá',
      );
    } finally {
      setPendingId(null);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          {numberFormat.format(total)} đánh giá của người dùng, mới nhất trước
        </p>
        <Button size="sm" variant="ghost" onClick={() => void load()}>
          <RefreshCw />
          Tải lại
        </Button>
      </div>
      <ErrorLine message={error} />
      {reviews === null ? (
        !error && (
          <LoaderCircle className="mx-auto my-8 size-6 animate-spin text-muted-foreground" />
        )
      ) : reviews.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">
          Chưa có đánh giá nào.
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {reviews.map((review) => (
            <li
              key={review.id}
              className="flex gap-3 rounded-xl border bg-card p-3"
            >
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{review.poiName}</span>
                  <span className="flex items-center gap-0.5 text-sm text-amber-600">
                    {review.rating}
                    <Star className="size-3.5 fill-current" />
                  </span>
                </div>
                <p className="text-xs text-muted-foreground">
                  {review.authorName || 'Ẩn danh'}
                  {review.username
                    ? ` (@${review.username})`
                    : ' · khách chưa đăng nhập'}{' '}
                  · {formatDate(review.updatedAt)}
                </p>
                {review.title && (
                  <p className="mt-1 text-sm font-medium">{review.title}</p>
                )}
                {review.body && (
                  <p className="mt-0.5 line-clamp-3 text-sm whitespace-pre-line text-muted-foreground">
                    {review.body}
                  </p>
                )}
              </div>
              <Button
                size="icon-sm"
                variant="destructive"
                disabled={pendingId === review.id}
                onClick={() => void remove(review)}
                aria-label="Gỡ đánh giá"
                title="Gỡ đánh giá"
              >
                {pendingId === review.id ? (
                  <LoaderCircle className="animate-spin" />
                ) : (
                  <Trash2 />
                )}
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

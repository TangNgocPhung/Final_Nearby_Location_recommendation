'use client';

import { type SyntheticEvent, useCallback, useEffect, useState } from 'react';
import {
  KeyRound,
  LoaderCircle,
  Lock,
  LockOpen,
  RefreshCw,
  Search,
  ShieldCheck,
  ShieldMinus,
  Star,
  Trash2,
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { apiRequest, type UserRole } from '@/lib/auth';
import { cn } from '@/lib/utils';

type Overview = {
  users: number;
  admins: number;
  lockedUsers: number;
  newUsers7d: number;
  pois: number;
  reviews: number;
  reviews7d: number;
  savedPlaces: number;
  events24h: number;
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
    <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
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
      <DialogContent className="flex max-h-[90vh] flex-col gap-4 overflow-hidden sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ShieldCheck className="size-5 text-emerald-600" />
            Trang quản trị
          </DialogTitle>
          <DialogDescription>
            Quản lý tài khoản, phân quyền và kiểm duyệt đánh giá của người dùng.
          </DialogDescription>
        </DialogHeader>
        <Tabs
          value={tab}
          onValueChange={(value) => setTab(String(value))}
          className="min-h-0 flex-1 gap-3"
        >
          <TabsList className="w-full sm:w-fit">
            <TabsTrigger value="overview">Tổng quan</TabsTrigger>
            <TabsTrigger value="users">Người dùng</TabsTrigger>
            <TabsTrigger value="reviews">Đánh giá</TabsTrigger>
          </TabsList>
          <div className="min-h-0 flex-1 overflow-y-auto pr-1">
            {open && (
              <>
                <TabsContent value="overview">
                  <OverviewTab apiBaseUrl={apiBaseUrl} />
                </TabsContent>
                <TabsContent value="users">
                  <UsersTab apiBaseUrl={apiBaseUrl} currentUserId={currentUserId} />
                </TabsContent>
                <TabsContent value="reviews">
                  <ReviewsTab apiBaseUrl={apiBaseUrl} />
                </TabsContent>
              </>
            )}
          </div>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}

function OverviewTab({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiRequest<Overview>(apiBaseUrl, '/api/v1/admin/overview')
      .then(setData)
      .catch((caught: Error) => setError(caught.message));
  }, [apiBaseUrl]);

  if (error) return <ErrorLine message={error} />;
  if (!data) return <LoaderCircle className="mx-auto my-8 size-6 animate-spin text-muted-foreground" />;

  const tiles = [
    { label: 'Tài khoản', value: data.users, hint: `+${data.newUsers7d} trong 7 ngày` },
    { label: 'Quản trị viên', value: data.admins, hint: `${data.lockedUsers} tài khoản bị khoá` },
    { label: 'Đánh giá', value: data.reviews, hint: `+${data.reviews7d} trong 7 ngày` },
    { label: 'Địa điểm đã lưu', value: data.savedPlaces, hint: 'tổng mọi người dùng' },
    { label: 'Địa điểm (POI)', value: data.pois, hint: 'trong cơ sở dữ liệu' },
    { label: 'Sự kiện 24 giờ', value: data.events24h, hint: 'tìm kiếm, click, chỉ đường…' },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
      {tiles.map((tile) => (
        <div key={tile.label} className="rounded-xl border bg-card p-4">
          <p className="text-xs text-muted-foreground">{tile.label}</p>
          <p className="mt-1 text-2xl font-semibold tabular-nums">
            {numberFormat.format(tile.value)}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">{tile.hint}</p>
        </div>
      ))}
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
        setError(caught instanceof Error ? caught.message : 'Không tải được danh sách');
      }
    },
    [apiBaseUrl],
  );

  useEffect(() => {
    // Fetch rồi setState — cùng mẫu với reloadSavedPlaces ở location-explorer.
    // oxlint-disable-next-line react/react-compiler
    void load('');
  }, [load]);

  async function update(user: AdminUser, change: Record<string, unknown>, message: string) {
    setPendingId(user.id);
    setError(null);
    setNotice(null);
    try {
      const result = await apiRequest<{ user: AdminUser }>(
        apiBaseUrl,
        `/api/v1/admin/users/${user.id}`,
        { method: 'PATCH', body: JSON.stringify(change) },
      );
      setUsers((current) =>
        current?.map((item) => (item.id === user.id ? result.user : item)) ?? null,
      );
      setNotice(message);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Không cập nhật được');
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
    void update(user, { password }, `Đã đặt lại mật khẩu cho @${user.username}`);
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
        !error && <LoaderCircle className="mx-auto my-8 size-6 animate-spin text-muted-foreground" />
      ) : users.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Không có tài khoản nào.</p>
      ) : (
        <>
          <p className="text-xs text-muted-foreground">{numberFormat.format(total)} tài khoản</p>
          <ul className="flex flex-col gap-2">
            {users.map((user) => {
              const isSelf = user.id === currentUserId;
              const busy = pendingId === user.id;
              const isAdmin = user.role === 'admin';
              return (
                <li
                  key={user.id}
                  className={cn(
                    'flex flex-col gap-3 rounded-xl border bg-card p-3 sm:flex-row sm:items-center',
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
                      {!user.isActive && <Badge variant="destructive">Đã khoá</Badge>}
                      {isSelf && <Badge variant="outline">Bạn</Badge>}
                    </div>
                    <p className="mt-0.5 truncate text-xs text-muted-foreground">
                      @{user.username} · tạo {formatDate(user.createdAt)} · đăng nhập{' '}
                      {formatDate(user.lastLoginAt)} · {user.savedCount} đã lưu ·{' '}
                      {user.reviewCount} đánh giá
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {busy && <LoaderCircle className="size-4 animate-spin self-center" />}
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busy || isSelf}
                      title={isSelf ? 'Không thể tự đổi quyền của chính mình' : undefined}
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
      const result = await apiRequest<{ reviews: AdminReview[]; total: number }>(
        apiBaseUrl,
        '/api/v1/admin/reviews?limit=100',
      );
      setReviews(result.reviews);
      setTotal(result.total);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Không tải được đánh giá');
    }
  }, [apiBaseUrl]);

  useEffect(() => {
    // oxlint-disable-next-line react/react-compiler
    void load();
  }, [load]);

  async function remove(review: AdminReview) {
    if (!window.confirm(`Gỡ đánh giá ${review.rating}★ về "${review.poiName}"? Điểm của địa điểm sẽ được tính lại.`)) {
      return;
    }
    setPendingId(review.id);
    setError(null);
    try {
      await apiRequest(apiBaseUrl, `/api/v1/admin/reviews/${review.id}`, {
        method: 'DELETE',
      });
      setReviews((current) => current?.filter((item) => item.id !== review.id) ?? null);
      setTotal((value) => Math.max(0, value - 1));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Không gỡ được đánh giá');
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
        !error && <LoaderCircle className="mx-auto my-8 size-6 animate-spin text-muted-foreground" />
      ) : reviews.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Chưa có đánh giá nào.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {reviews.map((review) => (
            <li key={review.id} className="flex gap-3 rounded-xl border bg-card p-3">
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
                  {review.username ? ` (@${review.username})` : ' · khách chưa đăng nhập'} ·{' '}
                  {formatDate(review.updatedAt)}
                </p>
                {review.title && <p className="mt-1 text-sm font-medium">{review.title}</p>}
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

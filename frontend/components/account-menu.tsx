'use client';

import { type SyntheticEvent, useEffect, useState } from 'react';
import {
  KeyRound,
  LoaderCircle,
  LogIn,
  LogOut,
  ShieldCheck,
  UserRound,
} from 'lucide-react';

import { AdminPanel } from '@/components/admin-panel';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import {
  apiRequest,
  type AuthUser,
  clearAuth,
  setAuth,
  useAuth,
  verifyStoredAuth,
} from '@/lib/auth';
import { cn } from '@/lib/utils';

export const ROLE_LABELS = { admin: 'Quản trị viên', user: 'Người dùng' } as const;

type AuthResponse = { token: string; user: AuthUser };

/** Nút tài khoản trên header: chưa đăng nhập thì mở hộp đăng nhập; đã đăng
 * nhập thì mở menu (đổi mật khẩu, trang quản trị nếu là admin, đăng xuất). */
export function AccountMenu({
  apiBaseUrl,
  sessionId,
  compact = false,
}: {
  apiBaseUrl: string;
  sessionId?: string;
  compact?: boolean;
}) {
  const { user } = useAuth();
  const [authOpen, setAuthOpen] = useState(false);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [adminOpen, setAdminOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    void verifyStoredAuth(apiBaseUrl);
  }, [apiBaseUrl]);

  if (!user) {
    return (
      <>
        <Button
          variant={compact ? 'ghost' : 'outline'}
          size={compact ? 'icon' : 'sm'}
          className={cn('rounded-full', !compact && 'h-9 px-3.5 text-[13px]')}
          onClick={() => setAuthOpen(true)}
          aria-label="Đăng nhập"
          title="Đăng nhập"
        >
          <LogIn data-icon="inline-start" className={cn(compact && 'size-5')} />
          {!compact && 'Đăng nhập'}
        </Button>
        <AuthDialog
          open={authOpen}
          onOpenChange={setAuthOpen}
          apiBaseUrl={apiBaseUrl}
          sessionId={sessionId}
        />
      </>
    );
  }

  const name = user.displayName || user.username;
  const isAdmin = user.role === 'admin';

  return (
    <>
      <Popover open={menuOpen} onOpenChange={setMenuOpen}>
        <PopoverTrigger
          render={
            <Button
              variant={compact ? 'ghost' : 'outline'}
              size={compact ? 'icon' : 'sm'}
              className={cn('max-w-44 rounded-full', !compact && 'h-9 px-3.5 text-[13px]')}
              aria-label={`Tài khoản ${name}`}
              title={`${name} · ${ROLE_LABELS[user.role]}`}
            />
          }
        >
          {isAdmin ? (
            <ShieldCheck
              data-icon="inline-start"
              className={cn('text-emerald-600', compact && 'size-5')}
            />
          ) : (
            <UserRound data-icon="inline-start" className={cn(compact && 'size-5')} />
          )}
          {!compact && <span className="truncate">{name}</span>}
        </PopoverTrigger>
        <PopoverContent align="end" className="w-64 gap-1 p-2">
          <div className="px-2 pt-1 pb-2">
            <p className="truncate text-sm font-semibold">{name}</p>
            <p className="truncate text-xs text-muted-foreground">@{user.username}</p>
            <Badge
              variant={isAdmin ? 'default' : 'secondary'}
              className="mt-2"
            >
              {ROLE_LABELS[user.role]}
            </Badge>
          </div>
          {isAdmin && (
            <Button
              variant="ghost"
              className="h-10 justify-start gap-3 px-2 text-sm"
              onClick={() => {
                setMenuOpen(false);
                setAdminOpen(true);
              }}
            >
              <ShieldCheck className="size-4" />
              Trang quản trị
            </Button>
          )}
          <Button
            variant="ghost"
            className="h-10 justify-start gap-3 px-2 text-sm"
            onClick={() => {
              setMenuOpen(false);
              setPasswordOpen(true);
            }}
          >
            <KeyRound className="size-4" />
            Đổi mật khẩu
          </Button>
          <Button
            variant="ghost"
            className="h-10 justify-start gap-3 px-2 text-sm text-destructive hover:text-destructive"
            onClick={() => {
              setMenuOpen(false);
              clearAuth();
            }}
          >
            <LogOut className="size-4" />
            Đăng xuất
          </Button>
        </PopoverContent>
      </Popover>
      <ChangePasswordDialog
        open={passwordOpen}
        onOpenChange={setPasswordOpen}
        apiBaseUrl={apiBaseUrl}
      />
      {/* Bị hạ quyền / đăng xuất khi đang mở thì panel rời khỏi cây ngay. */}
      {isAdmin && (
        <AdminPanel
          open={adminOpen}
          onOpenChange={setAdminOpen}
          apiBaseUrl={apiBaseUrl}
          currentUserId={user.id}
        />
      )}
    </>
  );
}

function FormError({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
      {message}
    </p>
  );
}

function AuthDialog({
  open,
  onOpenChange,
  apiBaseUrl,
  sessionId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  apiBaseUrl: string;
  sessionId?: string;
}) {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [username, setUsername] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Đóng hộp thì xoá mật khẩu đã gõ — mở lại không được còn sẵn trong ô.
  function close() {
    setPassword('');
    setConfirm('');
    setError(null);
    onOpenChange(false);
  }

  async function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (mode === 'register' && password !== confirm) {
      setError('Hai lần nhập mật khẩu không khớp');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const body =
        mode === 'login'
          ? { username, password, session_id: sessionId || undefined }
          : {
              username,
              password,
              display_name: displayName || undefined,
              session_id: sessionId || undefined,
            };
      const result = await apiRequest<AuthResponse>(
        apiBaseUrl,
        `/api/v1/auth/${mode}`,
        { method: 'POST', body: JSON.stringify(body) },
      );
      setAuth(result.token, result.user);
      close();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Không kết nối được máy chủ');
    } finally {
      setBusy(false);
    }
  }

  const isLogin = mode === 'login';

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? onOpenChange(true) : close())}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>{isLogin ? 'Đăng nhập' : 'Tạo tài khoản'}</DialogTitle>
          <DialogDescription>
            {isLogin
              ? 'Đăng nhập để giữ địa điểm đã lưu và đánh giá trên mọi thiết bị.'
              : 'Tài khoản mới có vai trò Người dùng. Địa điểm bạn đã lưu trên trình duyệt này sẽ chuyển sang tài khoản.'}
          </DialogDescription>
        </DialogHeader>
        <form className="flex flex-col gap-3" onSubmit={submit}>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="auth-username">Tên đăng nhập</Label>
            <Input
              id="auth-username"
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              required
              minLength={isLogin ? 1 : 3}
              maxLength={32}
            />
          </div>
          {!isLogin && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="auth-display-name">Tên hiển thị (tuỳ chọn)</Label>
              <Input
                id="auth-display-name"
                autoComplete="nickname"
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                maxLength={80}
              />
            </div>
          )}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="auth-password">Mật khẩu</Label>
            <Input
              id="auth-password"
              type="password"
              autoComplete={isLogin ? 'current-password' : 'new-password'}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
              minLength={isLogin ? 1 : 8}
              maxLength={128}
            />
          </div>
          {!isLogin && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="auth-confirm">Nhập lại mật khẩu</Label>
              <Input
                id="auth-confirm"
                type="password"
                autoComplete="new-password"
                value={confirm}
                onChange={(event) => setConfirm(event.target.value)}
                required
                minLength={8}
                maxLength={128}
              />
            </div>
          )}
          <FormError message={error} />
          <DialogFooter className="flex-col gap-2 sm:flex-col">
            <Button type="submit" disabled={busy} className="w-full">
              {busy && <LoaderCircle className="size-4 animate-spin" />}
              {isLogin ? 'Đăng nhập' : 'Đăng ký'}
            </Button>
            <Button
              type="button"
              variant="link"
              className="w-full"
              onClick={() => {
                setMode(isLogin ? 'register' : 'login');
                setError(null);
              }}
            >
              {isLogin ? 'Chưa có tài khoản? Đăng ký' : 'Đã có tài khoản? Đăng nhập'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ChangePasswordDialog({
  open,
  onOpenChange,
  apiBaseUrl,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  apiBaseUrl: string;
}) {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  function close() {
    setCurrent('');
    setNext('');
    setError(null);
    setDone(false);
    onOpenChange(false);
  }

  async function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await apiRequest(apiBaseUrl, '/api/v1/auth/password', {
        method: 'POST',
        body: JSON.stringify({ current_password: current, new_password: next }),
      });
      setDone(true);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Không kết nối được máy chủ');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(value) => (value ? onOpenChange(true) : close())}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Đổi mật khẩu</DialogTitle>
        </DialogHeader>
        {done ? (
          <p className="text-sm text-emerald-700 dark:text-emerald-400">Đã đổi mật khẩu.</p>
        ) : (
          <form className="flex flex-col gap-3" onSubmit={submit}>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="pw-current">Mật khẩu hiện tại</Label>
              <Input
                id="pw-current"
                type="password"
                autoComplete="current-password"
                value={current}
                onChange={(event) => setCurrent(event.target.value)}
                required
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="pw-next">Mật khẩu mới (ít nhất 8 ký tự)</Label>
              <Input
                id="pw-next"
                type="password"
                autoComplete="new-password"
                value={next}
                onChange={(event) => setNext(event.target.value)}
                required
                minLength={8}
                maxLength={128}
              />
            </div>
            <FormError message={error} />
            <Button type="submit" disabled={busy}>
              {busy && <LoaderCircle className="size-4 animate-spin" />}
              Lưu mật khẩu mới
            </Button>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

'use client';

import { useSyncExternalStore } from 'react';

// Trạng thái đăng nhập dùng chung cho cả trang. Một kho ở mức module (không
// phải React context) vì header điện thoại và header desktop đều gắn một
// AccountMenu riêng, cùng lúc location-explorer cần token để gọi API "Đã lưu":
// mọi nơi đọc cùng một nguồn, đăng nhập ở đâu cũng cập nhật mọi nơi.
//
// Token chỉ là chìa khoá xác thực — VAI TRÒ thật nằm ở backend, nó đọc lại tài
// khoản ở mỗi request. `user.role` ở đây chỉ để quyết định hiện/ẩn giao diện;
// sửa nó trong DevTools cũng không gọi được API admin.

export type UserRole = 'admin' | 'user';

export type AuthUser = {
  id: string;
  username: string;
  displayName: string | null;
  role: UserRole;
  isActive: boolean;
};

export type AuthState = {
  token: string | null;
  user: AuthUser | null;
};

const STORAGE_KEY = 'nearby-auth';
const EMPTY: AuthState = { token: null, user: null };

function readStored(): AuthState {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return EMPTY;
    const parsed = JSON.parse(raw) as AuthState;
    return parsed?.token && parsed.user ? parsed : EMPTY;
  } catch {
    return EMPTY;
  }
}

let state: AuthState = typeof window === 'undefined' ? EMPTY : readStored();
const listeners = new Set<() => void>();

function emit(next: AuthState) {
  state = next;
  try {
    if (next.token) {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  } catch {
    // Chế độ ẩn danh chặn localStorage: vẫn đăng nhập được trong tab này.
  }
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  // Đăng nhập/đăng xuất ở tab khác thì tab này cũng theo.
  const onStorage = (event: StorageEvent) => {
    if (event.key !== STORAGE_KEY) return;
    state = readStored();
    listener();
  };
  window.addEventListener('storage', onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener('storage', onStorage);
  };
}

export function useAuth(): AuthState {
  return useSyncExternalStore(
    subscribe,
    () => state,
    () => EMPTY,
  );
}

export function setAuth(token: string, user: AuthUser) {
  emit({ token, user });
}

export function clearAuth() {
  emit(EMPTY);
}

/** Header `Authorization` để trộn vào fetch; rỗng khi chưa đăng nhập. */
export function authHeaders(): Record<string, string> {
  return state.token ? { Authorization: `Bearer ${state.token}` } : {};
}

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

/** Gọi API kèm token, ném ApiError mang thông báo `detail` của backend. */
export async function apiRequest<T>(
  apiBaseUrl: string,
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...init,
    headers: {
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
      ...authHeaders(),
      ...(init.headers as Record<string, string> | undefined),
    },
  });
  const data = (await response.json().catch(() => null)) as { detail?: unknown } | null;
  if (!response.ok) {
    // Token hết hạn / tài khoản bị khoá: đăng xuất luôn để giao diện không
    // tiếp tục hiện menu quản trị mà mọi thao tác đều lỗi.
    if (response.status === 401 && state.token) clearAuth();
    const detail = data?.detail;
    throw new ApiError(
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? 'Dữ liệu nhập chưa hợp lệ'
          : `Lỗi ${response.status}`,
      response.status,
    );
  }
  return data as T;
}

let verified = false;

/** Kiểm tra lại token đã lưu một lần mỗi lần tải trang: vai trò có thể đã bị
 * admin khác đổi, tài khoản có thể đã bị khoá kể từ lần đăng nhập trước. */
export async function verifyStoredAuth(apiBaseUrl: string) {
  if (verified || !state.token) return;
  verified = true;
  try {
    const { user } = await apiRequest<{ user: AuthUser }>(
      apiBaseUrl,
      '/api/v1/auth/me',
    );
    if (state.token) emit({ token: state.token, user });
  } catch (error) {
    // Mất mạng thì giữ phiên; chỉ 401/403 mới là token thật sự hết hiệu lực.
    if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
      clearAuth();
    }
  }
}

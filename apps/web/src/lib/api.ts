import type { SessionResponse } from '@mtj/contracts';

/**
 * Fetch wrapper. All calls go through the same-origin /api proxy.
 * The access token lives only in memory; the refresh token is an httpOnly cookie the
 * browser sends to /api/auth/refresh. On a 401 we refresh once and retry.
 */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

let accessToken: string | null = null;
let refreshInFlight: Promise<SessionResponse | null> | null = null;
const authLostListeners = new Set<() => void>();

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

/** Called when the session cannot be refreshed any more (user must log in again). */
export function onAuthLost(listener: () => void): () => void {
  authLostListeners.add(listener);
  return () => authLostListeners.delete(listener);
}

/** Refresh the session. Concurrent callers share one request (rotation allows one use per token). */
export function refreshSession(): Promise<SessionResponse | null> {
  refreshInFlight ??= doRefresh().finally(() => {
    refreshInFlight = null;
  });
  return refreshInFlight;
}

async function doRefresh(): Promise<SessionResponse | null> {
  // A second attempt covers another tab having just rotated the cookie.
  for (let attempt = 0; attempt < 2; attempt++) {
    const res = await fetch('/api/auth/refresh', { method: 'POST', credentials: 'include' });
    if (res.ok) {
      const session = (await res.json()) as SessionResponse;
      setAccessToken(session.accessToken);
      return session;
    }
    if (res.status !== 401) break;
    if (attempt === 0) await new Promise((r) => setTimeout(r, 250));
  }
  setAccessToken(null);
  return null;
}

export async function apiFetch<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`);

  const res = await fetch(`/api${path}`, { ...init, headers, credentials: 'include' });

  if (res.status === 401 && retry && !path.startsWith('/auth/')) {
    const session = await refreshSession();
    if (session) return apiFetch<T>(path, init, false);
    authLostListeners.forEach((l) => l());
  }
  if (!res.ok) throw new ApiError(res.status, await errorMessage(res));
  return (res.status === 204 ? undefined : await res.json()) as T;
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { message?: string | string[] };
    if (body.message) return Array.isArray(body.message) ? body.message.join(', ') : body.message;
  } catch {
    /* non-JSON error body */
  }
  return res.statusText || `Request failed (${res.status})`;
}

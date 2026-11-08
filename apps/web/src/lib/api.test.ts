import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { json, mockFetch, session } from '@/test/fetch-mock';
import { apiFetch, ApiError, onAuthLost, refreshSession, setAccessToken } from './api';

beforeEach(() => setAccessToken('expired'));
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

it('refreshes once on 401 and retries with the new token', async () => {
  const seen: (string | null)[] = [];
  const fetch = mockFetch({
    'GET /api/users/me': (init) => {
      const auth = new Headers(init?.headers).get('Authorization');
      seen.push(auth);
      return auth === 'Bearer access-2' ? json({ id: 'u1' }) : json({}, 401);
    },
    'POST /api/auth/refresh': () => json(session('access-2')),
  });

  await expect(apiFetch('/users/me')).resolves.toEqual({ id: 'u1' });
  expect(seen).toEqual(['Bearer expired', 'Bearer access-2']);
  expect(fetch).toHaveBeenCalledTimes(3);
});

it('shares one refresh request between concurrent callers', async () => {
  const fetch = mockFetch({ 'POST /api/auth/refresh': () => json(session()) });
  await Promise.all([refreshSession(), refreshSession(), refreshSession()]);
  expect(fetch).toHaveBeenCalledTimes(1);
});

it('notifies listeners and throws when the session cannot be refreshed', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  mockFetch({
    'GET /api/connections': () => json({ message: 'Unauthorized' }, 401),
    'POST /api/auth/refresh': () => json({}, 401),
  });
  const lost = vi.fn();
  const off = onAuthLost(lost);
  await expect(apiFetch('/connections')).rejects.toEqual(new ApiError(401, 'Unauthorized'));
  expect(lost).toHaveBeenCalledTimes(1);
  off();
});

it('does not try to refresh for auth endpoints', async () => {
  const fetch = mockFetch({
    'POST /api/auth/login': () => json({ message: 'Invalid email or password' }, 401),
  });
  await expect(apiFetch('/auth/login', { method: 'POST', body: '{}' })).rejects.toThrow(
    'Invalid email or password',
  );
  expect(fetch).toHaveBeenCalledTimes(1);
});

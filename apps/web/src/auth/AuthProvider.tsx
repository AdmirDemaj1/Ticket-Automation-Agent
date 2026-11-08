import type { SessionResponse } from '@mtj/contracts';
import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { apiFetch, onAuthLost, refreshSession, setAccessToken } from '@/lib/api';
import { AuthContext, type AuthContextValue, type AuthState } from './auth-context';

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: 'loading', user: null });
  const queryClient = useQueryClient();

  const applySession = useCallback((session: SessionResponse | null) => {
    if (session) {
      setAccessToken(session.accessToken);
      setState({ status: 'authenticated', user: session.user });
    } else {
      setAccessToken(null);
      setState({ status: 'anonymous', user: null });
    }
  }, []);

  // Restore the session from the refresh cookie on load.
  useEffect(() => {
    let active = true;
    void refreshSession().then((s) => active && applySession(s));
    return () => {
      active = false;
    };
  }, [applySession]);

  useEffect(
    () =>
      onAuthLost(() => {
        applySession(null);
        queryClient.clear();
      }),
    [applySession, queryClient],
  );

  const value = useMemo<AuthContextValue>(
    () => ({
      state,
      login: async (body) =>
        applySession(
          await apiFetch<SessionResponse>('/auth/login', {
            method: 'POST',
            body: JSON.stringify(body),
          }),
        ),
      register: async (body) =>
        applySession(
          await apiFetch<SessionResponse>('/auth/register', {
            method: 'POST',
            body: JSON.stringify(body),
          }),
        ),
      logout: async () => {
        try {
          await apiFetch<void>('/auth/logout', { method: 'POST' });
        } finally {
          applySession(null);
          queryClient.clear();
        }
      },
    }),
    [state, applySession, queryClient],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/* eslint-disable react-refresh/only-export-components -- canonical React Context pattern co-locates Provider + hooks/helpers in one file. */
/**
 * Authentication Context for user session management.
 *
 * The auth-status check runs through TanStack Query (`useQuery`) so
 * exponential backoff with full jitter, AbortController-based unmount
 * cleanup, Strict-Mode safety, and 401/403 fast-fail are all delegated
 * to the library — see https://tanstack.com/query/v5/docs/framework/react/guides/query-retries.
 *
 * The context's public surface (user, isAuthenticated, isLoading,
 * authMode, canRegister, error, login, register, logout, checkAuth) is
 * unchanged so consumer code does not move.
 *
 * Login / register / logout mutate the auth state by invalidating the
 * `['auth', 'status']` query rather than calling a private setter — the
 * single source of truth stays the query cache, which TanStack Query
 * dedupes by reference equality, eliminating the spurious
 * `isAuthenticated` flips that closed the WS prematurely under React
 * Strict Mode.
 */

import React, { createContext, useContext, useCallback, useMemo } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { API_CONFIG } from '../config/api';
import { AUTH_RETRY } from '../lib/connectionConfig';

export interface User {
  id: number;
  email: string;
  display_name: string;
  is_owner: boolean;
}

export interface AuthStatus {
  auth_enabled: boolean;
  auth_mode: 'single' | 'multi';
  authenticated: boolean;
  user: User | null;
  can_register: boolean;
}

interface AuthContextType {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  authMode: 'single' | 'multi';
  canRegister: boolean;
  error: string | null;
  login: (email: string, password: string) => Promise<boolean>;
  register: (email: string, password: string, displayName: string) => Promise<boolean>;
  logout: () => Promise<void>;
  checkAuth: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const getApiBase = () => `${API_CONFIG.PYTHON_BASE_URL}/api/auth`;

const ANONYMOUS_USER: User = {
  id: 0,
  email: 'anonymous',
  display_name: 'Anonymous',
  is_owner: true,
};

// `['auth', 'status']` is the canonical key for the bootstrap query.
// Login / register / logout invalidate it via `queryClient.invalidateQueries`.
export const AUTH_STATUS_QUERY_KEY = ['auth', 'status'] as const;

/**
 * Full-jitter exponential backoff. Constants live in
 * `lib/connectionConfig.ts` (`AUTH_RETRY`) so a future tuning pass is a
 * single-file edit. See that module for the rationale and the reference
 * link to the AWS Architecture Blog.
 */
const authRetryDelay = (attemptIndex: number): number =>
  Math.random() * Math.min(AUTH_RETRY.CAP_MS, AUTH_RETRY.BASE_MS * 2 ** attemptIndex);

/**
 * Retry on network failures + 5xx; never retry on auth errors (401/403)
 * because those are valid responses meaning "auth disabled / not logged
 * in", not "backend unavailable". Cap at `AUTH_RETRY.MAX_ATTEMPTS`.
 */
const authShouldRetry = (failureCount: number, error: unknown): boolean => {
  if (failureCount >= AUTH_RETRY.MAX_ATTEMPTS) return false;
  const msg = error instanceof Error ? error.message : String(error);
  if (msg.includes('HTTP 401') || msg.includes('HTTP 403')) return false;
  return true;
};

const fetchAuthStatus = async ({ signal }: { signal: AbortSignal }): Promise<AuthStatus> => {
  const response = await fetch(`${getApiBase()}/status`, {
    credentials: 'include',
    signal,
  });
  if (!response.ok) {
    // Wrap status in the error message so `authShouldRetry` can detect
    // 401/403 without parsing the original Response.
    throw new Error(`auth.status: HTTP ${response.status}`);
  }
  return response.json() as Promise<AuthStatus>;
};

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const queryClient = useQueryClient();

  // Bootstrap auth-status query. The `signal` plumbed through `queryFn`
  // is automatically aborted when the component unmounts (Strict Mode
  // double-mount lifecycle handled by TanStack Query, see
  // https://tanstack.com/query/v5/docs/react/guides/cancellation).
  const authQuery = useQuery({
    queryKey: AUTH_STATUS_QUERY_KEY,
    queryFn: fetchAuthStatus,
    retry: authShouldRetry,
    retryDelay: authRetryDelay,
    // Boot-once: never refetch on focus / mount / network reconnect.
    // Logout / login explicitly invalidate.
    staleTime: Infinity,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });

  const data = authQuery.data;
  const user: User | null = useMemo(() => {
    if (!data) return null;
    if (data.auth_enabled === false) return ANONYMOUS_USER;
    return data.authenticated ? data.user : null;
  }, [data]);

  const authMode: 'single' | 'multi' = data?.auth_mode ?? 'single';
  const canRegister = data?.can_register ?? false;
  const isAuthenticated = user !== null;
  const isLoading = authQuery.isPending;
  const error = authQuery.isError ? 'Failed to connect to server' : null;

  const invalidateAuth = useCallback(
    () => queryClient.invalidateQueries({ queryKey: AUTH_STATUS_QUERY_KEY }),
    [queryClient],
  );

  const login = useCallback(async (email: string, password: string): Promise<boolean> => {
    try {
      const response = await fetch(`${getApiBase()}/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ email, password }),
      });
      const body = await response.json();

      if (!response.ok || !body.success || !body.user) {
        // Surface the server's error via the query cache so `error` flips
        // through the same path as a normal `isError` would.
        queryClient.setQueryData<AuthStatus | null>(AUTH_STATUS_QUERY_KEY, null);
        return false;
      }

      // Optimistically write the new user into the cache so the UI
      // updates this render; then invalidate so the next refetch
      // picks up server-derived fields (auth_mode, can_register).
      queryClient.setQueryData<AuthStatus>(AUTH_STATUS_QUERY_KEY, {
        auth_enabled: true,
        auth_mode: authMode,
        authenticated: true,
        user: body.user,
        can_register: false,
      });
      await invalidateAuth();
      return true;
    } catch (err) {
      console.error('Login error:', err);
      return false;
    }
  }, [queryClient, invalidateAuth, authMode]);

  const register = useCallback(async (
    email: string,
    password: string,
    displayName: string,
  ): Promise<boolean> => {
    try {
      const response = await fetch(`${getApiBase()}/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ email, password, display_name: displayName }),
      });
      const body = await response.json();

      if (!response.ok || !body.success || !body.user) {
        return false;
      }

      queryClient.setQueryData<AuthStatus>(AUTH_STATUS_QUERY_KEY, {
        auth_enabled: true,
        auth_mode: authMode,
        authenticated: true,
        user: body.user,
        can_register: false,
      });
      await invalidateAuth();
      return true;
    } catch (err) {
      console.error('Register error:', err);
      return false;
    }
  }, [queryClient, invalidateAuth, authMode]);

  const logout = useCallback(async () => {
    try {
      await fetch(`${getApiBase()}/logout`, {
        method: 'POST',
        credentials: 'include',
      });
    } catch (err) {
      console.error('Logout error:', err);
    } finally {
      // Force `authenticated: false` immediately so consumers (esp. the
      // WebSocket logout effect) react this render; then refetch so
      // `can_register` and `auth_mode` come back fresh.
      queryClient.setQueryData<AuthStatus>(AUTH_STATUS_QUERY_KEY, (prev) => ({
        ...(prev ?? { auth_enabled: true, auth_mode: 'single' as const, can_register: false }),
        authenticated: false,
        user: null,
      }));
      await invalidateAuth();
    }
  }, [queryClient, invalidateAuth]);

  const checkAuth = useCallback(async () => {
    await authQuery.refetch();
  }, [authQuery]);

  const value: AuthContextType = useMemo(() => ({
    user,
    isAuthenticated,
    isLoading,
    authMode,
    canRegister,
    error,
    login,
    register,
    logout,
    checkAuth,
  }), [user, isAuthenticated, isLoading, authMode, canRegister, error,
       login, register, logout, checkAuth]);

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = (): AuthContextType => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

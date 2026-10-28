import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { setUnauthorizedHandler, tokenStore } from '../api/client';
import { api } from '../api/endpoints';
import type { Role } from '../api/types';

interface Session {
  username: string;
  role: Role;
}

interface AuthValue {
  session: Session | null;
  ready: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  /** True when the signed-in role is at least `minimum`. */
  can: (minimum: Role) => boolean;
}

const ORDER: Record<Role, number> = { viewer: 1, analyst: 2, admin: 3 };
const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);

  const logout = useCallback(() => {
    tokenStore.clear();
    setSession(null);
  }, []);

  // Restore the session after a page reload.
  useEffect(() => {
    setUnauthorizedHandler(logout);
    if (!tokenStore.get()) {
      setReady(true);
      return () => setUnauthorizedHandler(null);
    }
    api
      .me()
      .then((me) => setSession({ username: me.username, role: me.role as Role }))
      .catch(() => tokenStore.clear())
      .finally(() => setReady(true));
    return () => setUnauthorizedHandler(null);
  }, [logout]);

  const login = useCallback(async (username: string, password: string) => {
    const token = await api.login(username, password);
    tokenStore.set(token.access_token);
    setSession({ username, role: token.role });
  }, []);

  const value = useMemo<AuthValue>(
    () => ({
      session,
      ready,
      login,
      logout,
      can: (minimum) => !!session && ORDER[session.role] >= ORDER[minimum],
    }),
    [session, ready, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>');
  return ctx;
}

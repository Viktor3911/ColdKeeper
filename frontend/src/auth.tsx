import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, type ReactNode } from "react";

import { api, ApiError, setCsrfToken, setUnauthorizedHandler } from "./api/client";
import type { Session } from "./api/types";

interface AuthState {
  session: Session | null;
  loading: boolean;
  isOwner: boolean;
  login: (login: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

/** Forget cached data of the previous user, but keep the session query the provider observes. */
function dropUserData(client: QueryClient): void {
  client.removeQueries({ predicate: (query) => query.queryKey[0] !== "session" });
}

async function loadSession(): Promise<Session | null> {
  try {
    return await api.get<Session>("/api/v1/session");
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null;
    throw error;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["session"], queryFn: loadSession, retry: false, staleTime: Infinity });
  const session = query.data ?? null;

  useEffect(() => {
    setCsrfToken(session?.csrf_token ?? null);
  }, [session]);

  useEffect(() => {
    // An expired session on any request returns the user to the sign-in form.
    setUnauthorizedHandler(() => {
      client.setQueryData(["session"], null);
    });
    return () => {
      setUnauthorizedHandler(null);
    };
  }, [client]);

  const login = useCallback(
    async (loginName: string, password: string) => {
      const created = await api.post<Session>("/api/v1/auth/login", { login: loginName, password });
      setCsrfToken(created.csrf_token);
      dropUserData(client);
      client.setQueryData(["session"], created);
    },
    [client],
  );

  const logout = useCallback(async () => {
    try {
      await api.post("/api/v1/auth/logout");
    } finally {
      setCsrfToken(null);
      client.setQueryData(["session"], null);
      dropUserData(client);
    }
  }, [client]);

  const value = useMemo<AuthState>(
    () => ({ session, loading: query.isPending, isOwner: session?.role === "owner", login, logout }),
    [session, query.isPending, login, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth outside AuthProvider");
  return value;
}

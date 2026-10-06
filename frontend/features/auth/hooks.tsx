"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, getToken, setToken } from "@/shared/api/client";
import { eventSocket } from "@/shared/api/ws";
import { fetchMe, login as loginRequest } from "./api";
import type { User } from "./types";

export type AuthState = {
  user: User | null;
  ready: boolean;
  /**
   * The server could not be reached while restoring the session. Aura has no
   * offline mode: the portal shows a "can't reach the server" state instead.
   */
  serverDown: boolean;
  /** Retry restoring the session (after the server comes back). */
  retry: () => void;
  signIn: (username: string, password: string) => Promise<void>;
  signOut: () => void;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const [serverDown, setServerDown] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const router = useRouter();

  useEffect(() => {
    let cancelled = false;
    const token = getToken();
    if (!token) {
      setReady(true);
      return;
    }
    fetchMe()
      .then((me) => {
        if (cancelled) return;
        setUser(me);
        setServerDown(false);
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiError && (err.isUnreachable || err.kind === "timeout")) {
          // Keep the token: the session may be fine, the server is just away.
          setServerDown(true);
          setUser(null);
        } else {
          setToken(null);
          setUser(null);
          setServerDown(false);
        }
      })
      .finally(() => {
        if (!cancelled) setReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  // A 401 on an existing session ends it immediately.
  useEffect(() => {
    const onExpired = () => {
      setToken(null);
      eventSocket.disconnect();
      setUser(null);
    };
    window.addEventListener("yuki:auth-expired", onExpired);
    return () => window.removeEventListener("yuki:auth-expired", onExpired);
  }, []);

  const retry = useCallback(() => setAttempt((a) => a + 1), []);

  const signIn = useCallback(async (username: string, password: string) => {
    const res = await loginRequest({ username, password });
    setToken(res.access_token);
    let me: User;
    try {
      me = await fetchMe();
    } catch (meErr) {
      setToken(null);
      throw new ApiError(
        "http",
        "Signed in, but your account details could not be loaded. Please try again.",
        meErr instanceof ApiError ? meErr.status : null,
        meErr,
      );
    }
    setServerDown(false);
    setUser(me);
  }, []);

  const signOut = useCallback(() => {
    setToken(null);
    eventSocket.disconnect();
    setUser(null);
    setServerDown(false);
    router.replace("/login");
  }, [router]);

  const value = useMemo<AuthState>(
    () => ({ user, ready, serverDown, retry, signIn, signOut }),
    [user, ready, serverDown, retry, signIn, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

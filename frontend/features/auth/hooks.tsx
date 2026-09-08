"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, getToken, setToken } from "@/shared/api/client";
import { eventSocket } from "@/shared/api/ws";
import { fetchMe, login as loginRequest } from "./api";
import type { User } from "./types";

const DEMO_TOKEN = "demo-offline-token";
const DEMO_USER: User = { id: 1, username: "bhavesh", role: "partner" };
const DEMO_FLAG = "yuki_os_demo";

export type AuthState = {
  user: User | null;
  ready: boolean;
  /** True when we authenticated locally because the API is unreachable. */
  demo: boolean;
  signIn: (username: string, password: string) => Promise<void>;
  signOut: () => void;
};

const AuthContext = createContext<AuthState | null>(null);

function readDemoFlag() {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(DEMO_FLAG) === "1";
  } catch {
    return false;
  }
}

function writeDemoFlag(value: boolean) {
  try {
    if (value) window.localStorage.setItem(DEMO_FLAG, "1");
    else window.localStorage.removeItem(DEMO_FLAG);
  } catch {
    /* ignore */
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [demo, setDemo] = useState(false);
  const [ready, setReady] = useState(false);
  const router = useRouter();

  useEffect(() => {
    let cancelled = false;
    const token = getToken();
    if (!token) {
      setReady(true);
      return;
    }
    if (readDemoFlag()) {
      setUser(DEMO_USER);
      setDemo(true);
      setReady(true);
      return;
    }
    fetchMe()
      .then((me) => {
        if (cancelled) return;
        setUser(me);
        setDemo(false);
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.isUnreachable) {
          // Keep the session; pages will show sample data and a warning banner.
          setUser(DEMO_USER);
          setDemo(true);
        } else {
          setToken(null);
          setUser(null);
        }
      })
      .finally(() => {
        if (!cancelled) setReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Any 401/403 from the API ends the session immediately.
  useEffect(() => {
    const onExpired = () => {
      setToken(null);
      writeDemoFlag(false);
      eventSocket.disconnect();
      setUser(null);
      setDemo(false);
    };
    window.addEventListener("yuki:auth-expired", onExpired);
    return () => window.removeEventListener("yuki:auth-expired", onExpired);
  }, []);

  const signIn = useCallback(async (username: string, password: string) => {
    try {
      const res = await loginRequest({ username, password });
      setToken(res.access_token);
      writeDemoFlag(false);
      // Never fabricate an identity here. DEMO_USER carries a role, and role
      // drives what the portal lets you do (only admins decide approvals), so
      // inventing one would show privileged UI for an unverified session.
      let me;
      try {
        me = await fetchMe();
      } catch (meErr) {
        setToken(null);
        // Deliberately NOT kind "network": login just succeeded, so the API is
        // demonstrably reachable. Marking this unreachable would drop the outer
        // catch into offline preview and hand back a fabricated DEMO_USER —
        // the exact thing this branch exists to prevent.
        throw new ApiError(
          "http",
          "Signed in, but your account details could not be loaded. Please try again.",
          meErr instanceof ApiError ? meErr.status : null,
          meErr,
        );
      }
      setUser(me);
      setDemo(false);
    } catch (err) {
      if (err instanceof ApiError && err.isUnreachable) {
        // Offline preview: only the seeded demo credentials are accepted.
        if (username === "bhavesh" && password === "admin123") {
          setToken(DEMO_TOKEN);
          writeDemoFlag(true);
          setUser({ ...DEMO_USER, username });
          setDemo(true);
          return;
        }
        throw new ApiError(
          "network",
          "Cannot reach the Yuki OS API. Sign in with the demo credentials to preview the portal offline.",
        );
      }
      throw err;
    }
  }, []);

  const signOut = useCallback(() => {
    setToken(null);
    writeDemoFlag(false);
    eventSocket.disconnect();
    setUser(null);
    setDemo(false);
    router.replace("/login");
  }, [router]);

  const value = useMemo<AuthState>(
    () => ({ user, ready, demo, signIn, signOut }),
    [user, ready, demo, signIn, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/shared/api/client";
import { FALLBACK_POLL_MS, useEvents, type LiveFilter } from "@/shared/api/events";
import { eventSocket } from "@/shared/api/ws";

export type Api<T> = {
  data: T;
  /** True only until the first answer for the current deps — refreshes are silent. */
  loading: boolean;
  error: string | null;
  /** The server answered 404 — the record doesn't exist or sits behind a deal wall. */
  unavailable: boolean;
  /** The server answered 403 — this role can't read it. */
  forbidden: boolean;
  refresh: () => void;
};

export type LiveOptions = {
  /** Refetch when a socket event matches. */
  live?: LiveFilter;
  /** Poll at this cadence while the socket is down (default 20s when `live` is set). */
  pollMs?: number;
};

const MISSING = [404];

/**
 * Fetch with loading/error/"not available yet" handling. Never throws.
 * With `live`, the data refreshes on matching socket events, after a
 * reconnect, and by light polling while the socket is down.
 */
export function useApi<T>(
  fetcher: (() => Promise<T>) | null,
  empty: T,
  deps: unknown[] = [],
  options: LiveOptions = {},
): Api<T> {
  const [data, setData] = useState<T>(empty);
  const [loading, setLoading] = useState(fetcher !== null);
  const [error, setError] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [forbidden, setForbidden] = useState(false);
  const [tick, setTick] = useState(0);
  const ref = useRef(fetcher);
  ref.current = fetcher;
  const emptyRef = useRef(empty);
  const depsKey = JSON.stringify(deps);
  const loadedKey = useRef<string | null>(null);
  const filterRef = useRef(options.live);
  filterRef.current = options.live;
  const liveOn = Boolean(options.live);
  const pollMs = options.pollMs ?? (liveOn ? FALLBACK_POLL_MS : 0);
  const { shouldPoll, connection, resync } = useEvents();

  useEffect(() => {
    const f = ref.current;
    if (!f) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    const background = loadedKey.current === depsKey;
    if (!background) setLoading(true);
    f()
      .then((r) => {
        if (cancelled) return;
        loadedKey.current = depsKey;
        setData(r);
        setError(null);
        setUnavailable(false);
        setForbidden(false);
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiError && MISSING.includes(err.status ?? 0)) {
          loadedKey.current = depsKey;
          setUnavailable(true);
          setError(null);
          setData(emptyRef.current);
        } else if (err instanceof ApiError && err.kind === "auth") {
          setError(null);
        } else if (err instanceof ApiError && err.kind === "forbidden") {
          loadedKey.current = depsKey;
          setForbidden(true);
          setError(err.message);
        } else if (background && err instanceof ApiError && (err.kind === "network" || err.kind === "timeout")) {
          // Keep what we have; the shell already says the server is away.
        } else {
          setUnavailable(false);
          setError(err instanceof Error ? err.message : "Something went wrong.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, depsKey]);

  const refresh = useCallback(() => setTick((t) => t + 1), []);

  // Socket events → debounced refetch.
  useEffect(() => {
    if (!liveOn) return;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const off = eventSocket.onEvent((e) => {
      if (!filterRef.current?.(e)) return;
      if (timer) clearTimeout(timer);
      timer = setTimeout(refresh, 250);
    });
    return () => {
      off();
      if (timer) clearTimeout(timer);
    };
  }, [liveOn, refresh]);

  // Missed events while disconnected → resync once.
  const firstResync = useRef(resync);
  useEffect(() => {
    if (!liveOn || resync === firstResync.current) return;
    refresh();
  }, [resync, liveOn, refresh]);

  // Socket down but server up → light polling.
  useEffect(() => {
    if (!pollMs || !shouldPoll || connection === "offline") return;
    const id = setInterval(refresh, pollMs);
    return () => clearInterval(id);
  }, [pollMs, shouldPoll, connection, refresh]);

  return { data, loading, error, unavailable, forbidden, refresh };
}

export function errMessage(err: unknown): string {
  return err instanceof Error ? err.message : "Something went wrong.";
}

/** True when an error is a 403 — callers show a "who can" message instead. */
export function isForbidden(err: unknown) {
  return err instanceof ApiError && err.status === 403;
}

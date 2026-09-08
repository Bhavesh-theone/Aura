"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/shared/api/client";
import { useEvents } from "@/shared/api/events";

export type Source = "live" | "sample";

export type Resource<T> = {
  data: T;
  loading: boolean;
  source: Source;
  /** True when the API could not be reached at all; the UI shows sample data. */
  offline: boolean;
  /** Set for real failures that are not "server is down" (e.g. a 500). */
  error: string | null;
  refresh: () => void;
};

type Options = {
  pollMs?: number;
  /** Treat a 404 as "endpoint not implemented yet" and show sample data. */
  sampleOnMissing?: boolean;
};

/**
 * Fetch a resource, keep it fresh from the event socket (or polling when the
 * socket is down), and fall back to sample data only when the API is
 * unreachable — so an empty live queue is never confused with a demo queue.
 */
export function useResource<T>(
  fetcher: () => Promise<T>,
  sample: T,
  empty: T,
  options: Options = {},
): Resource<T> {
  const { pollMs = 15000, sampleOnMissing = false } = options;
  const { revision, shouldPoll } = useEvents();
  const [data, setData] = useState<T>(empty);
  const [loading, setLoading] = useState(true);
  const [source, setSource] = useState<Source>("live");
  const [offline, setOffline] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const sampleRef = useRef(sample);
  sampleRef.current = sample;

  const load = useCallback(async (signal: { cancelled: boolean }) => {
    try {
      const result = await fetcherRef.current();
      if (signal.cancelled) return;
      setData(result);
      setSource("live");
      setOffline(false);
      setError(null);
    } catch (err) {
      if (signal.cancelled) return;
      const unreachable = err instanceof ApiError && err.isUnreachable;
      const missing = err instanceof ApiError && err.status === 404 && sampleOnMissing;
      if (unreachable || missing) {
        setData(sampleRef.current);
        setSource("sample");
        setOffline(true);
        setError(null);
      } else if (err instanceof ApiError && err.kind === "auth") {
        // The auth layer is already redirecting to /login; stay quiet.
        setError(null);
      } else {
        setSource("live");
        setOffline(false);
        setError(err instanceof Error ? err.message : "Something went wrong.");
      }
    } finally {
      if (!signal.cancelled) setLoading(false);
    }
  }, [sampleOnMissing]);

  useEffect(() => {
    const signal = { cancelled: false };
    load(signal);
    return () => {
      signal.cancelled = true;
    };
  }, [load, revision, tick]);

  useEffect(() => {
    if (!shouldPoll || pollMs <= 0) return;
    const id = setInterval(() => setTick((t) => t + 1), pollMs);
    return () => clearInterval(id);
  }, [shouldPoll, pollMs]);

  const refresh = useCallback(() => setTick((t) => t + 1), []);

  return { data, loading, source, offline, error, refresh };
}

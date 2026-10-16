"use client";

import { anyEvent } from "@/shared/api/events";
import { useApi } from "@/shared/lib/useApi";
import { listActivity } from "./api";
import type { ActivityEntry } from "./types";

/** The audit feed — refreshes on every socket event, polls when the socket is down. */
export function useActivity() {
  const r = useApi<ActivityEntry[]>(listActivity, [], [], { live: anyEvent, pollMs: 15000 });
  return { ...r, activity: r.data };
}

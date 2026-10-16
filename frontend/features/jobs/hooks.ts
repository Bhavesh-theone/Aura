"use client";

import { jobEvents } from "@/shared/api/events";
import { useApi } from "@/shared/lib/useApi";
import { listDeadLetters, listJobs } from "./api";
import type { DeadLetter, Job } from "./types";

export function useJobs() {
  const r = useApi<Job[]>(listJobs, [], [], { live: jobEvents, pollMs: 12000 });
  return { ...r, jobs: r.data };
}

/** Dead-lettered segments; `enabled` false (wrong role) skips the fetch entirely. */
export function useDeadLetters(enabled: boolean) {
  const r = useApi<DeadLetter[]>(enabled ? listDeadLetters : null, [], [enabled], { live: jobEvents, pollMs: 15000 });
  return { ...r, items: r.data };
}

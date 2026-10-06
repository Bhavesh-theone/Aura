"use client";

import { jobEvents } from "@/shared/api/events";
import { useApi } from "@/shared/lib/useApi";
import { listJobs } from "./api";
import type { Job } from "./types";

export function useJobs() {
  const r = useApi<Job[]>(listJobs, [], [], { live: jobEvents, pollMs: 12000 });
  return { ...r, jobs: r.data };
}

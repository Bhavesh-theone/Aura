"use client";

import { useResource } from "@/shared/lib/useResource";
import { listJobs } from "./api";
import { sampleJobs } from "./sample";
import type { Job } from "./types";

export function useJobs() {
  const resource = useResource<Job[]>(listJobs, sampleJobs, [], { pollMs: 12000 });
  return { ...resource, jobs: resource.data };
}

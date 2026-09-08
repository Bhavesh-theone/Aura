import { apiFetch } from "@/shared/api/client";
import type { CreateJobRequest, Job } from "./types";

export function listJobs() {
  return apiFetch<Job[]>("/api/jobs");
}

export function getJob(id: number) {
  return apiFetch<Job>(`/api/jobs/${id}`);
}

export function createJob(body: CreateJobRequest) {
  return apiFetch<Job>("/api/jobs", { method: "POST", body });
}

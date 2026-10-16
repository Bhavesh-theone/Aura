import { apiFetch } from "@/shared/api/client";
import type { Capability, CreateJobRequest, DeadLetter, Job } from "./types";

export function listJobs() {
  return apiFetch<Job[]>("/api/jobs");
}

export function getJob(id: number) {
  return apiFetch<Job>(`/api/jobs/${id}`);
}

export function createJob(body: CreateJobRequest) {
  return apiFetch<Job>("/api/jobs", { method: "POST", body });
}

/** Submit with an Idempotency-Key; reports whether the server replayed an earlier submission. */
export async function submitJob(body: CreateJobRequest, idempotencyKey: string) {
  let replayed = false;
  const job = await apiFetch<Job>("/api/jobs", {
    method: "POST",
    body,
    headers: { "Idempotency-Key": idempotencyKey },
    onResponse: (res) => {
      replayed = res.headers.get("Idempotent-Replayed") === "true" || res.status === 200;
    },
  });
  return { job, replayed };
}

export function listDeadLetters() {
  return apiFetch<DeadLetter[]>("/api/jobs/dead-letter");
}

export function retryJob(id: number) {
  return apiFetch<Job>(`/api/jobs/${id}/retry`, { method: "POST" });
}

/** Launch one agent capability against a deal object. */
export function runCapability(
  dealId: number,
  capability: Capability,
  target: { document_id?: number; party_id?: number; brief?: string },
) {
  return createJob({ deal_id: dealId, inputs: { capability, ...target } });
}

export const CAPABILITY_LABEL: Record<Capability, string> = {
  classify_document: "Classify document",
  draft_email: "Draft email",
  extract_financials: "Extract financials",
};

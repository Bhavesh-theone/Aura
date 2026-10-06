import { apiFetch } from "@/shared/api/client";
import type { Capability, CreateJobRequest, Job } from "./types";

export function listJobs() {
  return apiFetch<Job[]>("/api/jobs");
}

export function getJob(id: number) {
  return apiFetch<Job>(`/api/jobs/${id}`);
}

export function createJob(body: CreateJobRequest) {
  return apiFetch<Job>("/api/jobs", { method: "POST", body });
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

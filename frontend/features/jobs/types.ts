/** Job statuses as the backend emits them (core/domain/enums.py JobStatus). */
export type JobStatus = "pending" | "running" | "awaiting_approval" | "complete" | "failed" | "rejected";

export type JobSegment = {
  id: number;
  name: string;
  agent?: string | null;
  status: string;
  started_at?: string | null;
  finished_at?: string | null;
  detail?: string | null;
};

/** JobResponse (api/schemas/dto.py). */
export type Job = {
  id: number;
  status: JobStatus;
  inputs: Record<string, unknown>;
  result: Record<string, unknown> | null;
  deal_id: number | null;
  created_at: string;
  created_by: string | null;
  trace_id: string | null;
  attempts: number;
  /** Derived: retrying (backing off), deferred (daily model budget spent), dead_letter. */
  phase: JobPhase | null;
  next_attempt_at: string | null;
  last_error: string | null;
};

export type JobPhase = "retrying" | "deferred" | "dead_letter";

/** GET /api/jobs/dead-letter row. */
export type DeadLetter = {
  job: Job;
  segment_id: number;
  seq: number;
  status: "dead_letter";
  attempts: number;
  last_error: string | null;
  claimed_by: string | null;
  ended_at: string | null;
};

/** Agent capabilities the portal can launch (backend submit_job). */
export type Capability = "classify_document" | "draft_email" | "extract_financials";

export type CreateJobRequest = {
  deal_id: number | null;
  inputs: { capability?: Capability; document_id?: number; party_id?: number; brief?: string } & Record<string, unknown>;
};

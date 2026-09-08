export type JobStatus =
  | "queued"
  | "running"
  | "awaiting_approval"
  | "complete"
  | "completed"
  | "failed"
  | string;

export type JobSegment = {
  id: number;
  name: string;
  agent?: string | null;
  status: string;
  started_at?: string | null;
  finished_at?: string | null;
  detail?: string | null;
};

export type Job = {
  id: number;
  status: JobStatus;
  inputs: Record<string, unknown>;
  result: Record<string, unknown> | null;
  deal_id: number | null;
  created_at: string;
  /** Optional — some backends embed the segment timeline in the job payload. */
  segments?: JobSegment[];
};

export type CreateJobRequest = { inputs: Record<string, unknown>; deal_id: number | null };

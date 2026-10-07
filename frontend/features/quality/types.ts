export type CapabilityId = "classify_document" | "extract_financials" | "draft_email";
export const CAPABILITIES: CapabilityId[] = ["classify_document", "extract_financials", "draft_email"];

export type Autonomy = {
  capability: string;
  level: 0 | 1 | 2;
  pinned_model: string | null;
  demoted_at: string | null;
  reason: string | null;
  updated_by: string | null;
  updated_at: string | null;
};

export type EvalMetrics = {
  primary?: string;
  errors?: number;
  total_latency_ms?: number;
  trace_id?: string;
  partial?: boolean;
  case_ids?: string[];
  [key: string]: unknown;
};

export type EvalRun = {
  id: number;
  capability: string;
  orchestrator: "stub" | "crew";
  model_id: string | null;
  golden_sha256: string;
  n_cases: number;
  score: number;
  threshold: number;
  passed: boolean;
  metrics: EvalMetrics;
  started_at: string;
  completed_at: string | null;
  created_by: string | null;
};

export type EvalCase = {
  case_id: string;
  passed: boolean;
  score: number;
  confidence: number | null;
  expected: Record<string, unknown>;
  actual: Record<string, unknown>;
  detail: Record<string, unknown>;
  agent_run_id: number | null;
  latency_ms: number;
  error: string | null;
};

export type EvalRunDetail = EvalRun & { cases: EvalCase[] };

export type OverrideRate = {
  capability: string;
  decisions: number;
  overrides: number;
  rate: number | null;
  window_days: number;
};

export type PromptEntry = {
  template_id: string;
  version: string;
  ref: string;
  role: string;
  sha256: string;
  active: boolean;
  path: string;
};

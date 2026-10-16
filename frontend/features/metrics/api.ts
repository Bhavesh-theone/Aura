import { apiFetch } from "@/shared/api/client";

/** StageDwellOut / SuccessMetricsOut / MetricsOut (api/schemas/deals.py). Percentages are 0–100. */
export type StageDwell = { stage: string; n: number; median_hours: number; p90_hours: number };

export type SuccessMetrics = {
  guarded_forward_transitions_pct: number;
  runs_traceable_pct: number;
  audit_chain_ok: boolean;
  handoff_rejections_422: number;
  outbound_executed: number;
  deals_closed_end_to_end: number;
};

export type ReliabilityMetrics = {
  dead_lettered_segments: number;
  retried_segments: number;
  recovered_segments: number;
  fallback_runs: number;
  budget_deferrals: number;
};
export type OverrideRate = { capability: string; decisions: number; overrides: number; rate: number | null; window_days: number };
export type LatestEval = {
  capability: string;
  eval_run_id: number;
  orchestrator: string;
  model_id: string;
  score: number;
  threshold: number;
  passed: boolean;
  completed_at: string;
};
export type AutonomyLevel = { capability: string; level: number; reason: string | null; demoted_at: string | null };
export type EvaluationMetrics = { latest_runs: LatestEval[]; override_rate: OverrideRate[]; autonomy: AutonomyLevel[] };
export type SecurityMetrics = { injection_suspected: number; untrusted_content_handoffs: number };

export type OutboundMetrics = {
  mode: "off" | "gmail_draft" | "gmail_send";
  drafted: number;
  sent: number;
  blocked: number;
  failed: number;
  blocked_by_reason: Record<string, number>;
  outbound_without_approval: number;
};

export type Metrics = {
  stage_dwell: StageDwell[];
  success: SuccessMetrics;
  reliability?: ReliabilityMetrics | null;
  evaluation?: EvaluationMetrics | null;
  security?: SecurityMetrics | null;
  outbound?: OutboundMetrics | null;
};

export const getMetrics = () => apiFetch<Metrics>("/api/metrics");

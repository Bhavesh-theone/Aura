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

export type Metrics = { stage_dwell: StageDwell[]; success: SuccessMetrics };

export const getMetrics = () => apiFetch<Metrics>("/api/metrics");

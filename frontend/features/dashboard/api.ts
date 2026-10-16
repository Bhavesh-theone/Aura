import { apiFetch } from "@/shared/api/client";
import type { ActivityEntry } from "@/features/activity/types";

/** DashboardOut (api/schemas/handoffs.py). */
export type DashboardSummary = {
  open_deals: number;
  deals_by_class: Record<string, number>;
  /** Counts every stage, CLOSED and the terminal exits included. */
  deals_by_stage: Record<string, number>;
  closed_deals: number;
  ended_deals: number;
  decisions_waiting: number;
  blockers_open: number;
  recent_activity: ActivityEntry[];
};

export const getDashboardSummary = () => apiFetch<DashboardSummary>("/api/dashboard/summary");

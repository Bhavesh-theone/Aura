import type { Category } from "@/shared/ui/Tag";

export type ApprovalStatus = "pending" | "approved" | "rejected";

export type ProposedAction = {
  tool: string;
  category: Category | string;
  arguments: Record<string, unknown>;
  summary: string;
};

export type Approval = {
  id: number;
  segment_id: number;
  category: Category | string;
  proposed_action: ProposedAction;
  status: ApprovalStatus | string;
  /** Optional enrichments — present on some backends, safe when absent. */
  job_id?: number | null;
  created_at?: string | null;
  requested_by?: string | null;
};

import { apiFetch } from "@/shared/api/client";

export type HandoffOption = { id: string; label: string; consequence: string; reversible: boolean };

export type HandoffStatus = "open" | "resolved" | "escalated";
export type HandoffDirection = "bot_to_human" | "human_to_bot";
export type HandoffTrigger = "confidence_below_threshold" | "materiality_gate" | "policy_required" | "explicit_request" | "human_correction" | "untrusted_content";

export type Directive = {
  decision?: string;
  reasoning?: string;
  new_constraints?: { do_not_revisit?: string[] };
  next_checkpoint?: { condition?: string; escalate_if?: string };
};

/** HandoffOut (api/schemas/handoffs.py). context_package keys follow core/policy/handoff_policy.py
 * (validated for bot_to_human; human_to_bot packages may carry less). */
export type Handoff = {
  id: number;
  deal_id: number | null;
  task_id: number;
  job_id: number | null;
  task_type: string;
  direction: HandoffDirection;
  trigger: HandoffTrigger;
  context_package: {
    decision_required?: {
      question: string;
      options: HandoffOption[];
      recommendation?: string;
      confidence?: number;
      /** Optional free-text rationale for the recommendation. */
      rationale?: string;
      /** Optional: the strongest case against the recommendation (given when confidence is low). */
      dissent?: string;
    };
    if_you_do_nothing?: { consequence: string; auto_escalate_at: string; escalates_to_role: string };
    what_happened?: unknown[];
    evidence?: unknown[];
    /** Present on packages built for a gated agent tool call. */
    proposed_action?: { tool: string; category: string; arguments: Record<string, unknown>; summary: string; materiality_inr: number | null };
  };
  directive: Directive | null;
  /** `?status=open` returns escalated handoffs too — they still wait for a human. */
  status: HandoffStatus;
  created_at: string;
  auto_escalate_at: string | null;
  resolved_by: string | null;
  resolved_at: string | null;
};

export type ResolveBody = {
  decision: string;
  reasoning: string;
  new_constraints: { do_not_revisit: string[] };
  next_checkpoint: { condition: string; escalate_if: string };
};

export const listHandoffs = () => apiFetch<Handoff[]>("/api/handoffs?status=open");
export const listResolvedHandoffs = () => apiFetch<Handoff[]>("/api/handoffs?status=resolved");
export const getHandoff = (id: number) => apiFetch<Handoff>(`/api/handoffs/${id}`);
export const resolveHandoff = (id: number, body: ResolveBody) =>
  apiFetch<Handoff>(`/api/handoffs/${id}/resolve`, { method: "POST", body });

export const isEscalated = (h: Pick<Handoff, "status">) => h.status === "escalated";

import { blockReason } from "@/features/integrations/api";
import { formatINRCompact, humanize, stageLabel } from "@/shared/lib/format";
import type { ActivityEntry } from "./types";

/** Backend-written actors that are not people: the worker and seeded/system writes. */
export const isSystemActor = (actor: string) => /agent|system|bot|crew|scheduler|worker|guard|aura/i.test(actor);

export type ActionTone = "accent" | "success" | "warning" | "danger" | "neutral" | "info";
export type ActivityLink = { href: string; label: string };

/**
 * Every audit action the backend writes (core/services/*). Anything else is
 * unexpected and falls back to a humanised name.
 */
export const AUDIT_ACTIONS = [
  "deal_created", "deal_transition", "deal_transition_blocked", "deal_flags_updated", "deal_signoff",
  "wall_member_added", "wall_member_removed",
  "diligence_updated", "condition_created", "condition_updated", "finding_created",
  "extraction_created", "extraction_verified",
  "document_uploaded", "document_downloaded", "document_viewed", "document_updated",
  "mandate_created", "party_created", "party_linked",
  "handoff_created", "handoff_resolved", "handoff_rejected", "handoff_escalated", "handoff_skipped_per_directive",
  "outbound_executed", "outbound_blocked", "outbound_failed",
  "contact_added", "contact_removed", "contact_verified", "suppression_added", "suppression_removed",
  "job_submitted", "job_completed", "segment_failed",
  "segment_retry_scheduled", "segment_dead_lettered", "segment_recovered", "segment_retried",
  "budget_deferred", "orchestrator_fallback", "stale_result_discarded",
  "autonomy_demoted", "autonomy_promoted", "injection_suspected", "note_added",
  "user_created", "user_updated",
  "deal_exported",
] as const;
export type AuditAction = (typeof AUDIT_ACTIONS)[number];

type Payload = Record<string, unknown>;

const DECISION_VERB: Record<string, string> = {
  approve: "approved",
  reject: "rejected",
  confirm: "confirmed",
  keep: "kept",
  verify: "verified",
  discard: "discarded",
};

const str = (v: unknown) => (typeof v === "string" ? v : null);

/** A deal tab link — tab ids match DealDetailView's `?tab=` slugs. */
const dealTab = (e: ActivityEntry, tab?: string, label = "Open deal"): ActivityLink | null =>
  e.deal_id ? { href: `/deals/${e.deal_id}${tab ? `?tab=${tab}` : ""}`, label } : null;
const decisions = (p: Payload): ActivityLink => ({
  href: typeof p.handoff_id === "number" ? `/decisions?handoff=${p.handoff_id}` : "/decisions",
  label: "Decisions",
});
const job = (e: ActivityEntry): ActivityLink => ({ href: e.job_id ? `/jobs?job=${e.job_id}` : "/jobs", label: e.job_id ? `JOB-${e.job_id}` : "Agent jobs" });
const users: ActivityLink = { href: "/admin/users", label: "Users" };
const suppressionLink: ActivityLink = { href: "/settings/suppression", label: "Suppression list" };

type Spec = {
  verb: string | ((p: Payload) => string);
  tone: ActionTone | ((p: Payload) => ActionTone);
  link: (e: ActivityEntry) => ActivityLink | null;
};

const SPEC: Record<AuditAction, Spec> = {
  deal_created: { verb: "opened a deal", tone: "info", link: (e) => dealTab(e) },
  deal_transition: {
    verb: (p) => {
      const to = str(p.to);
      const overridden = Array.isArray(p.overridden) && p.overridden.length > 0;
      return `${to ? `moved a deal to ${stageLabel(to)}` : "moved a deal"}${overridden ? " with an override" : ""}`;
    },
    tone: (p) => (Array.isArray(p.overridden) && p.overridden.length ? "warning" : "accent"),
    link: (e) => dealTab(e, "history"),
  },
  deal_transition_blocked: {
    verb: (p) => (str(p.to) ? `was blocked moving a deal to ${stageLabel(str(p.to)!)}` : "was blocked moving a deal"),
    tone: "danger",
    link: (e) => dealTab(e, "history"),
  },
  deal_flags_updated: { verb: "updated regulatory flags", tone: "accent", link: (e) => dealTab(e) },
  deal_signoff: { verb: "signed off a deal", tone: "success", link: (e) => dealTab(e) },
  deal_exported: {
    verb: (p) => {
      const fmt = { pdf: "PDF", docx: "Word", xlsx: "Excel", json: "JSON", zip: "ZIP", csv: "CSV" }[str(p.format) ?? ""] ?? "a file";
      return p.scope === "deals_list" ? `exported the deals list as ${fmt}` : `exported a deal as ${fmt}`;
    },
    tone: "neutral",
    link: (e) => (e.deal_id ? dealTab(e) : { href: "/deals", label: "Deals" }),
  },
  wall_member_added: { verb: (p) => (str(p.username) ? `added ${p.username} to a deal wall` : "added someone to a deal wall"), tone: "info", link: (e) => dealTab(e) },
  wall_member_removed: { verb: (p) => (str(p.username) ? `removed ${p.username} from a deal wall` : "removed someone from a deal wall"), tone: "warning", link: (e) => dealTab(e) },
  diligence_updated: {
    verb: (p) => (str(p.to) ? `marked a diligence item ${humanize(str(p.to)!).toLowerCase()}` : "updated diligence"),
    tone: (p) => (p.to === "failed" ? "danger" : p.to === "satisfied" ? "success" : p.to === "waived" ? "warning" : "accent"),
    link: (e) => dealTab(e, "diligence"),
  },
  condition_created: { verb: "added a condition precedent", tone: "info", link: (e) => dealTab(e, "conditions") },
  condition_updated: {
    verb: (p) => (str(p.to) ? `marked a condition ${humanize(str(p.to)!).toLowerCase()}` : "updated a condition"),
    tone: (p) => (p.to === "failed" ? "danger" : p.to === "satisfied" ? "success" : p.to === "waived" ? "warning" : "accent"),
    link: (e) => dealTab(e, "conditions"),
  },
  finding_created: {
    verb: (p) => (p.finding_type === "red_flag" ? "raised a red flag" : "raised a finding"),
    tone: (p) => (p.finding_type === "red_flag" ? "danger" : "warning"),
    link: (e) => dealTab(e, "diligence"),
  },
  extraction_created: { verb: "extracted figures from a document", tone: "info", link: (e) => dealTab(e, "extractions") },
  extraction_verified: { verb: "verified an extraction", tone: "success", link: (e) => dealTab(e, "extractions") },
  document_uploaded: { verb: "uploaded a document", tone: "info", link: (e) => dealTab(e, "documents") },
  document_downloaded: { verb: "downloaded a document", tone: "neutral", link: (e) => dealTab(e, "documents") },
  document_viewed: { verb: "viewed a document", tone: "neutral", link: (e) => dealTab(e, "documents") },
  document_updated: {
    verb: (p) => (p.is_executed === true ? "marked a document executed" : "doc_class" in p ? "confirmed a document class" : "updated a document"),
    tone: (p) => (p.is_executed === true || "doc_class" in p ? "success" : "accent"),
    link: (e) => dealTab(e, "documents"),
  },
  mandate_created: { verb: "recorded a mandate", tone: "info", link: (e) => dealTab(e, "mandate") },
  party_created: { verb: (p) => (str(p.display_name) ? `created the party ${p.display_name}` : "created a party"), tone: "info", link: (e) => dealTab(e, "parties") },
  party_linked: { verb: (p) => (str(p.role) ? `attached a party as ${humanize(str(p.role)!).toLowerCase()}` : "attached a party"), tone: "info", link: (e) => dealTab(e, "parties") },
  handoff_created: { verb: "handed a decision to the desk", tone: "warning", link: (e) => decisions(e.payload) },
  handoff_resolved: {
    verb: (p) => {
      const d = str(p.decision);
      if (d && DECISION_VERB[d]) return `${DECISION_VERB[d]} an agent proposal`;
      return p.approved === false ? "rejected an agent proposal" : "approved an agent proposal";
    },
    tone: (p) => (p.approved === false ? "danger" : "success"),
    link: (e) => decisions(e.payload),
  },
  handoff_rejected: { verb: "had a malformed handoff refused", tone: "danger", link: (e) => (e.job_id ? job(e) : dealTab(e)) },
  handoff_escalated: { verb: "escalated an unanswered decision", tone: "danger", link: (e) => decisions(e.payload) },
  handoff_skipped_per_directive: {
    verb: (p) => (p.approved === false ? "skipped work the desk ruled out" : "proceeded per an earlier decision"),
    tone: "neutral",
    link: (e) => (e.job_id ? job(e) : decisions(e.payload)),
  },
    outbound_executed: {
    verb: (p) => {
      const to = str(p.to);
      return p.kind === "send"
        ? `sent an email via Gmail${to ? ` to ${to}` : ""}`
        : p.kind === "draft"
          ? `created a Gmail draft${to ? ` to ${to}` : ""}`
          : str(p.tool)
            ? `executed an outbound action (${p.tool})`
            : "executed an outbound action";
    },
    tone: (p) => (p.kind === "send" ? "danger" : "accent"),
    link: (e) => (typeof e.payload.handoff_id === "number" ? decisions(e.payload) : e.job_id ? job(e) : dealTab(e)),
  },
  outbound_blocked: {
    verb: (p) => `blocked an outbound email${str(p.reason) ? `: ${blockReason(str(p.reason)!)}` : ""}`,
    tone: "warning",
    link: (e) => decisions(e.payload),
  },
  outbound_failed: {
    verb: (p) => `failed to deliver an outbound email${str(p.error) ? `: ${p.error}` : ""}`,
    tone: "danger",
    link: (e) => decisions(e.payload),
  },
  contact_added: { verb: (p) => (str(p.email) ? `added the contact ${p.email}` : "added a contact"), tone: "info", link: (e) => dealTab(e, "parties") },
  contact_removed: { verb: (p) => (str(p.email) ? `removed the contact ${p.email}` : "removed a contact"), tone: "warning", link: (e) => dealTab(e, "parties") },
  contact_verified: { verb: (p) => (str(p.email) ? `verified the email ${p.email}` : "verified a contact email"), tone: "success", link: (e) => dealTab(e, "parties") },
  suppression_added: {
    verb: (p) => (str(p.value) ? `suppressed ${p.kind === "domain" ? "the domain" : "the email"} ${p.value}` : "added a suppression"),
    tone: "warning",
    link: () => suppressionLink,
  },
  suppression_removed: {
    verb: (p) => (str(p.value) ? `lifted the suppression on ${p.value}` : "removed a suppression"),
    tone: "info",
    link: () => suppressionLink,
  },
  job_submitted: { verb: "submitted an agent job", tone: "info", link: job },
  job_completed: { verb: "completed an agent job", tone: "success", link: job },
  segment_failed: {
    verb: (p) => (p.permanent === true ? "failed an agent step for good" : "failed an agent step"),
    tone: "danger",
    link: job,
  },
  segment_retry_scheduled: {
    verb: (p) => `scheduled a retry${typeof p.attempts === "number" ? ` (attempt ${p.attempts})` : ""}`,
    tone: "warning",
    link: job,
  },
  segment_dead_lettered: {
    verb: (p) => (p.reason === "lease_expired" ? "dead-lettered an agent step (worker went silent)" : "dead-lettered an agent step (retries used up)"),
    tone: "danger",
    link: () => ({ href: "/jobs", label: "Review dead letters" }),
  },
  segment_recovered: { verb: "recovered an agent step after a worker stall", tone: "success", link: job },
  segment_retried: { verb: "retried an agent step by hand", tone: "accent", link: job },
  budget_deferred: {
    verb: (p) =>
      typeof p.llm_calls_today === "number" && typeof p.daily_limit === "number"
        ? `deferred a step: daily model budget reached (${p.llm_calls_today}/${p.daily_limit})`
        : "deferred a step: daily model budget reached",
    tone: "warning",
    link: job,
  },
  orchestrator_fallback: { verb: "fell back to the stub orchestrator (model unavailable)", tone: "warning", link: job },
  stale_result_discarded: { verb: "discarded a stale agent result", tone: "warning", link: job },
  autonomy_demoted: {
    verb: (p) =>
      `demoted ${str(p.capability) ? humanize(str(p.capability)!).toLowerCase() : "a capability"}${typeof p.from_level === "number" ? ` from level ${p.from_level} to ${p.to_level}` : ""}`,
    tone: "warning",
    link: () => ({ href: "/quality", label: "Agent quality" }),
  },
  autonomy_promoted: {
    verb: (p) =>
      `promoted ${str(p.capability) ? humanize(str(p.capability)!).toLowerCase() : "a capability"}${typeof p.from_level === "number" ? ` from level ${p.from_level} to ${p.to_level}` : ""}`,
    tone: "success",
    link: () => ({ href: "/quality", label: "Agent quality" }),
  },
  injection_suspected: {
    verb: (p) => `flagged suspected prompt injection${typeof p.risk_score === "number" ? ` (risk ${p.risk_score})` : ""}`,
    tone: "danger",
    link: (e) => (e.job_id ? job(e) : decisions(e.payload)),
  },
  note_added: { verb: "added a deal note", tone: "neutral", link: (e) => dealTab(e) },
  user_created: { verb: (p) => (str(p.username) ? `created the user ${p.username}` : "created a user"), tone: "info", link: () => users },
  user_updated: {
    verb: (p) => {
      const c = (p.changes && typeof p.changes === "object" ? p.changes : {}) as Payload;
      const who = str(p.username) ?? "a user";
      if (c.active === false) return `deactivated ${who}`;
      if (c.active === true) return `reactivated ${who}`;
      if ("role" in c) return `changed ${who}’s role`;
      return `updated ${who}`;
    },
    tone: (p) => ((p.changes as Payload | undefined)?.active === false ? "warning" : "accent"),
    link: () => users,
  },
};

const specFor = (action: string): Spec | null => (action in SPEC ? SPEC[action as AuditAction] : null);

export function verbFor(action: string, payload: Payload): string {
  const s = specFor(action);
  if (!s) return humanize(action).toLowerCase();
  return typeof s.verb === "function" ? s.verb(payload) : s.verb;
}

export function toneFor(action: string, payload: Payload): ActionTone {
  const s = specFor(action);
  if (!s) return "neutral";
  return typeof s.tone === "function" ? s.tone(payload) : s.tone;
}

/** Where the row leads: the deal tab, the decisions inbox, the job, or admin users. */
export function linkFor(entry: ActivityEntry): ActivityLink | null {
  const s = specFor(entry.action);
  return s ? s.link(entry) : entry.deal_id ? dealTab(entry) : null;
}

/** True when a resolved handoff was a "no" (approved=false). */
export const isRejection = (action: string, payload: Payload) => action === "handoff_resolved" && payload.approved === false;

/** Shown in the verb or link already, or not useful in a fact row. */
const HIDDEN_KEYS = new Set(["approved", "handoff_id", "resolved_by", "sha256", "argument_names", "trace_id", "span_id", "outbound_id", "party_id", "contact_id", "suppression_id"]);

/** Trace id carried by audit rows written inside a span, if any. */
export const traceIdFor = (payload: Payload): string | null => str(payload.trace_id) || null;

/** One array element as text: identifiers read "PAN AAACK1234F", other objects as JSON. */
function listItem(item: unknown): string {
  if (item && typeof item === "object") {
    const o = item as Record<string, unknown>;
    return typeof o.scheme === "string" && typeof o.value === "string" ? `${o.scheme} ${o.value}` : JSON.stringify(o);
  }
  return String(item);
}

/** Payload → short readable facts; money keys formatted ₹ L / ₹ Cr. */
export function payloadFacts(payload: Payload): { key: string; value: string; mono?: boolean }[] {
  return Object.entries(payload)
    .filter(([k, v]) => v !== null && v !== undefined && v !== "" && !HIDDEN_KEYS.has(k))
    .slice(0, 5)
    .map(([k, v]) => {
      if (k === "decision" && typeof v === "string") return { key: "Decision", value: DECISION_VERB[v] ? humanize(DECISION_VERB[v]) : humanize(v) };
      if ((k === "from" || k === "to") && Array.isArray(v)) return { key: humanize(k), value: v.length ? v.join(", ") : "none" };
      if (Array.isArray(v)) return { key: humanize(k), value: v.length ? v.map(listItem).join(", ") : "none", mono: true };
      if (typeof v === "number" && /(_inr|amount|fee|total|impact)$/i.test(k)) return { key: humanize(k.replace(/_inr$/i, "")), value: formatINRCompact(v), mono: true };
      if (k === "reason" && typeof v === "string" && /^[a-z]+(_[a-z]+)+$/.test(v)) return { key: "Reason", value: humanize(v) };
      if (typeof v === "number" || /(_id|hash)$/i.test(k)) return { key: humanize(k), value: String(v), mono: true };
      if (typeof v === "boolean") return { key: humanize(k), value: v ? "Yes" : "No" };
      if (typeof v === "object") return { key: humanize(k), value: JSON.stringify(v), mono: true };
      if (typeof v === "string" && /^[A-Z]+(_[A-Z]+)+$|^[A-Z]{4,}$/.test(v)) return { key: humanize(k), value: stageLabel(v) };
      if (typeof v === "string" && /^[a-z]+(_[a-z]+)+$/.test(v)) return { key: humanize(k), value: humanize(v) };
      return { key: humanize(k), value: String(v) };
    });
}

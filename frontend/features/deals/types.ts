export const STAGES = [
  "ORIGINATED", "QUALIFIED", "MANDATED", "PREPARED", "MARKETED", "MATCHED",
  "BID_AUCTION", "NEGOTIATION", "DILIGENCE", "DOCUMENTATION", "CONDITIONS_PRECEDENT", "CLOSED",
] as const;

/** The only backward moves the stage machine allows. */
export const REGRESSIONS: Record<string, string[]> = {
  DILIGENCE: ["NEGOTIATION"],
  DOCUMENTATION: ["NEGOTIATION"],
  CONDITIONS_PRECEDENT: ["DOCUMENTATION"],
  MATCHED: ["MARKETED"],
  BID_AUCTION: ["MARKETED"],
};
export const isRegression = (from: string, to: string) => (REGRESSIONS[from] ?? []).includes(to);
export const DILIGENCE_STATUSES = ["open", "requested", "received", "under_review", "satisfied", "waived", "failed"] as const;
export const CONDITION_STATUSES = ["open", "in_progress", "satisfied", "waived", "failed"] as const;
export const CP_TYPES = ["regulatory_approval", "third_party_consent", "corporate_action", "financing", "no_mac", "title_perfection", "tax_clearance", "other"] as const;
export const PARTY_TYPES = [
  "company", "llp", "fund", "trust", "individual", "government_body", "foreign_entity", "partnership", "sole_prop", "huf",
] as const;

export const TERMINAL_STAGES = ["LAPSED", "WITHDRAWN", "REJECTED", "ABORTED"] as const;

export const CLASSES = ["DEBT", "EQUITY", "MNA", "HYBRID", "JV", "LPGP", "ALLIANCE"] as const;
export const SCHEMES = ["CIN", "LLPIN", "PAN", "GSTIN", "DIN"] as const;
export const ROLES = ["buyer", "seller", "target", "issuer", "investor", "lender", "advisor", "counsel"] as const;
export const DOC_CLASSES = [
  "financial_statement", "cap_table", "board_resolution", "moa_aoa", "term_sheet", "spa", "shpa",
  "valuation_report", "tax_return", "litigation_summary", "env_clearance", "engagement_letter", "nda",
  "bank_statement", "gst_return", "charge_document", "land_title",
] as const;

export type Deal = {
  id: number;
  external_id: string;
  name: string;
  stage: string;
  transaction_class: string;
  owner: string;
  outcome: string | null;
  opened_at: string;
  closed_at: string | null;
  /** Regulatory regimes this deal touches; non-empty means compliance must sign off. */
  regulatory_flags: string[];
};

export type DealParty = { party_id: number; display_name: string; role: string };
export type StageHistory = {
  from_stage: string | null;
  to_stage: string;
  entered_at: string;
  actor: string;
  reason_code: string | null;
  is_regression: boolean;
};
export type DealDetail = Deal & { parties: DealParty[]; history: StageHistory[]; allowed_next: string[] };

export type GuardResult = {
  guard_name: string;
  /** Plain-English statement of the guard, e.g. "A signed engagement letter is on file". */
  description: string;
  result: boolean;
  /** Raw evaluator output (JSON) — never shown verbatim. */
  detail: Record<string, unknown>;
  /** Only "blocking" failures stop a move; "warning" failures are advisory. */
  severity: "blocking" | "warning";
  overridden_by: string | null;
  /** The single role allowed to override this guard. */
  override_role: string | null;
};

/** A failing blocking guard this role may override (with a justification). */
export const overridableBy = (g: GuardResult, role: string | null | undefined) =>
  !g.result && g.severity === "blocking" && !!role && g.override_role === role;

export type Party = {
  id: number;
  party_type: string;
  display_name: string;
  identifiers: { scheme: string; value: string }[];
};

export type DealDocument = {
  id: number;
  deal_id: number;
  doc_class: string;
  filename: string;
  sha256: string;
  byte_size: number;
  current_version: number;
  contains_upsi: boolean;
  /** 1 (public) … 4 (UPSI). */
  sensitivity: number;
  is_executed: boolean;
  /** False while the class is only an agent’s or uploader’s proposal. */
  class_confirmed: boolean;
  uploaded_by: string;
  uploaded_at: string;
};

export type DocumentVersion = { version: number; sha256: string; byte_size: number; uploaded_by: string; uploaded_at: string };

export const SENSITIVITY: Record<number, { label: string; hint: string }> = {
  1: { label: "S1 · Public", hint: "Already public or cleared for release" },
  2: { label: "S2 · Internal", hint: "Deal team and the firm" },
  3: { label: "S3 · Confidential", hint: "Deal team only" },
  4: { label: "S4 · Restricted", hint: "UPSI and the most sensitive material" },
};

export type DiligenceItem = {
  id: number;
  deal_id: number;
  template_id: number | null;
  prompt: string;
  severity: string;
  status: string;
  evidence_doc_ids: number[];
  waiver_justification: string | null;
};

export type Condition = {
  id: number;
  deal_id: number;
  description: string;
  cp_type: string;
  status: string;
  waiver_justification: string | null;
};

export type AgentRun = {
  id: number;
  job_id: number | null;
  deal_id: number | null;
  task_id: number | null;
  archetype: string;
  model_id: string;
  model_version: string;
  prompt_template_id: string;
  prompt_hash: string;
  confidence: number | null;
  tokens_in: number;
  tokens_out: number;
  cost_inr: number;
  latency_ms: number;
  started_at: string;
  completed_at: string;
  tool_calls: unknown[];
};

export type AgentRunMessage = { role: string; content: unknown };
export type AgentRunDetail = AgentRun & {
  input_digest: { messages?: AgentRunMessage[] } & Record<string, unknown>;
  output: Record<string, unknown> | string | null;
};

/* --------------------------------- Mandates -------------------------------- */

export const OPERATORS = ["eq", "in", "not_in", "gte", "lte", "between", "contains"] as const;
export type Operator = (typeof OPERATORS)[number];
export const HARDNESS = ["hard", "soft", "preference"] as const;
export type Hardness = (typeof HARDNESS)[number];

export const MANDATE_SIDES = ["sell", "buy", "raise", "deploy", "partner"] as const;
export type MandateSide = (typeof MANDATE_SIDES)[number];
export const MANDATE_STATUSES = ["draft", "active", "paused", "fulfilled", "expired", "withdrawn"] as const;
export type MandateStatus = (typeof MANDATE_STATUSES)[number];

/** JSON value of a criterion: a 2-list for between, a non-empty list for in / not_in,
 * a number for gte / lte, a string or number for eq / contains. */
export type CriterionValue = string | number | (string | number)[];

/** SOSPE §6.2 mandate criterion (CriterionIO). `weight` is 0–1 and required for soft. */
export type Criterion = {
  criterion_key: string;
  operator: Operator;
  value: CriterionValue;
  hardness: Hardness;
  weight: number | null;
};
export type Mandate = {
  id: number;
  deal_id: number;
  title: string;
  notes: string;
  side: MandateSide;
  status: MandateStatus;
  created_at: string;
  criteria: Criterion[];
};
export type CreateMandateBody = {
  title: string;
  notes: string;
  side: MandateSide;
  status: MandateStatus;
  criteria: Criterion[];
};

/* ---------------------------- Findings, extractions ------------------------- */

export const FINDING_TYPES = ["red_flag", "qualification", "adjustment", "observation"] as const;
export type FindingType = (typeof FINDING_TYPES)[number];
export type Finding = {
  id: number;
  deal_id: number;
  diligence_item_id: number;
  finding_type: FindingType;
  description: string;
  quantified_impact_inr: number | null;
  affects_valuation: boolean;
  raised_by: string;
  raised_at: string;
};

export type Extraction = {
  id: number;
  document_id: number;
  schema_name: string;
  payload: Record<string, unknown>;
  confidence: number;
  feeds_valuation: boolean;
  human_verified_by: string | null;
  human_verified_at: string | null;
  created_at: string;
};

/** PRD F5.5: figures feed valuation only at ≥ 0.95 confidence or after a human verifies them. */
export const VALUATION_CONFIDENCE = 0.95;

/* ----------------------------- Walls, compliance ---------------------------- */

export type Member = { username: string; added_at: string };
export type Signoff = { id: number; deal_id: number; signed_by: string; note: string; signed_at: string };

export const isTerminal = (s: string) => (TERMINAL_STAGES as readonly string[]).includes(s);

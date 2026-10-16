/* Deal intake — mirrors the backend contract (API_CONTRACT.md). */

export type Citation = {
  document_id: number;
  filename: string;
  page_from: number | null;
  page_to: number | null;
  chunk_id: number;
  /** ≤ 200 chars; appears in the chunk text. */
  quote: string;
};

export type FieldType =
  | "text"
  | "textarea"
  | "inr"
  | "number"
  | "integer"
  | "percent"
  | "date"
  | "enum"
  | "identifier"
  | "boolean"
  | "string_list"
  | "parties"
  | "criteria"
  | "flags"
  | "json";

export type FieldSource = "llm" | "table" | "regex" | "user";

export type IntakeField = {
  key: string;
  group: string;
  label: string;
  description: string | null;
  type: FieldType;
  options: string[] | null;
  enum_labels: Record<string, string> | null;
  required: boolean;
  /** INR amounts are integer rupees; dates "YYYY-MM-DD"; percent like 11.25. */
  value: unknown;
  auto_value: unknown;
  confidence: number | null;
  source: FieldSource | null;
  citations: Citation[];
  needs_review: boolean;
  requires_confirmation: boolean;
  accepted: boolean;
  edited: boolean;
  error: string | null;
  conflict_id: string | null;
  note: string | null;
};

export type PartyValue = {
  name: string;
  role: string;
  party_type: string;
  identifiers: { scheme: string; value: string }[];
  include: boolean;
};
export type CriterionValue = {
  criterion_key: string;
  operator: string;
  value: unknown;
  hardness: string;
  weight: number | null;
  include: boolean;
};
export type FlagValue = { flag: string; reason: string; include: boolean };

export type ConflictCandidate = { value: unknown; display: string; source: string; confidence: number; citations: Citation[] };
export type IntakeConflict = {
  id: string;
  field: string;
  label: string;
  candidates: ConflictCandidate[];
  chosen: number | null;
  resolved: boolean;
};

export type FileStage = "uploaded" | "parsing" | "indexed" | "failed";

export type IntakeFile = {
  id: number;
  filename: string;
  doc_class: string;
  byte_size: number;
  sha256: string;
  version: number;
  sensitivity: number;
  contains_upsi: boolean;
  stage: FileStage;
  page_count: number | null;
  chunk_count: number;
  ocr_used: boolean;
  warnings: string[];
  error: string | null;
  uploaded_at: string;
};

export type ProgressStage = "idle" | "indexing" | "extracting" | "ready" | "failed";

export type IntakeProgress = {
  stage: ProgressStage;
  percent: number;
  message: string;
  files_total: number;
  files_indexed: number;
  files_failed: number;
  groups_total: number;
  groups_done: number;
};

export type IntakeStatus = "draft" | "processing" | "review" | "confirmed" | "discarded";

export type IntakeHints = { company_name: string | null; cin: string | null; transaction_class_hint: string | null };

export type IntakeExtraction = {
  status: "idle" | "queued" | "running" | "done" | "failed";
  attempts: number;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  model: string | null;
  llm_used: boolean;
  warnings: string[];
};

export type IntakeGroup = { id: string; label: string; fields: string[] };

export type IntakeReview = {
  needs_review: number;
  unresolved_conflicts: number;
  missing_required: string[];
  errors: Record<string, string>;
  ready: boolean;
};

export type Intake = {
  id: number;
  status: IntakeStatus;
  title: string;
  created_by: string;
  created_at: string;
  updated_at: string;
  hints: IntakeHints;
  transaction_class: string | null;
  external_id: string | null;
  progress: IntakeProgress;
  extraction: IntakeExtraction;
  files: IntakeFile[];
  groups: IntakeGroup[];
  fields: Record<string, IntakeField>;
  conflicts: IntakeConflict[];
  review: IntakeReview;
  confirmed_deal_id: number | null;
};

export type IntakeSummary = {
  id: number;
  status: IntakeStatus;
  title: string;
  transaction_class: string | null;
  files: number;
  progress: IntakeProgress;
  created_at: string;
  updated_at: string;
};

export type FieldPatch = { value?: unknown; accepted?: boolean };

export type IntakePatch = {
  transaction_class?: string;
  external_id?: string | null;
  hints?: Partial<IntakeHints>;
  fields?: Record<string, FieldPatch>;
  conflicts?: Record<string, { chosen: number }>;
  files?: Record<string, { doc_class?: string }>;
};

export type UploadedFile = IntakeFile & { duplicate: boolean };
export type UploadResult = { files: UploadedFile[]; intake: Intake };

export type IntakeChunk = {
  chunk_id: number;
  document_id: number;
  filename: string;
  page_from: number | null;
  page_to: number | null;
  kind: string;
  heading: string | null;
  text: string;
  page_text: string;
};

export type ConfirmResult = { deal_id: number; external_id: string; name: string; warnings: string[]; intake: Intake };

export type DocumentFormats = { extensions: string[]; accept: string; max_upload_mb: number; ocr_enabled: boolean };

export const FALLBACK_FORMATS: DocumentFormats = {
  extensions: [".pdf", ".docx", ".xlsx", ".xlsm", ".csv", ".pptx", ".eml", ".msg", ".txt", ".md", ".markdown"],
  accept: ".pdf,.docx,.xlsx,.xlsm,.csv,.pptx,.eml,.msg,.txt,.md,.markdown",
  max_upload_mb: 25,
  ocr_enabled: true,
};

export const CLASSES = ["DEBT", "EQUITY", "MNA", "HYBRID", "JV", "LPGP", "ALLIANCE"] as const;
export const CLASS_LABEL: Record<string, string> = {
  DEBT: "Debt",
  EQUITY: "Equity",
  MNA: "M&A",
  HYBRID: "Hybrid",
  JV: "JV",
  LPGP: "LP/GP",
  ALLIANCE: "Alliance",
};

export const PARTY_ROLES = ["buyer", "seller", "target", "issuer", "investor", "lender", "advisor", "counsel"] as const;
export const PARTY_TYPES = ["company", "llp", "fund", "trust", "individual", "partnership", "government", "other"] as const;
export const ID_SCHEMES = ["CIN", "LLPIN", "PAN", "GSTIN", "DIN"] as const;
export const OPERATORS = ["eq", "in", "gte", "lte", "between", "not_in", "contains"] as const;
export const HARDNESS = ["hard", "soft", "preference"] as const;
export const FLAGS = ["RBI", "FEMA", "CCI", "SEBI", "PRESS_NOTE_3"] as const;

/** Below this the field is highlighted for review (mirrors the backend threshold). */
export const REVIEW_THRESHOLD = 0.85;

/**
 * The intake wizard as a small pure state machine.
 *
 *   draft → uploading → processing → review → confirmed      (+ error)
 *
 * The server's Intake (status / progress) is the truth; local state adds what
 * only the browser knows: per-file uploads in flight, which step the user is
 * looking at, and edits not yet acknowledged by the server (autosave). Edits
 * are an overlay on the server copy, so a refetch arriving mid-edit never
 * clobbers what the user typed.
 */
import type { FieldPatch, Intake, IntakeConflict, IntakeField, IntakeHints, IntakePatch, UploadedFile } from "./types";

/* ---------------------------------- Types --------------------------------- */

export type View = "start" | "processing" | "review" | "confirm";
export type Step = "loading" | "error" | "gone" | View | "confirmed";
export type Phase = "draft" | "uploading" | "processing" | "review" | "confirmed" | "error";

export type UploadStatus = "invalid" | "queued" | "uploading" | "failed" | "duplicate";
export type UploadItem = {
  localId: string;
  name: string;
  size: number;
  status: UploadStatus;
  pct: number;
  error: string | null;
  /** Worth a retry (network / 5xx) — not for 413 / 415 / invalid. */
  retriable: boolean;
};

export type Pending = {
  fields: Record<string, FieldPatch>;
  conflicts: Record<string, { chosen: number }>;
  hints: Partial<IntakeHints>;
  external_id?: string | null;
  transaction_class?: string;
};

export type SaveStatus = "idle" | "saving" | "saved" | "error";

export type WizardState = {
  intakeId: number | null;
  intake: Intake | null;
  loadError: string | null;
  unavailable: boolean;
  uploads: UploadItem[];
  view: View;
  /** Typed but not yet sent. */
  edits: Pending;
  /** Sent, awaiting the server. */
  inflight: Pending | null;
  save: SaveStatus;
  saveError: string | null;
  /** From a confirm 422 (`field_errors`), cleared as the user edits each field. */
  fieldErrors: Record<string, string>;
  confirmedDealId: number | null;
};

export type Action =
  | { type: "reset" }
  | { type: "resume"; id: number }
  | { type: "created"; intake: Intake }
  | { type: "loaded"; intake: Intake }
  | { type: "loadFailed"; message: string; unavailable: boolean }
  | { type: "queue"; items: UploadItem[] }
  | { type: "progress"; localId: string; pct: number }
  | { type: "uploaded"; localId: string; file: UploadedFile | undefined; intake: Intake }
  | { type: "uploadFailed"; localId: string; message: string; retriable: boolean }
  | { type: "retryUpload"; localId: string }
  | { type: "removeUpload"; localId: string }
  | { type: "go"; view: View }
  | { type: "edit"; patch: Partial<Pending> }
  | { type: "flushStart" }
  | { type: "flushOk"; intake: Intake }
  | { type: "flushFail"; message: string }
  | { type: "fieldErrors"; errors: Record<string, string> }
  | { type: "confirmed"; dealId: number };

/* --------------------------------- Helpers -------------------------------- */

export const emptyPending = (): Pending => ({ fields: {}, conflicts: {}, hints: {} });

export function mergePending(a: Pending, b: Partial<Pending>): Pending {
  const fields = { ...a.fields };
  for (const [k, v] of Object.entries(b.fields ?? {})) fields[k] = { ...fields[k], ...v };
  const out: Pending = {
    fields,
    conflicts: { ...a.conflicts, ...b.conflicts },
    hints: { ...a.hints, ...b.hints },
  };
  const ext = "external_id" in b ? b.external_id : a.external_id;
  if (ext !== undefined) out.external_id = ext;
  const cls = b.transaction_class ?? a.transaction_class;
  if (cls !== undefined) out.transaction_class = cls;
  return out;
}

export const isEmptyPending = (p: Pending | null) =>
  !p ||
  (!Object.keys(p.fields).length &&
    !Object.keys(p.conflicts).length &&
    !Object.keys(p.hints).length &&
    p.external_id === undefined &&
    p.transaction_class === undefined);

/** Wire body for PATCH /api/intakes/{id}. */
export function toPatchBody(p: Pending): IntakePatch {
  const body: IntakePatch = {};
  if (Object.keys(p.fields).length) body.fields = p.fields;
  if (Object.keys(p.conflicts).length) body.conflicts = p.conflicts;
  if (Object.keys(p.hints).length) body.hints = p.hints;
  if (p.external_id !== undefined) body.external_id = p.external_id;
  if (p.transaction_class !== undefined) body.transaction_class = p.transaction_class;
  return body;
}

/** Everything not yet acknowledged: inflight first, newer edits on top. */
export const overlay = (s: WizardState): Pending => (s.inflight ? mergePending(s.inflight, s.edits) : s.edits);

export const hasUnsaved = (s: WizardState) => !isEmptyPending(s.edits) || s.inflight !== null;

export function sameValue(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if ((a === null || a === undefined || a === "") && (b === null || b === undefined || b === "")) return true;
  try {
    return JSON.stringify(a) === JSON.stringify(b);
  } catch {
    return false;
  }
}

/** The field as the user sees it: server copy + unsaved edits. */
export function effectiveField(field: IntakeField, p: Pending): IntakeField {
  const patch = p.fields[field.key];
  if (!patch) return field;
  const hasValue = "value" in patch;
  const value = hasValue ? patch.value : field.value;
  const edited = hasValue ? !sameValue(value, field.auto_value) : field.edited;
  return {
    ...field,
    value,
    edited,
    source: hasValue && edited ? "user" : field.source,
    accepted: patch.accepted ?? (hasValue ? true : field.accepted),
  };
}

export function effectiveConflict(c: IntakeConflict, p: Pending): IntakeConflict {
  const pick = p.conflicts[c.id];
  return pick ? { ...c, chosen: pick.chosen, resolved: true } : c;
}

export const mustAccept = (f: IntakeField) => f.needs_review || f.requires_confirmation;

/** Error to show under a field: confirm 422 > server review errors > field validation. */
export function fieldError(s: WizardState, f: IntakeField): string | null {
  return s.fieldErrors[f.key] ?? s.intake?.review.errors[f.key] ?? f.error ?? null;
}

export type ReviewCounts = { needsReview: number; conflicts: number; errors: number; ready: boolean };

export function reviewCounts(s: WizardState): ReviewCounts {
  const intake = s.intake;
  if (!intake) return { needsReview: 0, conflicts: 0, errors: 0, ready: false };
  const p = overlay(s);
  let needsReview = 0;
  let errors = 0;
  for (const raw of Object.values(intake.fields)) {
    const f = effectiveField(raw, p);
    if (mustAccept(f) && !f.accepted) needsReview += 1;
    if (fieldError(s, f)) errors += 1;
  }
  const conflicts = intake.conflicts.filter((c) => !effectiveConflict(c, p).resolved).length;
  const ready = intake.review.ready && !hasUnsaved(s) && needsReview === 0 && conflicts === 0 && Object.keys(s.fieldErrors).length === 0;
  return { needsReview, conflicts, errors, ready };
}

/** The view a freshly loaded (resumed) intake should open on. */
function initialView(intake: Intake): View {
  if (intake.status === "review") return "review";
  if (intake.status === "processing") return "processing";
  const busy = intake.progress.stage === "indexing" || intake.progress.stage === "extracting";
  return busy ? "processing" : "start";
}

/** Server status moved: follow it unless the user is legitimately elsewhere. */
function nextView(prev: Intake | null, next: Intake, view: View): View {
  if (!prev) return initialView(next);
  if (next.status === "review" && prev.status !== "review") return view === "confirm" ? view : "review";
  if ((next.status === "processing" || next.status === "draft") && (view === "review" || view === "confirm")) {
    return next.status === "processing" ? "processing" : "start";
  }
  return view;
}

/* --------------------------------- Reducer -------------------------------- */

export const initialState = (intakeId: number | null = null): WizardState => ({
  intakeId,
  intake: null,
  loadError: null,
  unavailable: false,
  uploads: [],
  view: "start",
  edits: emptyPending(),
  inflight: null,
  save: "idle",
  saveError: null,
  fieldErrors: {},
  confirmedDealId: null,
});

const mapUpload = (s: WizardState, id: string, f: (u: UploadItem) => UploadItem): UploadItem[] =>
  s.uploads.map((u) => (u.localId === id ? f(u) : u));

export function reducer(s: WizardState, a: Action): WizardState {
  switch (a.type) {
    case "reset":
      return initialState();
    case "resume":
      return initialState(a.id);
    case "created":
      // Hints typed before the draft existed rode along on the POST.
      return { ...s, intakeId: a.intake.id, intake: a.intake, edits: { ...s.edits, hints: {} }, loadError: null };
    case "loaded":
      return {
        ...s,
        intake: a.intake,
        intakeId: a.intake.id,
        loadError: null,
        unavailable: false,
        view: nextView(s.intake, a.intake, s.view),
      };
    case "loadFailed":
      return { ...s, loadError: a.message, unavailable: a.unavailable };
    case "queue":
      return { ...s, uploads: [...s.uploads, ...a.items] };
    case "progress":
      return { ...s, uploads: mapUpload(s, a.localId, (u) => ({ ...u, status: "uploading", pct: a.pct })) };
    case "uploaded": {
      // A fresh file now lives in intake.files; a duplicate stays as a quiet "Already added" row.
      // Concurrent uploads answer out of order: never let an older snapshot drop a file.
      const ids = new Set(a.intake.files.map((f) => f.id));
      const kept = (s.intake?.files ?? []).filter((f) => !ids.has(f.id));
      const intake = kept.length ? { ...a.intake, files: [...a.intake.files, ...kept] } : a.intake;
      const uploads = a.file?.duplicate
        ? mapUpload(s, a.localId, (u) => ({ ...u, status: "duplicate", pct: 100, error: null }))
        : s.uploads.filter((u) => u.localId !== a.localId);
      return { ...s, uploads, intake, intakeId: intake.id };
    }
    case "uploadFailed":
      return {
        ...s,
        uploads: mapUpload(s, a.localId, (u) => ({ ...u, status: "failed", error: a.message, retriable: a.retriable })),
      };
    case "retryUpload":
      return { ...s, uploads: mapUpload(s, a.localId, (u) => ({ ...u, status: "queued", pct: 0, error: null })) };
    case "removeUpload":
      return { ...s, uploads: s.uploads.filter((u) => u.localId !== a.localId) };
    case "go":
      return { ...s, view: a.view };
    case "edit": {
      const fieldErrors = { ...s.fieldErrors };
      for (const k of Object.keys(a.patch.fields ?? {})) delete fieldErrors[k];
      for (const c of Object.keys(a.patch.conflicts ?? {})) {
        delete fieldErrors[`conflict:${c}`];
        const field = s.intake?.conflicts.find((x) => x.id === c)?.field;
        if (field) delete fieldErrors[field];
      }
      return { ...s, edits: mergePending(s.edits, a.patch), fieldErrors, save: s.save === "saved" ? "idle" : s.save };
    }
    case "flushStart":
      return { ...s, inflight: overlay(s), edits: emptyPending(), save: "saving", saveError: null };
    case "flushOk":
      return { ...s, inflight: null, intake: a.intake, save: "saved", view: nextView(s.intake, a.intake, s.view) };
    case "flushFail":
      // Never lose an edit: put what was in flight back under anything newer.
      return {
        ...s,
        edits: s.inflight ? mergePending(s.inflight, s.edits) : s.edits,
        inflight: null,
        save: "error",
        saveError: a.message,
      };
    case "fieldErrors":
      return { ...s, fieldErrors: a.errors };
    case "confirmed":
      return { ...s, confirmedDealId: a.dealId };
  }
}

/* -------------------------------- Selectors ------------------------------- */

export function stepOf(s: WizardState): Step {
  if (s.confirmedDealId !== null || s.intake?.status === "confirmed") return "confirmed";
  if (s.intakeId !== null && !s.intake) return s.unavailable ? "gone" : s.loadError ? "error" : "loading";
  if (s.intake?.status === "discarded") return "gone";
  return s.view;
}

export function phaseOf(s: WizardState): Phase {
  const step = stepOf(s);
  if (step === "confirmed") return "confirmed";
  if (step === "error" || step === "gone") return "error";
  if (s.uploads.some((u) => u.status === "queued" || u.status === "uploading")) return "uploading";
  if (s.intake?.status === "review") return "review";
  if (s.intake?.status === "processing" || step === "processing") return "processing";
  return "draft";
}

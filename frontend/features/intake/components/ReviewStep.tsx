"use client";

import { ArrowLeft, ArrowRight, CircleAlert, CircleCheck, CornerDownRight, RotateCw } from "lucide-react";
import { useCallback, useState } from "react";
import { cx } from "@/shared/lib/format";
import { Badge, Button, Spinner, labelCls, selectCls } from "@/shared/ui/primitives";
import { EmptyState, Notice } from "@/shared/ui/States";
import type { IntakeWizard } from "../hooks";
import { effectiveConflict, effectiveField, fieldError, hasUnsaved, mustAccept, overlay, reviewCounts, type WizardState } from "../machine";
import { CLASSES, CLASS_LABEL } from "../types";
import { CitationPane } from "./CitationPane";
import { FieldRow, fieldDomId, type CitationTarget } from "./FieldRow";

/* ------------------------------- Save status ------------------------------- */

export function SaveIndicator({ s, onRetry }: { s: WizardState; onRetry: () => void }) {
  const unsaved = hasUnsaved(s);
  return (
    <span role="status" aria-live="polite" className="inline-flex h-7 items-center gap-1.5 text-[12px] text-muted">
      {s.save === "saving" ? (
        <>
          <Spinner className="h-3 w-3" /> Saving…
        </>
      ) : s.save === "error" ? (
        <>
          <CircleAlert className="h-3.5 w-3.5 text-danger" />
          <span className="text-danger">Couldn’t save</span>
          <button type="button" onClick={onRetry} className="inline-flex h-6 items-center gap-1 rounded-xs px-1.5 font-medium text-fg-2 hover:bg-control-hover hover:text-fg">
            <RotateCw className="h-3 w-3" /> Retry
          </button>
        </>
      ) : unsaved ? (
        "Unsaved changes"
      ) : s.save === "saved" ? (
        <>
          <CircleCheck className="h-3.5 w-3.5 text-success" /> Saved
        </>
      ) : (
        "Draft saved automatically"
      )}
    </span>
  );
}

/** Scroll to and focus the next field still needing attention, after the focused one. */
function jumpToNext() {
  const rows = Array.from(document.querySelectorAll<HTMLElement>("[data-attention='true'],[data-error='true']"));
  if (!rows.length) return;
  const active = document.activeElement;
  const after = rows.find((r) => active && !r.contains(active) && active.compareDocumentPosition(r) & Node.DOCUMENT_POSITION_FOLLOWING);
  const row = after ?? rows[0];
  row.scrollIntoView({ block: "center", behavior: "smooth" });
  row.querySelector<HTMLElement>("input,select,textarea,button")?.focus({ preventScroll: true });
}

function Count({ n, label, tone }: { n: number; label: string; tone: "warning" | "danger" | "neutral" }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[12px]">
      <Badge tone={n === 0 ? "neutral" : tone} mono>
        <span className="num">{n}</span>
      </Badge>
      <span className={n ? "text-fg-2" : "text-muted"}>{label}</span>
    </span>
  );
}

/* ----------------------------------- Step ---------------------------------- */

export function ReviewStep({ w, onContinue }: { w: IntakeWizard; onContinue: () => void }) {
  const s = w.state;
  const intake = s.intake;
  const [cite, setCite] = useState<CitationTarget | null>(null);
  const p = overlay(s);
  const counts = reviewCounts(s);
  const conflicts = new Map((intake?.conflicts ?? []).map((c) => [c.id, effectiveConflict(c, p)]));
  const { edit } = w;

  const setValue = useCallback((key: string, value: unknown) => edit({ fields: { [key]: { value } } }), [edit]);
  const setAccepted = useCallback((key: string, accepted: boolean) => edit({ fields: { [key]: { accepted } } }), [edit]);
  const pick = useCallback((id: string, chosen: number) => edit({ conflicts: { [id]: { chosen } } }), [edit]);

  if (!intake) return null;
  const cls = p.transaction_class ?? intake.transaction_class ?? "";
  const switching = s.inflight?.transaction_class !== undefined || s.edits.transaction_class !== undefined;
  const missing = intake.review.missing_required;

  const groups = intake.groups
    .map((g) => ({ ...g, list: g.fields.map((k) => intake.fields[k]).filter(Boolean).map((f) => effectiveField(f, p)) }))
    .filter((g) => g.list.length > 0);

  const blocker = counts.ready
    ? null
    : hasUnsaved(s)
      ? "Saving your changes…"
      : counts.conflicts
        ? "Resolve the conflicting values first."
        : counts.needsReview
          ? "Accept or edit every highlighted field."
          : counts.errors || Object.keys(s.fieldErrors).length
            ? "Fix the fields marked in red."
            : missing.length
              ? "Fill in the required fields."
              : "Waiting for the server to re-check the draft…";

  return (
    <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_400px]">
      <div className="min-w-0">
        {/* Summary bar */}
        <div className="sticky top-12 z-20 -mx-2 mb-4 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-md border border-line bg-raised px-3 py-2 shadow-card">
          <Count n={counts.needsReview} label="need review" tone="warning" />
          <Count n={counts.conflicts} label="conflicts" tone="warning" />
          <Count n={counts.errors} label="errors" tone="danger" />
          {counts.needsReview + counts.conflicts + counts.errors > 0 ? (
            <Button size="sm" variant="ghost" onClick={jumpToNext}>
              <CornerDownRight className="h-3.5 w-3.5" /> Next to check
            </Button>
          ) : null}
          <div className="ml-auto flex items-center gap-3">
            <SaveIndicator s={s} onRetry={w.flush} />
            <Button onClick={onContinue} disabled={!counts.ready} aria-describedby={blocker ? "ik-blocker" : undefined}>
              Continue to confirm <ArrowRight className="h-4 w-4" />
            </Button>
          </div>
          {blocker ? (
            <p id="ik-blocker" className="w-full text-[12px] text-muted">{blocker}</p>
          ) : null}
        </div>

        <div className="mb-5 flex flex-wrap items-end gap-4">
          <div className="w-64">
            <label htmlFor="ik-txclass" className={labelCls}>
              Transaction class <span className="text-danger" aria-hidden>*</span>
            </label>
            <select
              id="ik-txclass"
              value={cls}
              disabled={switching}
              onChange={(e) => {
                setCite(null);
                edit({ transaction_class: e.target.value });
              }}
              className={selectCls}
            >
              {!cls ? <option value="">Choose a class…</option> : null}
              {CLASSES.map((c) => (
                <option key={c} value={c}>{CLASS_LABEL[c]}</option>
              ))}
            </select>
          </div>
          <p className="flex h-8 items-center gap-1.5 text-[12px] text-muted">
            {switching ? (
              <>
                <Spinner className="h-3 w-3" /> Rebuilding the class-specific profile…
              </>
            ) : (
              "Changing the class rebuilds the class-specific profile fields."
            )}
          </p>
          <Button size="sm" variant="ghost" className="ml-auto" onClick={() => w.dispatch({ type: "go", view: "start" })}>
            <ArrowLeft className="h-3 w-3" /> Documents
          </Button>
        </div>

        {missing.length ? (
          <Notice tone="warn" title="Still required" className="mb-4">
            {missing.map((k, i) => (
              <span key={k}>
                {i ? ", " : ""}
                <button
                  type="button"
                  className="underline decoration-warning-border underline-offset-2 hover:decoration-current"
                  onClick={() => {
                    const el = document.getElementById(`${fieldDomId(k)}-row`);
                    el?.scrollIntoView({ block: "center", behavior: "smooth" });
                    el?.querySelector<HTMLElement>("input,select,textarea,button")?.focus({ preventScroll: true });
                  }}
                >
                  {intake.fields[k]?.label ?? k}
                </button>
              </span>
            ))}
          </Notice>
        ) : null}

        {groups.length === 0 ? (
          <EmptyState title="Nothing was extracted" description="Aura couldn’t find deal fields in these documents. Add more documents, or retry extraction." />
        ) : (
          <div className="space-y-5">
            {groups.map((g) => {
              const open = g.list.filter((f) => (mustAccept(f) && !f.accepted) || (f.conflict_id && !conflicts.get(f.conflict_id)?.resolved)).length;
              return (
                <section key={g.id} aria-labelledby={`ik-g-${g.id}`} className="rounded-md border border-line bg-surface shadow-card">
                  <div className="flex h-10 items-center gap-2 border-b border-line-subtle px-4">
                    <h3 id={`ik-g-${g.id}`} className="text-[13px] font-medium text-fg">{g.label}</h3>
                    <span className="num text-[12px] text-muted">{g.list.length}</span>
                    {open ? <Badge tone="warning" className="ml-auto">{open} to check</Badge> : null}
                  </div>
                  <div className={cx("grid grid-cols-1 gap-1 p-2", g.id !== "parties" && g.id !== "mandate" && "lg:grid-cols-2")}>
                    {g.list.map((f) => {
                      const wide = ["textarea", "parties", "criteria", "flags", "string_list", "json"].includes(f.type) || f.conflict_id;
                      return (
                        <div key={f.key} className={cx(wide && "lg:col-span-2")}>
                          <FieldRow
                            field={f}
                            error={fieldError(s, f) ?? (f.conflict_id ? s.fieldErrors[`conflict:${f.conflict_id}`] ?? null : null)}
                            conflict={f.conflict_id ? conflicts.get(f.conflict_id) ?? null : null}
                            activeKey={cite?.key ?? null}
                            onChange={(v) => setValue(f.key, v)}
                            onAccept={(v) => setAccepted(f.key, v)}
                            onPick={pick}
                            onCite={setCite}
                          />
                        </div>
                      );
                    })}
                  </div>
                </section>
              );
            })}
          </div>
        )}
      </div>

      {/* Citation pane: sticky column on wide screens, a floating panel when narrower. */}
      <aside
        aria-label="Source passage"
        className={cx(
          "overflow-hidden rounded-md border border-line bg-surface shadow-card",
          "xl:sticky xl:top-[60px] xl:block xl:h-[calc(100vh-76px)]",
          cite ? "fixed inset-y-2 right-2 z-40 w-[min(420px,calc(100vw-16px))] shadow-overlay xl:inset-auto xl:z-auto xl:w-auto xl:shadow-card" : "hidden",
        )}
      >
        <CitationPane
          intakeId={intake.id}
          target={cite}
          onIndex={(index) => setCite((c) => (c ? { ...c, index } : c))}
          onClose={() => setCite(null)}
        />
      </aside>
    </div>
  );
}

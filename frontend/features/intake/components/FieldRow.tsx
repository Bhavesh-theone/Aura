"use client";

import { Check, Undo2 } from "lucide-react";
import { cx } from "@/shared/lib/format";
import { Badge, Button, Tip, labelCls } from "@/shared/ui/primitives";
import { mustAccept } from "../machine";
import type { Citation, IntakeConflict, IntakeField } from "../types";
import { ConfidenceBadge, SourceChip, pageLabel } from "./bits";
import { FieldInput } from "./FieldInput";

export const fieldDomId = (key: string) => `ik-f-${key.replace(/[^a-zA-Z0-9_-]/g, "-")}`;

export type CitationTarget = { key: string; label: string; citations: Citation[]; index: number };

function ConflictCards({
  conflict,
  activeKey,
  onPick,
  onCite,
}: {
  conflict: IntakeConflict;
  activeKey: string | null;
  onPick: (i: number) => void;
  onCite: (t: CitationTarget) => void;
}) {
  return (
    <div role="group" aria-label={`Conflicting values for ${conflict.label} — pick one`} className="grid grid-cols-1 gap-2 sm:grid-cols-2">
      {conflict.candidates.map((c, i) => {
        const picked = conflict.chosen === i;
        const citeKey = `conflict:${conflict.id}:${i}`;
        const first = c.citations[0];
        return (
          <div
            key={i}
            className={cx(
              "flex flex-col rounded-sm border bg-surface p-2.5 transition-colors",
              picked ? "border-accent bg-accent-soft" : "border-line hover:border-line-strong",
            )}
          >
            <button
              type="button"
              aria-pressed={picked}
              onClick={() => onPick(i)}
              className="flex items-start gap-2 rounded-xs text-left"
            >
              <span
                aria-hidden
                className={cx(
                  "mt-0.5 inline-flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full border",
                  picked ? "border-accent bg-accent text-on-accent" : "border-line-strong",
                )}
              >
                {picked ? <Check className="h-2.5 w-2.5" strokeWidth={3} /> : null}
              </span>
              <span className="min-w-0 flex-1">
                <span className="num block break-words text-[13px] font-medium text-fg">{c.display}</span>
                <span className="sr-only">{picked ? " (chosen)" : " — choose this value"}</span>
              </span>
            </button>
            {first ? (
              <p className="mt-1.5 line-clamp-2 pl-[22px] text-[12px] italic leading-snug text-muted">“{first.quote}”</p>
            ) : null}
            <div className="mt-2 flex flex-wrap items-center gap-1.5 pl-[22px]">
              <ConfidenceBadge value={c.confidence} />
              <SourceChip
                source={c.source}
                citations={c.citations}
                active={activeKey === citeKey}
                onOpen={() => onCite({ key: citeKey, label: `${conflict.label} — option ${i + 1}`, citations: c.citations, index: 0 })}
              />
              {first && pageLabel(first) ? <span className="truncate text-[11px] text-muted">{first.filename}</span> : null}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function FieldRow({
  field,
  error,
  conflict,
  activeKey,
  onChange,
  onAccept,
  onPick,
  onCite,
}: {
  field: IntakeField;
  error: string | null;
  conflict: IntakeConflict | null;
  activeKey: string | null;
  onChange: (v: unknown) => void;
  onAccept: (v: boolean) => void;
  onPick: (conflictId: string, i: number) => void;
  onCite: (t: CitationTarget) => void;
}) {
  const id = fieldDomId(field.key);
  const attention = mustAccept(field) && !field.accepted;
  const unresolved = conflict && !conflict.resolved;
  const describedBy = [field.description && `${id}-desc`, error && `${id}-err`].filter(Boolean).join(" ") || undefined;

  return (
    <div
      id={`${id}-row`}
      data-attention={attention || unresolved ? "true" : undefined}
      data-error={error ? "true" : undefined}
      className={cx(
        "scroll-mt-28 rounded-sm border px-3 py-3 transition-colors",
        error ? "border-danger-border bg-danger-soft/40" : attention || unresolved ? "border-warning-border bg-warning-soft" : "border-transparent",
      )}
    >
      <div className="mb-1.5 flex flex-wrap items-center gap-x-2 gap-y-1">
        <label id={`${id}-label`} htmlFor={id} className={cx(labelCls, "mb-0")}>
          {field.label}
          {field.required ? <span className="text-danger" aria-hidden> *</span> : null}
          {field.required ? <span className="sr-only"> (required)</span> : null}
        </label>
        <ConfidenceBadge value={field.confidence} />
        <SourceChip
          source={field.source}
          citations={field.citations}
          active={activeKey === field.key}
          onOpen={() => onCite({ key: field.key, label: field.label, citations: field.citations, index: 0 })}
        />
        {field.edited ? (
          <>
            <Badge tone="accent">Changed</Badge>
            <Tip label="Revert to the extracted value">
              <button
                type="button"
                onClick={() => onChange(field.auto_value ?? null)}
                aria-label={`Revert ${field.label} to the extracted value`}
                className="inline-flex h-5 items-center gap-1 rounded-xs px-1 text-[11px] text-muted hover:bg-control-hover hover:text-fg"
              >
                <Undo2 className="h-3 w-3" /> Revert
              </button>
            </Tip>
          </>
        ) : null}
        {field.note ? <span className="text-[11px] text-muted">{field.note}</span> : null}
      </div>

      {unresolved ? (
        <ConflictCards conflict={conflict} activeKey={activeKey} onPick={(i) => onPick(conflict.id, i)} onCite={onCite} />
      ) : (
        <FieldInput field={field} id={id} onChange={onChange} invalid={Boolean(error)} describedBy={describedBy} />
      )}

      {field.description ? <p id={`${id}-desc`} className="mt-1.5 text-[12px] leading-relaxed text-muted">{field.description}</p> : null}
      {error ? <p id={`${id}-err`} className="mt-1.5 text-[12px] font-medium text-danger">{error}</p> : null}

      {mustAccept(field) && !unresolved ? (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {field.accepted ? (
            <>
              <span className="inline-flex items-center gap-1 text-[12px] font-medium text-success">
                <Check className="h-3.5 w-3.5" strokeWidth={2.4} /> {field.edited ? "Edited by you" : "Accepted"}
              </span>
              {!field.edited ? (
                <button type="button" onClick={() => onAccept(false)} className="h-6 rounded-xs px-1.5 text-[12px] text-muted hover:bg-control-hover hover:text-fg">
                  Undo
                </button>
              ) : null}
            </>
          ) : (
            <>
              <Button size="sm" variant="secondary" onClick={() => onAccept(true)} aria-describedby={`${id}-why`}>
                <Check className="h-3.5 w-3.5" /> Accept
              </Button>
              <span id={`${id}-why`} className="text-[12px] text-warning">
                {field.requires_confirmation ? "Valuation input — confirm it against the source." : "Low confidence — check it, then accept or edit."}
              </span>
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}

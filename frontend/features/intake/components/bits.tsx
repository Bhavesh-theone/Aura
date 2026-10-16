"use client";

import { Bot, Check, FileSpreadsheet, Quote, Regex, UserRound } from "lucide-react";
import { cx } from "@/shared/lib/format";
import { Badge, Tip } from "@/shared/ui/primitives";
import { REVIEW_THRESHOLD, type Citation, type FieldSource } from "../types";

/** "97%" — green when trusted, amber below the review threshold, red when weak. */
export function ConfidenceBadge({ value }: { value: number | null }) {
  if (value === null || value === undefined) return null;
  const pct = Math.round(value * 100);
  const tone = value >= REVIEW_THRESHOLD ? "success" : value >= 0.5 ? "warning" : "danger";
  return (
    <Badge tone={tone} mono title={`Extraction confidence ${pct}%`}>
      <span className="num">{pct}%</span>
      <span className="sr-only"> confidence</span>
    </Badge>
  );
}

const SOURCE: Record<FieldSource, { label: string; Icon: typeof Bot; hint: string }> = {
  table: { label: "Table", Icon: FileSpreadsheet, hint: "Read from a table in the document" },
  regex: { label: "Regex", Icon: Regex, hint: "Matched by a deterministic pattern" },
  llm: { label: "Model", Icon: Bot, hint: "Inferred by the extraction model" },
  user: { label: "You", Icon: UserRound, hint: "Entered by you" },
};

export function pageLabel(c: Pick<Citation, "page_from" | "page_to">) {
  if (c.page_from === null) return null;
  return c.page_to !== null && c.page_to !== c.page_from ? `pp. ${c.page_from}–${c.page_to}` : `p. ${c.page_from}`;
}

/**
 * Where a value came from. With citations it is a button that opens the
 * source passage in the citation pane.
 */
export function SourceChip({
  source,
  citations,
  active,
  onOpen,
}: {
  source: FieldSource | string | null;
  citations: Citation[];
  active?: boolean;
  onOpen?: () => void;
}) {
  const meta = source && source in SOURCE ? SOURCE[source as FieldSource] : null;
  if (!meta && citations.length === 0) return null;
  const first = citations[0];
  const where = first ? pageLabel(first) : null;
  const content = (
    <>
      {meta ? <meta.Icon className="h-3 w-3" aria-hidden /> : <Quote className="h-3 w-3" aria-hidden />}
      <span>{meta?.label ?? "Source"}</span>
      {first ? (
        <span className="max-w-[140px] truncate font-normal text-muted">
          · {where ?? first.filename}
          {citations.length > 1 ? ` +${citations.length - 1}` : ""}
        </span>
      ) : null}
    </>
  );
  const cls = cx(
    "inline-flex h-5 max-w-full items-center gap-1 rounded-xs border px-1.5 text-[11px] font-medium leading-none",
    active ? "border-accent-border bg-accent-soft text-accent" : "border-line bg-well text-fg-2",
  );
  if (!citations.length || !onOpen) {
    return (
      <span className={cls} title={meta?.hint}>
        {content}
      </span>
    );
  }
  return (
    <Tip label={`Show source — ${first.filename}${where ? `, ${where}` : ""}`}>
      <button
        type="button"
        onClick={onOpen}
        aria-pressed={active}
        aria-label={`Show source for this value: ${first.filename}${where ? `, ${where}` : ""}`}
        className={cx(cls, "transition-colors hover:border-line-strong hover:text-fg")}
      >
        {content}
      </button>
    </Tip>
  );
}

export function ProgressBar({ pct, label, tone = "accent", className }: { pct: number; label: string; tone?: "accent" | "danger" | "success"; className?: string }) {
  const v = Math.max(0, Math.min(100, Math.round(pct)));
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuenow={v}
      aria-valuemin={0}
      aria-valuemax={100}
      className={cx("h-1 overflow-hidden rounded-full bg-control-active", className)}
    >
      <div
        className={cx(
          "h-full transition-[width] duration-300",
          tone === "danger" ? "bg-danger" : tone === "success" ? "bg-success" : "bg-accent",
        )}
        style={{ width: `${v}%` }}
      />
    </div>
  );
}

/* --------------------------------- Stepper -------------------------------- */

export const STEPS = [
  { id: "start", label: "Documents" },
  { id: "processing", label: "Extraction" },
  { id: "review", label: "Review" },
  { id: "confirm", label: "Confirm" },
] as const;

export function Stepper({ current, reachable, onGo }: { current: string; reachable: (id: string) => boolean; onGo: (id: string) => void }) {
  const idx = STEPS.findIndex((s) => s.id === current);
  return (
    <nav aria-label="Intake steps">
      <ol className="flex flex-wrap items-center gap-x-1 gap-y-2">
        {STEPS.map((s, i) => {
          const done = i < idx;
          const here = i === idx;
          const can = !here && reachable(s.id);
          return (
            <li key={s.id} className="flex items-center gap-1">
              {i > 0 ? <span aria-hidden className={cx("mx-1 h-px w-6", done || here ? "bg-accent-border" : "bg-line")} /> : null}
              <button
                type="button"
                disabled={!can}
                onClick={() => onGo(s.id)}
                aria-current={here ? "step" : undefined}
                className={cx(
                  "inline-flex h-7 items-center gap-2 rounded-sm px-2 text-[12px] font-medium transition-colors",
                  here ? "text-fg" : done ? "text-fg-2" : "text-muted",
                  can && "hover:bg-control-hover hover:text-fg",
                  "disabled:cursor-default",
                )}
              >
                <span
                  aria-hidden
                  className={cx(
                    "inline-flex h-[18px] w-[18px] items-center justify-center rounded-full border text-[10px]",
                    here ? "border-accent bg-accent text-on-accent" : done ? "border-accent-border bg-accent-soft text-accent" : "border-line-strong text-muted",
                  )}
                >
                  {done ? <Check className="h-3 w-3" strokeWidth={2.6} /> : i + 1}
                </span>
                {s.label}
                {done ? <span className="sr-only"> (done)</span> : null}
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

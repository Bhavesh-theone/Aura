"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";
import { cx } from "@/shared/lib/format";
import { Tip } from "@/shared/ui/primitives";

export const CAP_LABEL: Record<string, string> = {
  classify_document: "Classify document",
  extract_financials: "Extract financials",
  draft_email: "Draft email",
};
export const capLabel = (c: string) => CAP_LABEL[c] ?? c;

export function CopyChip({ value, shown, className }: { value: string; shown: string; className?: string }) {
  const [done, setDone] = useState(false);
  return (
    <Tip label={done ? "Copied" : "Copy full value"}>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          navigator.clipboard
            ?.writeText(value)
            .then(() => {
              setDone(true);
              setTimeout(() => setDone(false), 1200);
            })
            .catch(() => {});
        }}
        className={cx("inline-flex items-center gap-1 rounded-xs font-mono text-[11px] text-fg-2 hover:text-fg", className)}
      >
        {shown}
        {done ? <Check className="h-3 w-3 text-success" /> : <Copy className="h-3 w-3 text-muted" />}
      </button>
    </Tip>
  );
}

/** Horizontal bar with an optional threshold tick. value/threshold are 0..1. */
export function ScoreBar({
  value,
  threshold,
  tone,
  className,
}: {
  value: number;
  threshold?: number;
  tone: "success" | "danger" | "warning" | "accent";
  className?: string;
}) {
  const pct = (n: number) => `${Math.max(0, Math.min(1, n)) * 100}%`;
  const fill = { success: "bg-success", danger: "bg-danger", warning: "bg-warning", accent: "bg-accent" }[tone];
  return (
    <div className={cx("relative h-1.5 rounded-full bg-well", className)} role="img" aria-label={`${Math.round(value * 100)} percent`}>
      <div className={cx("absolute inset-y-0 left-0 rounded-full", fill)} style={{ width: pct(value) }} />
      {threshold !== undefined ? (
        <span aria-hidden className="absolute -top-0.5 h-2.5 w-px bg-fg-2" style={{ left: pct(threshold) }} />
      ) : null}
    </div>
  );
}

"use client";

import { cx, stageLabel } from "@/shared/lib/format";
import { Badge, Card, CardHeader, Dot, type Tone } from "@/shared/ui/primitives";
import { STAGES, isTerminal } from "../types";

export { inputCls, labelCls, selectCls, textareaCls } from "@/shared/ui/primitives";
export { EmptyState, InlineError, Notice, SkeletonRows, Unavailable } from "@/shared/ui/States";

export const CLASS_LABEL: Record<string, string> = {
  DEBT: "Debt",
  EQUITY: "Equity",
  MNA: "M&A",
  HYBRID: "Hybrid",
  JV: "JV",
  LPGP: "LP/GP",
  ALLIANCE: "Alliance",
};

export function stageTone(stage: string, outcome?: string | null): Tone {
  if (isTerminal(stage)) return "danger";
  if (stage === "CLOSED") return outcome && /lost|fail/i.test(outcome) ? "danger" : "success";
  return "accent";
}

/** Status dot + stage name + n/12 — the deal's position at a glance. */
export function StageChip({ stage, outcome, showStep = false }: { stage: string; outcome?: string | null; showStep?: boolean }) {
  const idx = (STAGES as readonly string[]).indexOf(stage);
  const tone = stageTone(stage, outcome);
  return (
    <span className="inline-flex h-5 items-center gap-1.5 whitespace-nowrap text-[12px] text-fg-2">
      <Dot tone={tone} />
      <span className={cx(tone === "danger" && "text-danger")}>{stageLabel(stage)}</span>
      {showStep && idx >= 0 ? <span className="num font-mono text-[11px] text-muted">{idx + 1}/12</span> : null}
    </span>
  );
}

export function ClassChip({ cls }: { cls: string }) {
  return <Badge tone="neutral">{CLASS_LABEL[cls] ?? cls}</Badge>;
}

/** Card with a 40px header — the standard container inside deal tabs. */
export function Section({ title, children, aside, flush }: { title: React.ReactNode; children: React.ReactNode; aside?: React.ReactNode; flush?: boolean }) {
  return (
    <Card>
      <CardHeader title={title} aside={aside} />
      <div className={flush ? "" : "p-4"}>{children}</div>
    </Card>
  );
}

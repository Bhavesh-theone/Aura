"use client";

import { CheckCircle2, ExternalLink, XCircle } from "lucide-react";
import Link from "next/link";
import { cx, humanize, shortAgo } from "@/shared/lib/format";
import { Badge } from "@/shared/ui/primitives";
import { Sheet } from "@/shared/ui/Sheet";
import { InlineError, SkeletonRows, Unavailable } from "@/shared/ui/States";
import { useEvalRun } from "../hooks";
import type { EvalCase } from "../types";
import { capLabel, ScoreBar } from "./shared";
import { fmtMs, OrchestratorBadge } from "./EvalRunsSection";

const HANDLED = new Set(["primary", "errors", "total_latency_ms", "trace_id", "partial", "case_ids"]);

const show = (v: unknown): string => {
  if (v === null || v === undefined) return "—";
  if (v && typeof v === "object" && "confidence_at_least" in v) {
    // calibration: how often the model was right when it was this sure
    const c = v as { confidence_at_least: number; n: number; accuracy: number | null };
    return c.n
      ? `${Math.round((c.accuracy ?? 0) * 100)}% right at confidence ≥ ${c.confidence_at_least} (n=${c.n})`
      : `no answers at confidence ≥ ${c.confidence_at_least}`;
  }
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(3);
  if (typeof v === "string") return v;
  return JSON.stringify(v);
};

function Metric({ k, v }: { k: string; v: unknown }) {
  return (
    <div className="flex items-baseline gap-3 border-b border-line-subtle py-1.5 text-[12.5px] last:border-0">
      <dt className="text-muted">{humanize(k)}</dt>
      <dd className="num ml-auto min-w-0 break-words text-right font-mono text-fg-2">{show(v)}</dd>
    </div>
  );
}

/** One side of expected vs actual. Only keys the golden case expects are compared: extra
 * fields on the actual side (a rationale, say) are context, not a mismatch. */
function Side({ title, data, other, expectedKeys }: { title: string; data: Record<string, unknown>; other: Record<string, unknown>; expectedKeys: Set<string> }) {
  const keys = Object.keys(data ?? {});
  return (
    <div className="min-w-0 flex-1 rounded-sm border border-line-subtle bg-well p-2">
      <p className="mb-1 text-[10.5px] uppercase tracking-[0.06em] text-muted">{title}</p>
      {keys.length === 0 ? <p className="text-[12px] text-muted">empty</p> : null}
      {keys.map((k) => {
        const differs = expectedKeys.has(k) && JSON.stringify(data[k]) !== JSON.stringify(other?.[k]);
        const long = show(data[k]).length > 28;
        return (
          <div key={k} className={cx("rounded-xs px-1 py-0.5 text-[11.5px]", long ? "block" : "flex gap-2", differs && "bg-danger-soft")}>
            <span className="shrink-0 text-muted">{k}</span>
            <span className={cx("min-w-0 break-words", long ? "mt-0.5 block leading-snug" : "ml-auto text-right font-mono", differs ? "text-danger" : "text-fg-2")}>{show(data[k])}</span>
          </div>
        );
      })}
    </div>
  );
}

function Case({ c }: { c: EvalCase }) {
  return (
    <li className={cx("rounded-md border p-3", c.passed ? "border-line-subtle" : "border-danger-border")}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {c.passed ? <CheckCircle2 className="h-4 w-4 text-success" /> : <XCircle className="h-4 w-4 text-danger" />}
        <span className="font-mono text-[12px] text-fg">{c.case_id}</span>
        <span className="num text-[12px] text-fg-2">score {c.score.toFixed(2)}</span>
        {c.confidence !== null ? <span className="num text-[12px] text-muted">conf {c.confidence.toFixed(2)}</span> : null}
        <span className="num text-[12px] text-muted">{fmtMs(c.latency_ms)}</span>
        {c.agent_run_id !== null ? <span className="ml-auto font-mono text-[11px] text-muted">run #{c.agent_run_id}</span> : null}
      </div>
      {c.error ? <p className="mt-2 rounded-xs bg-danger-soft px-2 py-1 font-mono text-[11.5px] text-danger">{c.error}</p> : null}
      <div className="mt-2 flex flex-col gap-2 sm:flex-row">
        <Side title="Expected" data={c.expected} other={c.actual} expectedKeys={new Set(Object.keys(c.expected ?? {}))} />
        <Side title="Actual" data={c.actual} other={c.expected} expectedKeys={new Set(Object.keys(c.expected ?? {}))} />
      </div>
    </li>
  );
}

export function EvalRunSheet({ id, onClose }: { id: number | null; onClose: () => void }) {
  const { data: run, loading, error, unavailable, refresh } = useEvalRun(id);
  const m = run?.metrics ?? {};
  const extras = Object.entries(m).filter(([k]) => !HANDLED.has(k));

  return (
    <Sheet
      open={id !== null}
      onClose={onClose}
      width={720}
      eyebrow={run ? <span className="font-mono">Eval run #{run.id}</span> : undefined}
      title={run ? capLabel(run.capability) : "Eval run"}
      description={run ? `${run.n_cases} cases${run.completed_at ? ` · ${shortAgo(run.completed_at)}` : ""}` : undefined}
    >
      {error ? (
        <InlineError message={error} onRetry={refresh} />
      ) : unavailable ? (
        <Unavailable what="This eval run" />
      ) : loading || !run ? (
        <SkeletonRows rows={6} />
      ) : (
        <div className="space-y-6">
          <div className="flex flex-wrap items-center gap-2">
            <OrchestratorBadge o={run.orchestrator} />
            <Badge tone={run.passed ? "success" : "danger"}>{run.passed ? "passed" : "failed"}</Badge>
            {m.partial ? <Badge tone="warning" title="Does not count for autonomy">spot check</Badge> : null}
            {run.model_id ? <span className="font-mono text-[11px] text-fg-2">{run.model_id}</span> : null}
            {m.trace_id ? (
              <Link href={`/traces/${m.trace_id}`} className="ml-auto inline-flex items-center gap-1 text-[12px] font-medium text-accent hover:underline">
                View trace <ExternalLink className="h-3 w-3" />
              </Link>
            ) : null}
          </div>

          <div>
            <div className="mb-1 flex items-baseline gap-2">
              <span className="num font-serif text-[28px] text-fg">{run.score.toFixed(2)}</span>
              <span className="num text-[13px] text-muted">/ {run.threshold.toFixed(2)} threshold</span>
              {m.primary ? <span className="ml-auto text-[12px] text-muted">{humanize(String(m.primary))}</span> : null}
            </div>
            <ScoreBar value={run.score} threshold={run.threshold} tone={run.passed ? "success" : "danger"} />
          </div>

          <dl>
            <Metric k="errors" v={m.errors ?? 0} />
            <Metric k="total latency" v={fmtMs(m.total_latency_ms)} />
            <Metric k="golden sha" v={run.golden_sha256.slice(0, 12)} />
            {extras.map(([k, v]) => (
              <Metric key={k} k={k} v={v} />
            ))}
            {m.partial && Array.isArray(m.case_ids) ? <Metric k="cases in spot check" v={m.case_ids.join(", ")} /> : null}
          </dl>

          <div>
            <h3 className="mb-2 text-[13px] font-medium text-fg">Cases</h3>
            <ul className="space-y-2">
              {run.cases.map((c) => (
                <Case key={c.case_id} c={c} />
              ))}
            </ul>
          </div>
        </div>
      )}
    </Sheet>
  );
}

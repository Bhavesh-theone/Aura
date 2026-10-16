"use client";

import { useMemo, useState } from "react";
import { cx, shortAgo } from "@/shared/lib/format";
import { Badge, Card, Segmented, Tip } from "@/shared/ui/primitives";
import { EmptyState, InlineError, SkeletonRows } from "@/shared/ui/States";
import { useEvalRuns } from "../hooks";
import type { EvalRun } from "../types";
import { EvalRunSheet } from "./EvalRunSheet";
import { capLabel, ScoreBar } from "./shared";

type Filter = "all" | "classify_document" | "extract_financials" | "draft_email";

export const fmtMs = (ms: number | undefined | null) =>
  ms === undefined || ms === null ? "—" : ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;

export function OrchestratorBadge({ o }: { o: string }) {
  return o === "crew" ? <Badge tone="accent">crew</Badge> : <Badge tone="neutral">stub</Badge>;
}

export function EvalRunsSection() {
  const { data, loading, error, refresh } = useEvalRuns();
  const [filter, setFilter] = useState<Filter>("all");
  const [openId, setOpenId] = useState<number | null>(null);
  const rows = useMemo(() => (filter === "all" ? data : data.filter((r) => r.capability === filter)), [data, filter]);

  return (
    <section aria-labelledby="q-evals">
      <div className="mb-3 flex flex-wrap items-end gap-3">
        <div>
          <h2 id="q-evals" className="font-serif text-[18px] text-fg">Eval runs</h2>
          <p className="mt-0.5 text-[13px] text-muted">Each run replays the golden set against the agent and scores it. Click a run to see every case.</p>
        </div>
        <div className="ml-auto">
          <Segmented<Filter>
            label="Capability"
            value={filter}
            onChange={setFilter}
            options={[
              { value: "all", label: "All" },
              { value: "classify_document", label: "Classify" },
              { value: "extract_financials", label: "Extract" },
              { value: "draft_email", label: "Draft" },
            ]}
          />
        </div>
      </div>
      <Card className="overflow-hidden">
        {error ? (
          <div className="p-4"><InlineError message={error} onRetry={refresh} /></div>
        ) : loading ? (
          <SkeletonRows rows={5} />
        ) : rows.length === 0 ? (
          <EmptyState compact title="No eval runs yet" description="Runs appear here once the golden set has been scored." />
        ) : (
          <div className="scroll overflow-x-auto">
            <table className="w-full min-w-[960px] text-left text-[12.5px]">
              <thead>
                <tr className="border-b border-line-subtle text-[11px] uppercase tracking-[0.06em] text-muted">
                  {["Run", "Capability", "Orchestrator", "Model", "Score / threshold", "Result", "Cases", "Golden set", "Completed", "Latency"].map((h) => (
                    <th key={h} className="whitespace-nowrap px-3 py-2 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <Row key={r.id} r={r} onOpen={() => setOpenId(r.id)} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <EvalRunSheet id={openId} onClose={() => setOpenId(null)} />
    </section>
  );
}

function Row({ r, onOpen }: { r: EvalRun; onOpen: () => void }) {
  const tone = r.passed ? "success" : "danger";
  return (
    <tr
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onOpen())}
      className="cursor-pointer border-b border-line-subtle transition-colors last:border-0 hover:bg-well focus-visible:bg-well focus-visible:outline-none"
    >
      <td className="whitespace-nowrap px-3 py-2.5 font-mono text-[12px] text-fg-2">#{r.id}</td>
      <td className="whitespace-nowrap px-3 py-2.5 text-fg">{capLabel(r.capability)}</td>
      <td className="px-3 py-2.5"><OrchestratorBadge o={r.orchestrator} /></td>
      <td className="max-w-[160px] truncate px-3 py-2.5 font-mono text-[11px] text-fg-2" title={r.model_id ?? undefined}>{r.model_id ?? "—"}</td>
      <td className="px-3 py-2.5">
        <div className="flex items-center gap-2">
          <ScoreBar value={r.score} threshold={r.threshold} tone={tone} className="w-24" />
          <span className="num whitespace-nowrap text-fg">
            {r.score.toFixed(2)} <span className="text-muted">/ {r.threshold.toFixed(2)}</span>
          </span>
        </div>
      </td>
      <td className="px-3 py-2.5">
        <div className="flex items-center gap-1.5">
          <Badge tone={tone}>{r.passed ? "passed" : "failed"}</Badge>
          {r.metrics?.partial ? (
            <Tip label="Spot check over part of the golden set. Does not count for autonomy.">
              <span><Badge tone="warning">spot check</Badge></span>
            </Tip>
          ) : null}
        </div>
      </td>
      <td className="num px-3 py-2.5 text-fg-2">{r.n_cases}</td>
      <td className="px-3 py-2.5">
        <span className="font-mono text-[11px] text-fg-2" title={r.golden_sha256}>{r.golden_sha256.slice(0, 8)}</span>
      </td>
      <td className="whitespace-nowrap px-3 py-2.5 text-fg-2">{r.completed_at ? shortAgo(r.completed_at) : <span className="text-muted">running</span>}</td>
      <td className={cx("num whitespace-nowrap px-3 py-2.5 text-fg-2")}>{fmtMs(r.metrics?.total_latency_ms)}</td>
    </tr>
  );
}

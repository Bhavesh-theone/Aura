"use client";

import { CheckCircle2, CircleDashed, XCircle } from "lucide-react";
import Link from "next/link";
import { STAGES } from "@/features/deals/types";
import { anyEvent } from "@/shared/api/events";
import { cx, formatDateTime, humanize, stageLabel } from "@/shared/lib/format";
import { useApi } from "@/shared/lib/useApi";
import { PageHeader } from "@/shared/ui/PageHeader";
import { Badge, Card, CardHeader, Tip } from "@/shared/ui/primitives";
import { EmptyState, InlineError, Skel, Unavailable } from "@/shared/ui/States";
import { getMetrics, type EvaluationMetrics, type Metrics, type ReliabilityMetrics, type SecurityMetrics, type StageDwell, type SuccessMetrics } from "../api";

/* --------------------------------- helpers -------------------------------- */

export function formatHours(h: number | null | undefined): string {
  if (h == null || !Number.isFinite(h)) return "—";
  if (h < 1) return `${Math.max(1, Math.round(h * 60))} min`;
  if (h < 48) return `${h < 10 ? h.toFixed(1) : Math.round(h)} h`;
  const d = h / 24;
  return `${d < 10 ? d.toFixed(1) : Math.round(d)} d`;
}

type Status = "pass" | "fail" | "none";

type MetricCard = {
  key: keyof SuccessMetrics;
  label: string;
  value: string;
  target: string;
  status: Status;
  caption: string;
  source: string;
};

function cards(s: SuccessMetrics): MetricCard[] {
  const pct = (v: number | null) => (v == null ? "—" : `${Math.round(v * 10) / 10}%`);
  const at100 = (v: number | null): Status => (v == null ? "none" : v >= 100 ? "pass" : "fail");
  const zero = (v: number | null): Status => (v == null ? "none" : v === 0 ? "pass" : "fail");
  return [
    {
      key: "guarded_forward_transitions_pct",
      label: "Stage moves with a guard evaluation",
      value: pct(s.guarded_forward_transitions_pct),
      target: "100%",
      status: at100(s.guarded_forward_transitions_pct),
      caption: "Forward transitions that left a recorded guard evaluation behind.",
      source: "deal_stage_history ⋈ stage_guard_evaluation",
    },
    {
      key: "runs_traceable_pct",
      label: "Model runs traceable to their prompt",
      value: pct(s.runs_traceable_pct),
      target: "100%",
      status: at100(s.runs_traceable_pct),
      caption: "Agent runs whose stored messages re-hash to the recorded prompt hash.",
      source: "agent_run",
    },
    {
      key: "audit_chain_ok",
      label: "Audit chain verification",
      value: s.audit_chain_ok == null ? "—" : s.audit_chain_ok ? "Intact" : "Broken",
      target: "100% pass",
      status: s.audit_chain_ok == null ? "none" : s.audit_chain_ok ? "pass" : "fail",
      caption: "Every audit row’s SHA-256 matches its predecessor.",
      source: "verify-audit",
    },
    {
      key: "handoff_rejections_422",
      label: "Incomplete handoffs that reached a human",
      value: s.handoff_rejections_422 == null ? "—" : "0",
      target: "0",
      status: s.handoff_rejections_422 == null ? "none" : "pass",
      caption:
        s.handoff_rejections_422 == null
          ? "Handoffs missing required parts are rejected at the API."
          : `${s.handoff_rejections_422} incomplete handoff${s.handoff_rejections_422 === 1 ? " was" : "s were"} rejected (422) before reaching anyone.`,
      source: "API 422 log",
    },
    {
      key: "outbound_executed",
      label: "Outbound actions executed without approval",
      value: s.outbound_executed == null ? "—" : String(s.outbound_executed),
      target: "0",
      status: zero(s.outbound_executed),
      caption: "Emails or other outbound actions carried out without a human approval on record.",
      source: "task / handoff / audit",
    },
    {
      key: "deals_closed_end_to_end",
      label: "Real deals run end to end",
      value: s.deals_closed_end_to_end == null ? "—" : String(s.deals_closed_end_to_end),
      target: "≥ 1",
      status: s.deals_closed_end_to_end == null ? "none" : s.deals_closed_end_to_end >= 1 ? "pass" : "fail",
      caption: "Deals that went from Originated to Closed through the stage machine.",
      source: "deal_stage_history",
    },
  ];
}

const STATUS_UI: Record<Status, { tone: "success" | "danger" | "neutral"; label: string; icon: React.ReactNode }> = {
  pass: { tone: "success", label: "On target", icon: <CheckCircle2 className="h-3 w-3" /> },
  fail: { tone: "danger", label: "Below target", icon: <XCircle className="h-3 w-3" /> },
  none: { tone: "neutral", label: "No data", icon: <CircleDashed className="h-3 w-3" /> },
};

/* --------------------------------- pieces --------------------------------- */

function SuccessCard({ c }: { c: MetricCard }) {
  const st = STATUS_UI[c.status];
  return (
    <div className={cx("flex flex-col rounded-md border bg-surface p-4 shadow-card", c.status === "fail" ? "border-danger-border" : "border-line")}>
      <div className="flex items-start gap-2">
        <span className="min-h-[32px] text-[12px] leading-snug text-muted">{c.label}</span>
        <Badge tone={st.tone} className="ml-auto">{st.icon} {st.label}</Badge>
      </div>
      <div className="mt-3 flex items-baseline gap-2">
        <span className={cx("num font-serif text-[36px] leading-none", c.status === "fail" ? "text-danger" : "text-fg")}>{c.value}</span>
        <span className="text-[12px] text-muted">target {c.target}</span>
      </div>
      <p className="mt-3 text-[12px] leading-relaxed text-fg-2">{c.caption}</p>
      <p className="mt-auto pt-3 font-mono text-[11px] text-muted">{c.source}</p>
    </div>
  );
}

function DwellTable({ rows }: { rows: StageDwell[] }) {
  const byStage = new Map(rows.map((r) => [r.stage, r]));
  const ordered = [
    ...(STAGES as readonly string[]).map((s) => byStage.get(s) ?? { stage: s, n: 0, median_hours: 0, p90_hours: 0 }),
    ...rows.filter((r) => !(STAGES as readonly string[]).includes(r.stage)),
  ];
  const max = Math.max(1, ...ordered.map((r) => r.p90_hours ?? r.median_hours ?? 0));
  const measured = ordered.filter((r) => r.n > 0).length;
  return (
    <Card>
      <CardHeader
        title="Time in stage"
        aside={
          <span className="flex items-center gap-3 text-[12px] text-muted">
            <span className="flex items-center gap-1.5"><span className="h-2 w-3 rounded-[2px] bg-accent" /> median</span>
            <span className="flex items-center gap-1.5"><span className="h-2 w-3 rounded-[2px] bg-accent-border" /> p90</span>
            <span>{measured} of {ordered.length} stages measured</span>
          </span>
        }
      />
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="h-8 border-b border-line-subtle text-[11px] text-muted">
            <th className="w-10 px-4 font-medium">#</th>
            <th className="w-44 px-2 font-medium">Stage</th>
            <th className="w-14 px-2 text-right font-medium">Exits</th>
            <th className="px-4 font-medium">Distribution</th>
            <th className="w-20 px-2 text-right font-medium">Median</th>
            <th className="w-20 px-4 text-right font-medium">p90</th>
          </tr>
        </thead>
        <tbody>
          {ordered.map((r, i) => {
            const med = r.median_hours ?? 0;
            const p90 = r.p90_hours ?? med;
            return (
              <tr key={r.stage} className="h-10 border-b border-line-subtle text-[13px] last:border-0">
                <td className="px-4 font-mono text-[11px] text-muted">{String(i + 1).padStart(2, "0")}</td>
                <td className={cx("px-2", r.n ? "text-fg" : "text-muted")}>{stageLabel(r.stage)}</td>
                <td className="num px-2 text-right font-mono text-[12px] text-fg-2">{r.n || "—"}</td>
                <td className="px-4">
                  {r.n ? (
                    <Tip label={`Median ${formatHours(r.median_hours)} · p90 ${formatHours(r.p90_hours)} · ${r.n} exit${r.n === 1 ? "" : "s"}`}>
                      <span tabIndex={0} className="relative block h-2.5 w-full rounded-full bg-control-active outline-none focus-visible:ring-2 focus-visible:ring-accent/50">
                        <span className="absolute inset-y-0 left-0 rounded-full bg-accent-border" style={{ width: `${(p90 / max) * 100}%` }} />
                        <span className="absolute inset-y-0 left-0 rounded-full bg-accent" style={{ width: `${(med / max) * 100}%` }} />
                      </span>
                    </Tip>
                  ) : (
                    <span className="block h-px w-full bg-line-subtle" />
                  )}
                </td>
                <td className="num px-2 text-right font-mono text-[12px] text-fg">{r.n ? formatHours(r.median_hours) : "—"}</td>
                <td className="num px-4 text-right font-mono text-[12px] text-fg-2">{r.n ? formatHours(r.p90_hours) : "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="border-t border-line-subtle px-4 py-2.5 text-[12px] text-muted">
        Computed only from the append-only stage history — the time between entering a stage and leaving it.
      </p>
    </Card>
  );
}

function StatTile({ label, value, caption, danger }: { label: string; value: number; caption: string; danger?: boolean }) {
  return (
    <div className={cx("flex flex-col rounded-md border bg-surface p-4 shadow-card", danger ? "border-danger-border" : "border-line")}>
      <span className="text-[12px] leading-snug text-muted">{label}</span>
      <span className={cx("num mt-2 font-serif text-[32px] leading-none", danger ? "text-danger" : "text-fg")}>{value}</span>
      <p className="mt-3 text-[12px] leading-relaxed text-fg-2">{caption}</p>
    </div>
  );
}

const sectionLink = "text-[12px] font-medium text-accent hover:underline";

function ReliabilitySection({ r }: { r: ReliabilityMetrics }) {
  return (
    <section aria-label="Reliability">
      <div className="mb-3 flex items-center gap-3">
        <h2 className="text-[12px] font-medium text-fg-2">Reliability</h2>
        {r.dead_lettered_segments > 0 ? <Link href="/jobs" className={sectionLink}>Review dead letters</Link> : null}
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-5">
        <StatTile label="Dead-lettered steps" value={r.dead_lettered_segments} danger={r.dead_lettered_segments > 0} caption="Agent steps that ran out of retries or lost their worker, all time. Open ones wait on Agent jobs." />
        <StatTile label="Retried" value={r.retried_segments} caption="Steps retried after a failure, automatically or by hand." />
        <StatTile label="Recovered" value={r.recovered_segments} caption="Steps picked up again after a worker stalled mid-run." />
        <StatTile label="Fallback runs" value={r.fallback_runs} caption="Runs that used the stub because the local model was down." />
        <StatTile label="Budget deferrals" value={r.budget_deferrals} caption="Steps pushed to later because the daily model-call budget was reached." />
      </div>
    </section>
  );
}

const LEVEL_LABEL: Record<number, string> = { 0: "0 · Off", 1: "1 · Supervised", 2: "2 · Autonomous" };

function EvaluationSection({ e }: { e: EvaluationMetrics }) {
  const caps = Array.from(new Set([...e.latest_runs.map((x) => x.capability), ...e.override_rate.map((x) => x.capability), ...e.autonomy.map((x) => x.capability)]));
  return (
    <section aria-label="Evaluation">
      <div className="mb-3 flex items-center gap-3">
        <h2 className="text-[12px] font-medium text-fg-2">Evaluation</h2>
        <Link href="/quality" className={sectionLink}>Open Agent quality</Link>
      </div>
      <Card>
        {caps.length === 0 ? (
          <EmptyState compact title="No evaluation data yet" description="Capabilities appear here once they have an eval run or a decision." />
        ) : (
          <table className="w-full border-collapse text-left">
            <thead>
              <tr className="h-8 border-b border-line-subtle text-[11px] text-muted">
                <th className="px-4 font-medium">Capability</th>
                <th className="px-2 font-medium">Latest eval</th>
                <th className="px-2 font-medium">Override rate</th>
                <th className="px-4 font-medium">Autonomy</th>
              </tr>
            </thead>
            <tbody>
              {caps.map((c) => {
                const run = e.latest_runs.find((x) => x.capability === c);
                const or = e.override_rate.find((x) => x.capability === c);
                const au = e.autonomy.find((x) => x.capability === c);
                return (
                  <tr key={c} className="border-b border-line-subtle align-top text-[13px] last:border-0">
                    <td className="px-4 py-2.5 text-fg">{humanize(c)}</td>
                    <td className="px-2 py-2.5">
                      {run ? (
                        <div className="flex flex-col gap-1">
                          <span className="flex items-center gap-2">
                            <Badge tone={run.passed ? "success" : "danger"}>{run.passed ? "Pass" : "Fail"}</Badge>
                            <span className="num font-mono text-[12px] text-fg-2">{run.score.toFixed(2)} / {run.threshold.toFixed(2)}</span>
                          </span>
                          <span className="text-[11px] text-muted">{run.orchestrator} · {run.model_id} · {formatDateTime(run.completed_at)}</span>
                        </div>
                      ) : (
                        <span className="text-muted">No eval run yet</span>
                      )}
                    </td>
                    <td className="px-2 py-2.5">
                      {or && or.rate != null ? (
                        <span className="num font-mono text-[12px] text-fg-2">
                          {Math.round(or.rate * 1000) / 10}% <span className="text-muted">({or.overrides}/{or.decisions}, {or.window_days} d)</span>
                        </span>
                      ) : (
                        <span className="text-muted">No decisions</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5">
                      {au ? (
                        <div className="flex flex-col gap-1">
                          <Badge tone={au.level === 0 ? "danger" : au.level === 2 ? "accent" : "neutral"}>{LEVEL_LABEL[au.level] ?? `Level ${au.level}`}</Badge>
                          {au.reason ? <span className="max-w-xs text-[11px] text-warning">Demoted: {au.reason}</span> : null}
                        </div>
                      ) : (
                        <span className="text-muted">—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Card>
    </section>
  );
}

function SecuritySection({ s }: { s: SecurityMetrics }) {
  return (
    <section aria-label="Security">
      <div className="mb-3 flex items-center gap-3">
        <h2 className="text-[12px] font-medium text-fg-2">Security</h2>
        {s.untrusted_content_handoffs > 0 ? <Link href="/decisions" className={sectionLink}>Review untrusted-content decisions</Link> : null}
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        <StatTile
          label="Injection suspected"
          value={s.injection_suspected}
          danger={s.injection_suspected > 0}
          caption={s.injection_suspected === 0 ? "No document or tool text looked like a prompt injection." : "Times text inside a document or tool result looked like an instruction to the agent."}
        />
        <StatTile label="Untrusted-content handoffs" value={s.untrusted_content_handoffs} caption="Decisions forced onto a person because the injection screen fired." />
      </div>
    </section>
  );
}

function MetricsSkeleton() {
  return (
    <div className="space-y-6 px-8" aria-busy="true" aria-label="Loading metrics">
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="rounded-md border border-line bg-surface p-4 shadow-card">
            <Skel className="h-3 w-40" />
            <Skel className="mt-4 h-8 w-20" />
            <Skel className="mt-4 h-2.5 w-full" />
          </div>
        ))}
      </div>
      <Skel className="h-80 w-full rounded-md" />
    </div>
  );
}

/* ---------------------------------- view ---------------------------------- */

export function MetricsView() {
  const m = useApi<Metrics | null>(getMetrics, null, [], { live: anyEvent, pollMs: 60000 });
  const cs = m.data ? cards(m.data.success) : [];
  const onTarget = cs.filter((c) => c.status === "pass").length;

  return (
    <div className="flex-1 pb-14">
      <PageHeader
        title="Metrics"
        description="The six v1 success measures and how long deals sit in each stage. Every number comes from the records, not from estimates."
        meta={m.data ? `${onTarget} of ${cs.length} on target` : undefined}
      />
      {m.unavailable ? (
        <div className="px-8"><Unavailable what="Metrics" /></div>
      ) : m.error ? (
        <div className="px-8"><InlineError message={m.error} onRetry={m.refresh} /></div>
      ) : m.loading || !m.data ? (
        <MetricsSkeleton />
      ) : (
        <div className="space-y-6 px-8">
          <section aria-label="Success metrics">
            <h2 className="mb-3 text-[12px] font-medium text-fg-2">Success metrics · PRD §11</h2>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
              {cs.map((c) => (
                <SuccessCard key={c.key} c={c} />
              ))}
            </div>
          </section>
          <section aria-label="Stage dwell">
            <h2 className="mb-3 text-[12px] font-medium text-fg-2">Cycle time</h2>
            {m.data.stage_dwell.length === 0 ? (
              <Card>
                <EmptyState compact title="No stage moves yet" description="Dwell times appear once deals have left at least one stage." />
              </Card>
            ) : (
              <DwellTable rows={m.data.stage_dwell} />
            )}
          </section>
          {m.data.reliability ? <ReliabilitySection r={m.data.reliability} /> : null}
          {m.data.evaluation ? <EvaluationSection e={m.data.evaluation} /> : null}
          {m.data.security ? <SecuritySection s={m.data.security} /> : null}
        </div>
      )}
    </div>
  );
}

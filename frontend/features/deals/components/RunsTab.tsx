"use client";

import { Bot, ChevronRight, Copy, User, Wrench } from "lucide-react";
import { useState } from "react";
import { dealEvents } from "@/shared/api/events";
import { cx, formatDateTime, humanize } from "@/shared/lib/format";
import { useApi } from "@/shared/lib/useApi";
import { Badge, IconButton, Tip } from "@/shared/ui/primitives";
import { Sheet } from "@/shared/ui/Sheet";
import { useToast } from "@/shared/ui/toast";
import { getAgentRun, listAgentRuns } from "../api";
import type { AgentRun, AgentRunDetail, AgentRunMessage } from "../types";
import { ConfidenceCells } from "./ExtractionsTab";
import { EmptyState, InlineError, SkeletonRows, Unavailable } from "./ui";

const preCls = "scroll overflow-x-auto whitespace-pre-wrap break-words rounded-md border border-line bg-well p-3 font-mono text-[12px] leading-relaxed text-fg-2";

function asText(v: unknown): string {
  if (typeof v === "string") return v;
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}

const roleIcon = (role: string) =>
  role === "user" ? <User className="h-3.5 w-3.5" /> : role === "tool" ? <Wrench className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />;

function Message({ m, i }: { m: AgentRunMessage; i: number }) {
  const text = asText(m.content);
  const long = text.length > 1400;
  const [more, setMore] = useState(!long);
  return (
    <li className="rounded-md border border-line bg-surface">
      <div className="flex h-8 items-center gap-2 border-b border-line-subtle px-3 text-[12px]">
        <span className="text-muted">{roleIcon(m.role)}</span>
        <span className="font-medium capitalize text-fg">{m.role}</span>
        <span className="num ml-auto font-mono text-[11px] text-muted">#{i + 1} · {text.length.toLocaleString("en-IN")} chars</span>
      </div>
      <pre className="scroll max-h-[420px] overflow-auto whitespace-pre-wrap break-words px-3 py-2.5 font-mono text-[12px] leading-relaxed text-fg-2">
        {more ? text : `${text.slice(0, 1400)}…`}
      </pre>
      {long ? (
        <button onClick={() => setMore(!more)} className="w-full border-t border-line-subtle py-1.5 text-[12px] text-fg-2 hover:bg-control-hover hover:text-fg">
          {more ? "Show less" : "Show the full message"}
        </button>
      ) : null}
    </li>
  );
}

/** Drill-down for one model call: the exact messages sent and what came back (F8.A). */
export function RunDrawer({ runId, onClose }: { runId: number | null; onClose: () => void }) {
  const toast = useToast();
  const run = useApi<AgentRunDetail | null>(runId !== null ? () => getAgentRun(runId) : null, null, [runId]);
  const r = run.data;
  const messages = (r?.input_digest?.messages ?? []) as AgentRunMessage[];
  const otherDigest = r ? Object.fromEntries(Object.entries(r.input_digest ?? {}).filter(([k]) => k !== "messages")) : {};

  const facts: [string, React.ReactNode][] = r
    ? [
        ["Model", <span key="m" className="font-mono">{r.model_id}{r.model_version ? ` · ${r.model_version}` : ""}</span>],
        ["Archetype", r.archetype ? humanize(r.archetype) : "—"],
        ["Template", <span key="t" className="font-mono">{r.prompt_template_id}</span>],
        ["Latency", r.latency_ms != null ? `${(r.latency_ms / 1000).toFixed(2)} s` : "—"],
        ["Tokens in / out", <span key="k" className="num font-mono">{r.tokens_in ?? "—"} / {r.tokens_out ?? "—"}</span>],
        ["Cost", r.cost_inr != null ? `₹${r.cost_inr.toFixed(2)} · local model` : "—"],
        ["Started", <span key="s" className="num font-mono">{formatDateTime(r.started_at)}</span>],
        ["Job", r.job_id ? <span key="j" className="font-mono">JOB-{r.job_id}</span> : "—"],
      ]
    : [];

  return (
    <Sheet
      open={runId !== null}
      onClose={onClose}
      width={760}
      eyebrow={<span className="inline-flex items-center gap-1.5"><Bot className="h-3.5 w-3.5" /> Model run lineage</span>}
      title={r ? `Run #${r.id}` : runId ? `Run #${runId}` : "Run"}
      description="The exact prompt this model saw and what it returned. The hash ties this record to the prompt."
    >
      {run.unavailable ? (
        <Unavailable what="Run detail" />
      ) : run.error ? (
        <InlineError message={run.error} onRetry={run.refresh} />
      ) : !r ? (
        <div className="space-y-3" aria-busy="true">
          <SkeletonRows rows={4} />
        </div>
      ) : (
        <div className="space-y-7">
          <div className="rounded-md border border-line bg-surface p-4">
            <div className="flex items-center gap-2">
              <span className="text-[11px] text-muted">Prompt hash</span>
              <code className="min-w-0 flex-1 truncate font-mono text-[12px] text-fg">{r.prompt_hash}</code>
              <Tip label="Copy hash">
                <IconButton size="sm" label="Copy prompt hash" onClick={() => navigator.clipboard?.writeText(r.prompt_hash).then(() => toast("Prompt hash copied", "info"))}>
                  <Copy className="h-3 w-3" />
                </IconButton>
              </Tip>
            </div>
            <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2.5 border-t border-line-subtle pt-3 text-[13px] sm:grid-cols-4">
              {facts.map(([k, v]) => (
                <div key={k} className="min-w-0">
                  <dt className="text-[11px] text-muted">{k}</dt>
                  <dd className="mt-0.5 truncate text-fg">{v}</dd>
                </div>
              ))}
            </dl>
            {r.confidence != null ? (
              <div className="mt-3 flex items-center gap-2 border-t border-line-subtle pt-3 text-[12px] text-muted">
                Confidence <ConfidenceCells value={r.confidence} />
              </div>
            ) : null}
          </div>

          <section>
            <h3 className="mb-2.5 flex items-center gap-2 text-[12px] font-medium text-fg-2">
              Prompt <Badge>{messages.length} message{messages.length === 1 ? "" : "s"}</Badge>
            </h3>
            {messages.length ? (
              <ol className="space-y-2">
                {messages.map((m, i) => (
                  <Message key={i} m={m} i={i} />
                ))}
              </ol>
            ) : (
              <p className="text-[13px] text-muted">This run recorded no message list.</p>
            )}
            {Object.keys(otherDigest).length ? <pre className={cx(preCls, "mt-2")}>{asText(otherDigest)}</pre> : null}
          </section>

          <section>
            <h3 className="mb-2.5 text-[12px] font-medium text-fg-2">Output</h3>
            {r.output == null ? <p className="text-[13px] text-muted">No output recorded.</p> : <pre className={preCls}>{asText(r.output)}</pre>}
          </section>
        </div>
      )}
    </Sheet>
  );
}

export function RunsTab({ dealId }: { dealId: number }) {
  const runs = useApi<AgentRun[]>(() => listAgentRuns(dealId), [], [dealId], { live: dealEvents(dealId, ["job"]) });
  const [openId, setOpenId] = useState<number | null>(null);

  if (runs.unavailable) return <Unavailable what="Agent run lineage" />;
  if (runs.loading)
    return (
      <div className="rounded-md border border-line bg-surface">
        <SkeletonRows rows={4} />
      </div>
    );
  if (runs.error) return <InlineError message={runs.error} onRetry={runs.refresh} />;
  if (runs.data.length === 0)
    return (
      <div className="rounded-md border border-line bg-surface">
        <EmptyState compact title="No agent runs on this deal" description="Every local model call is recorded here with its exact prompt and output." />
      </div>
    );
  return (
    <>
      <div className="overflow-x-auto rounded-md border border-line bg-surface shadow-card">
        <table className="w-full border-collapse text-left">
          <thead>
            <tr className="h-9 border-b border-line text-[12px] text-muted">
              {["Started", "Model", "Template", "Prompt hash", "Latency", "Tokens", "Confidence", ""].map((h, i) => (
                <th key={i} className={cx("px-3 font-medium first:pl-4", i >= 4 && i < 7 && "text-right")}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {runs.data.map((r) => (
              <tr
                key={r.id}
                tabIndex={0}
                onClick={() => setOpenId(r.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    setOpenId(r.id);
                  }
                }}
                aria-label={`Open run ${r.id}`}
                className="group h-10 cursor-pointer border-b border-line-subtle text-[12px] outline-none last:border-0 hover:bg-well focus-visible:bg-well focus-visible:shadow-[inset_2px_0_0_var(--accent)]"
              >
                <td className="num whitespace-nowrap px-3 pl-4 font-mono text-muted">{formatDateTime(r.started_at)}</td>
                <td className="px-3 font-mono text-fg">{r.model_id}</td>
                <td className="px-3 text-fg-2">{r.prompt_template_id}</td>
                <td className="px-3 font-mono text-muted" title={r.prompt_hash}>{r.prompt_hash?.slice(0, 10)}</td>
                <td className="num px-3 text-right font-mono text-fg-2">{r.latency_ms != null ? `${(r.latency_ms / 1000).toFixed(1)}s` : "—"}</td>
                <td className="num whitespace-nowrap px-3 text-right font-mono text-fg-2">{r.tokens_in ?? "—"} / {r.tokens_out ?? "—"}</td>
                <td className="num px-3 text-right font-mono text-fg">{r.confidence != null ? r.confidence.toFixed(2) : "—"}</td>
                <td className="w-8 pr-3 text-muted"><ChevronRight className="h-3.5 w-3.5 opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100" /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <RunDrawer runId={openId} onClose={() => setOpenId(null)} />
    </>
  );
}

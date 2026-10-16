"use client";

import { Check, ChevronRight, Copy } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { cx, formatDateTime, parseApiDate } from "@/shared/lib/format";
import { useApi } from "@/shared/lib/useApi";
import { Badge, IconButton } from "@/shared/ui/primitives";
import { traceCrumbs, useCrumbs } from "@/shared/ui/shell/crumbs";
import { EmptyState, InlineError, Skel } from "@/shared/ui/States";
import { getTrace } from "../api";
import type { Span, TraceResponse } from "../types";

type Row = { span: Span; depth: number; startMs: number; endMs: number; running: boolean };

const fmtDur = (ms: number) =>
  ms < 1 ? "<1 ms" : ms < 1000 ? `${Math.round(ms)} ms` : ms < 60000 ? `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)} s` : `${(ms / 60000).toFixed(1)} min`;
const num = (v: unknown) =>
  typeof v === "number" ? v : typeof v === "string" && v !== "" && !Number.isNaN(Number(v)) ? Number(v) : null;
const str = (v: unknown) => (typeof v === "string" ? v : null);

function buildRows(spans: Span[], now: number) {
  const byParent = new Map<string | null, Span[]>();
  const ids = new Set(spans.map((s) => s.span_id));
  for (const s of spans) {
    const p = s.parent_span_id && ids.has(s.parent_span_id) ? s.parent_span_id : null;
    byParent.set(p, [...(byParent.get(p) ?? []), s]);
  }
  const rows: Row[] = [];
  const walk = (parent: string | null, depth: number) => {
    const kids = [...(byParent.get(parent) ?? [])].sort(
      (a, b) => parseApiDate(a.start).getTime() - parseApiDate(b.start).getTime(),
    );
    for (const span of kids) {
      const startMs = parseApiDate(span.start).getTime();
      const running = span.end === null;
      const endMs = running ? Math.max(now, startMs) : parseApiDate(span.end as string).getTime();
      rows.push({ span, depth, startMs, endMs, running });
      walk(span.span_id, depth + 1);
    }
  };
  walk(null, 0);
  return rows;
}

function niceTicks(total: number) {
  const steps = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 30000, 60000, 120000, 300000, 600000];
  const step = steps.find((s) => total / s <= 6) ?? 600000;
  const out: number[] = [];
  for (let t = 0; t <= total; t += step) out.push(t);
  return out;
}

export function TraceView({ traceId }: { traceId: string }) {
  useCrumbs(traceCrumbs(traceId));
  const { data, loading, error, unavailable, refresh } = useApi<TraceResponse | null>(() => getTrace(traceId), null, [traceId]);
  const [now, setNow] = useState(() => Date.now());
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [copied, setCopied] = useState(false);
  const [focus, setFocus] = useState<string | null>(null);
  const focusEl = useRef<HTMLLIElement | null>(null);

  const spans = useMemo(() => data?.spans ?? [], [data]);
  const anyRunning = spans.some((s) => s.end === null);
  useEffect(() => {
    if (!anyRunning) return;
    const t = setInterval(() => setNow(Date.now()), 500);
    const r = setInterval(refresh, 5000);
    return () => {
      clearInterval(t);
      clearInterval(r);
    };
  }, [anyRunning, refresh]);

  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("span");
    if (id) {
      setFocus(id);
      setOpen((o) => new Set(o).add(id));
    }
  }, []);
  useEffect(() => {
    if (focus && spans.length) focusEl.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [focus, spans.length]);

  const rows = useMemo(() => buildRows(spans, now), [spans, now]);
  const t0 = rows.length ? Math.min(...rows.map((r) => r.startMs)) : 0;
  const tEnd = rows.length ? Math.max(...rows.map((r) => r.endMs)) : 0;
  const total = Math.max(tEnd - t0, 1);

  const stats = useMemo(() => {
    let tin = 0;
    let tout = 0;
    const models = new Set<string>();
    let jobId: number | null = null;
    for (const s of spans) {
      tin += num(s.attributes["gen_ai.usage.input_tokens"]) ?? 0;
      tout += num(s.attributes["gen_ai.usage.output_tokens"]) ?? 0;
      const m = str(s.attributes["gen_ai.request.model"]);
      if (m) models.add(m);
      const j = num(s.attributes["aura.job_id"]);
      if (j !== null && jobId === null) jobId = j;
    }
    return { tokens: tin + tout, tin, tout, models: [...models], jobId };
  }, [spans]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(traceId);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  };
  const toggle = (id: string) =>
    setOpen((o) => {
      const n = new Set(o);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  return (
    <div className="a-fade mx-auto max-w-[1100px] px-8 py-8">
      <div className="flex items-center gap-2">
        <h1 className="font-serif text-[24px] text-fg">Trace</h1>
        <code className="rounded-sm border border-line bg-well px-1.5 py-0.5 font-mono text-[12px] text-fg-2">{traceId}</code>
        <IconButton label={copied ? "Copied" : "Copy trace id"} size="sm" onClick={copy}>
          {copied ? <Check className="h-3.5 w-3.5 text-success" /> : <Copy className="h-3.5 w-3.5" />}
        </IconButton>
      </div>

      {error ? (
        <div className="mt-6">
          <InlineError message={error} onRetry={refresh} />
        </div>
      ) : unavailable || (!loading && spans.length === 0) ? (
        <EmptyState
          title="Trace not found"
          description="This trace doesn’t exist, or it isn’t visible to you (deal walls apply to traces too)."
          action={
            <Link href="/jobs" className="text-[13px] text-accent hover:underline">
              Back to agent jobs
            </Link>
          }
        />
      ) : loading ? (
        <div className="mt-6 space-y-2">
          {[0, 1, 2, 3, 4].map((i) => (
            <Skel key={i} className="h-7 w-full" />
          ))}
        </div>
      ) : (
        <>
          <dl className="mt-4 flex flex-wrap items-center gap-x-8 gap-y-2 text-[12px]">
            <Stat k="Duration" v={fmtDur(total)} />
            <Stat k="Spans" v={String(spans.length)} />
            <Stat
              k="Tokens"
              v={stats.tokens ? `${stats.tokens.toLocaleString()} (${stats.tin.toLocaleString()} in / ${stats.tout.toLocaleString()} out)` : "—"}
            />
            <Stat k="Started" v={formatDateTime(new Date(t0).toISOString())} />
            {stats.models.length ? (
              <div className="flex items-center gap-1.5">
                <dt className="text-muted">Models</dt>
                {stats.models.map((m) => (
                  <Badge key={m} tone="accent" mono>
                    {m}
                  </Badge>
                ))}
              </div>
            ) : null}
            {stats.jobId !== null ? (
              <Link href={`/jobs?job=${stats.jobId}`} className="font-medium text-accent hover:underline">
                JOB-{stats.jobId} →
              </Link>
            ) : null}
          </dl>

          <div className="mt-6 overflow-hidden rounded-md border border-line bg-surface">
            <div className="flex border-b border-line bg-well text-[11px] text-muted">
              <div className="w-[300px] shrink-0 px-3 py-1.5">Span</div>
              <div className="relative h-7 min-w-0 flex-1">
                {niceTicks(total).map((t) => (
                  <span
                    key={t}
                    className="num absolute top-1.5 -translate-x-1/2 whitespace-nowrap font-mono first:translate-x-0 last:-translate-x-full"
                    style={{ left: `${(t / total) * 100}%` }}
                  >
                    {t === 0 ? "0" : fmtDur(t)}
                  </span>
                ))}
              </div>
              <div className="w-[76px] shrink-0 px-3 py-1.5 text-right">Time</div>
            </div>
            <ul>
              {rows.map((r) => {
                const { span } = r;
                const isOpen = open.has(span.span_id);
                const dur = r.endMs - r.startMs;
                const left = ((r.startMs - t0) / total) * 100;
                const model = str(span.attributes["gen_ai.request.model"]);
                const tin = num(span.attributes["gen_ai.usage.input_tokens"]);
                const tout = num(span.attributes["gen_ai.usage.output_tokens"]);
                const bad = span.status === "error";
                const isFocus = focus === span.span_id;
                return (
                  <li
                    key={span.span_id}
                    ref={isFocus ? focusEl : undefined}
                    className={cx("border-b border-line-subtle last:border-0", isFocus && "bg-accent-soft")}
                  >
                    <button
                      onClick={() => toggle(span.span_id)}
                      aria-expanded={isOpen}
                      className="flex w-full items-center text-left hover:bg-well"
                    >
                      <div
                        className="flex w-[300px] shrink-0 items-center gap-1 py-2 pr-3"
                        style={{ paddingLeft: 12 + r.depth * 16 }}
                      >
                        <ChevronRight className={cx("h-3 w-3 shrink-0 text-muted transition-transform", isOpen && "rotate-90")} />
                        <span className="truncate font-mono text-[12px] text-fg">{span.name}</span>
                        <Badge tone={bad ? "danger" : "success"} className="ml-auto">
                          {bad ? "error" : span.status || "ok"}
                        </Badge>
                      </div>
                      <div className="relative h-7 min-w-0 flex-1">
                        <div
                          className={cx(
                            "absolute top-1/2 h-3 -translate-y-1/2 rounded-xs",
                            bad ? "bg-danger" : span.name === "llm.call" ? "bg-accent" : "bg-info",
                            r.running && "a-pulse opacity-70",
                          )}
                          style={{
                            left: `${left}%`,
                            width: `max(2px, ${(dur / total) * 100}%)`,
                            ...(r.running
                              ? { backgroundImage: "repeating-linear-gradient(45deg, transparent 0 4px, rgb(255 255 255 / 0.35) 4px 8px)" }
                              : null),
                          }}
                        />
                        {model || tin !== null ? (
                          <span
                            className={cx(
                              "pointer-events-none absolute top-1/2 -translate-y-1/2 whitespace-nowrap font-mono text-[10.5px] text-fg-2",
                              left + (dur / total) * 100 > 60 ? "pr-1.5 text-right" : "pl-1.5",
                            )}
                            // Beside the bar, never on it: to its right, or to its left when it ends late.
                            style={left + (dur / total) * 100 > 60 ? { right: `${100 - left}%` } : { left: `${left + (dur / total) * 100}%` }}
                          >
                            {model}
                            {tin !== null || tout !== null ? ` · ${tin ?? 0}→${tout ?? 0} tok` : ""}
                          </span>
                        ) : null}
                      </div>
                      <div className="num w-[76px] shrink-0 px-3 text-right font-mono text-[11.5px] text-fg-2">
                        {fmtDur(span.duration_ms ?? dur)}
                        {r.running ? "…" : ""}
                      </div>
                    </button>
                    {isOpen ? (
                      <div className="border-t border-line-subtle bg-well px-4 py-3" style={{ paddingLeft: 28 + r.depth * 16 }}>
                        <table className="w-full text-left font-mono text-[11.5px]">
                          <tbody>
                            {(
                              [
                                ["span_id", span.span_id],
                                ["parent", span.parent_span_id ?? "—"],
                                ["start", span.start],
                                ["end", span.end ?? "running"],
                                ...Object.entries(span.attributes),
                              ] as [string, unknown][]
                            ).map(([k, v]) => (
                              <tr key={k} className="align-top">
                                <td className="w-[240px] py-0.5 pr-4 text-muted">{k}</td>
                                <td className="break-all py-0.5 text-fg-2">{typeof v === "string" ? v : JSON.stringify(v)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          </div>
        </>
      )}
    </div>
  );
}

function Stat({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <dt className="text-muted">{k}</dt>
      <dd className="num font-mono text-fg">{v}</dd>
    </div>
  );
}

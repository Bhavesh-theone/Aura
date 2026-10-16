"use client";

import { FileSearch, ShieldAlert } from "lucide-react";
import Link from "next/link";
import { humanize } from "@/shared/lib/format";
import { Badge } from "@/shared/ui/primitives";

const LONG_KEYS = new Set(["body", "review_notes", "rationale"]);
const THRESHOLD = 0.5;

const RULES: Record<string, string> = {
  ignore_instructions: "Tells the model to ignore or override its earlier instructions.",
  role_reassignment: "Tries to give the model a new role or persona.",
  system_prompt: "Refers to or tries to reveal the system prompt.",
  tool_call_json: "Contains JSON shaped like a tool call.",
  role_tags: "Contains chat role markers such as system or assistant tags.",
  approval_manipulation: "Pushes the agent to approve, skip a review or bypass a gate.",
  base64_blob: "Contains a large encoded blob that could hide instructions.",
  hidden_unicode: "Contains invisible or direction-changing characters.",
  excessive_repetition: "Repeats the same text many times, a common flooding trick.",
};

function asObj(v: unknown): Record<string, unknown> | null {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
}

export function show(v: unknown): string {
  if (typeof v === "string") return v;
  const o = asObj(v);
  if (o) {
    const text = o.summary ?? o.text ?? o.description ?? o.title ?? o.label;
    if (typeof text === "string") return text;
  }
  try {
    return JSON.stringify(v);
  } catch {
    return String(v);
  }
}

/** Document ids cited as retrieval sources on a proposed action. */
export function citationsOf(args: Record<string, unknown> | null | undefined): number[] {
  const c = args?.citations;
  return Array.isArray(c) ? c.filter((x): x is number => typeof x === "number") : [];
}

const chipCls = "inline-flex h-5 items-center rounded-xs border border-line bg-well px-1.5 text-[11px] text-fg-2";

export function Citations({ ids, dealId }: { ids: number[]; dealId: number | null }) {
  if (!ids.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-muted">Retrieved from</span>
      {ids.map((id) =>
        dealId ? (
          <Link key={id} href={`/deals/${dealId}?tab=documents`} className={`${chipCls} font-mono hover:border-accent hover:text-fg`}>
            Document {id}
          </Link>
        ) : (
          <span key={id} className={`${chipCls} font-mono`}>Document {id}</span>
        ),
      )}
    </div>
  );
}

function SourceLabel({ s, dealId }: { s: string; dealId: number | null }) {
  const doc = /^document:(\d+)(?:#chunk(\d+))?$/.exec(s);
  if (doc) {
    const label = `Document ${doc[1]}${doc[2] ? `, chunk ${doc[2]}` : ""}`;
    return dealId ? (
      <Link href={`/deals/${dealId}?tab=documents`} className={`${chipCls} hover:border-accent hover:text-fg`}>{label}</Link>
    ) : (
      <span className={chipCls}>{label}</span>
    );
  }
  const tool = /^tool:(.+)$/.exec(s);
  return <span className={chipCls}>{tool ? `Tool output: ${tool[1]}` : s}</span>;
}

function UntrustedBody({ o, dealId }: { o: Record<string, unknown>; dealId: number | null }) {
  const score = typeof o.risk_score === "number" ? o.risk_score : null;
  const rules = Array.isArray(o.matched_rules) ? o.matched_rules.map(String) : [];
  const sources = Array.isArray(o.sources) ? o.sources.map(String) : [];
  return (
    <div className="min-w-0 flex-1 space-y-2.5">
      <div className="font-medium text-danger">Possible prompt injection</div>
      {score !== null ? (
        <div>
          <span className="text-muted">Risk score </span>
          <span className="num font-mono text-fg">{score.toFixed(2)}</span>
          <span className="text-muted"> (flagged at {THRESHOLD.toFixed(1)} and above)</span>
        </div>
      ) : null}
      {rules.length ? (
        <ul className="space-y-1">
          {rules.map((r) => (
            <li key={r} className="flex items-start gap-2">
              <code className="shrink-0 rounded-xs border border-line bg-well px-1.5 font-mono text-[11px] text-fg">{r}</code>
              <span className="text-fg-2">{RULES[r] ?? "Matched a screening rule."}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {sources.length ? (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-muted">Found in</span>
          {sources.map((s) => <SourceLabel key={s} s={s} dealId={dealId} />)}
        </div>
      ) : null}
      <p className="text-fg-2">Text in this content looked like instructions aimed at the agent. The recommended option is the one that changes nothing.</p>
    </div>
  );
}

function GatedAttempts({ o }: { o: Record<string, unknown> }) {
  const list = Array.isArray(o.additional_gated_attempts) ? o.additional_gated_attempts : [];
  return (
    <div className="min-w-0 flex-1 space-y-2">
      <p className="text-muted">Gated calls the agent also tried. None of them ran.</p>
      <ul className="space-y-1.5">
        {list.map((a, i) => {
          const r = asObj(a) ?? {};
          const m = typeof r.materiality_inr === "number" ? r.materiality_inr : null;
          return (
            <li key={i} className="rounded-sm border border-line-subtle bg-canvas px-2.5 py-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-[11px] text-fg">{String(r.tool ?? "tool")}</span>
                {r.category ? <Badge tone="neutral">{humanize(String(r.category))}</Badge> : null}
                {m !== null ? <span className="num font-mono text-[11px] text-muted">₹{m.toLocaleString("en-IN")}</span> : null}
              </div>
              {r.arguments !== undefined ? (
                <details className="mt-1">
                  <summary className="cursor-pointer text-[11px] text-muted hover:text-fg">Arguments</summary>
                  <pre className="scroll mt-1 overflow-x-auto whitespace-pre-wrap break-words font-mono text-[11px] text-fg-2">{JSON.stringify(r.arguments, null, 2)}</pre>
                </details>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** One evidence item as labelled facts, never a raw object. */
export function EvidenceBody({ ev, dealId }: { ev: unknown; dealId: number | null }) {
  const o = asObj(ev);
  if (!o) return <span className="min-w-0 break-words">{show(ev)}</span>;
  if (o.type === "untrusted_content") return <UntrustedBody o={o} dealId={dealId} />;
  if (o.type === "additional_gated_attempts" || Array.isArray(o.additional_gated_attempts)) return <GatedAttempts o={o} />;
  const args = asObj(o.arguments);
  if (!args) return <span className="min-w-0 break-words">{show(ev)}</span>;
  const cites = citationsOf(args);
  const entries = Object.entries(args).filter(([k, v]) => k !== "citations" && v !== null && v !== undefined && v !== "");
  const short = entries.filter(([k]) => !LONG_KEYS.has(k));
  const long = entries.filter(([k]) => LONG_KEYS.has(k));
  return (
    <div className="min-w-0 flex-1 space-y-2">
      <div className="font-mono text-[11px] text-muted">{typeof o.tool === "string" ? o.tool : "proposed action"}</div>
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1">
        {short.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-muted">{humanize(k)}</dt>
            <dd className="min-w-0 break-words text-fg">{typeof v === "object" ? JSON.stringify(v) : String(v)}</dd>
          </div>
        ))}
      </dl>
      {long.map(([k, v]) => (
        <div key={k}>
          <div className="mb-1 text-muted">{humanize(k)}</div>
          <p className="whitespace-pre-wrap rounded-sm border border-line-subtle bg-canvas px-2.5 py-2 text-[12px] leading-relaxed text-fg">{String(v)}</p>
        </div>
      ))}
      <Citations ids={cites} dealId={dealId} />
    </div>
  );
}

export function EvidenceList({ items, dealId }: { items: unknown[]; dealId: number | null }) {
  return (
    <ul className="space-y-1.5">
      {items.map((ev, i) => {
        const bad = asObj(ev)?.type === "untrusted_content";
        return (
          <li
            key={i}
            className={`flex items-start gap-2 rounded-sm border bg-surface px-3 py-2 text-[12px] text-fg-2 ${bad ? "border-danger-border border-l-2 border-l-danger" : "border-line"}`}
          >
            {bad ? <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-danger" /> : <FileSearch className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted" />}
            <EvidenceBody ev={ev} dealId={dealId} />
          </li>
        );
      })}
    </ul>
  );
}

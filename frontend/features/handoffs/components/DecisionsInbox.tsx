"use client";

import { AlarmClock, ArrowUpRight, Check, CheckCircle2, Hourglass, Info, ShieldAlert, Lock, Plus, RotateCcw, Siren, Sparkles, X, XCircle } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError } from "@/shared/api/client";
import { handoffEvents } from "@/shared/api/events";
import { cx, formatDateTime, formatStamp, humanize, parseApiDate, shortAgo, titleCase } from "@/shared/lib/format";
import { errMessage, useApi } from "@/shared/lib/useApi";
import { Badge, Button, Kbd, Keys, Segmented, inputCls, labelCls, textareaCls } from "@/shared/ui/primitives";
import { Permit, RoleNote } from "@/shared/ui/Permit";
import { isTyping } from "@/shared/ui/shell/PortalShell";
import { EmptyState, InlineError, Notice, Skel, Unavailable } from "@/shared/ui/States";
import { useToast } from "@/shared/ui/toast";
import { useDeals } from "@/features/deals/hooks";
import type { Deal } from "@/features/deals/types";
import { useAuth } from "@/features/auth/hooks";
import { canResolve, roleLabel, whoCanResolve } from "@/features/auth/roles";
import { getJob } from "@/features/jobs/api";
import { DraftRecipientPanel, OutboundResult, isDraftEmail, isRecipientEvidence } from "@/features/integrations/components/OutboundPanels";
import { EvidenceList, show } from "./Evidence";
import { isEscalated, listHandoffs, listResolvedHandoffs, resolveHandoff, type Handoff, type HandoffOption } from "../api";

/* --------------------------------- helpers -------------------------------- */

function useNow(ms = 1000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(id);
  }, [ms]);
  return now;
}

function countdown(target: string, now: number): { text: string; overdue: boolean; urgent: boolean } {
  const t = parseApiDate(target).getTime();
  if (Number.isNaN(t)) return { text: "", overdue: false, urgent: false };
  let s = Math.floor((t - now) / 1000);
  if (s <= 0) return { text: "now", overdue: true, urgent: true };
  const urgent = s < 3600;
  const d = Math.floor(s / 86400);
  s -= d * 86400;
  const h = Math.floor(s / 3600);
  s -= h * 3600;
  const m = Math.floor(s / 60);
  const sec = s - m * 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  if (d > 0) return { text: `${d}d ${pad(h)}h ${pad(m)}m`, overdue: false, urgent };
  return { text: `${pad(h)}:${pad(m)}:${pad(sec)}`, overdue: false, urgent };
}

const escalateAt = (h: Handoff) => h.context_package?.if_you_do_nothing?.auto_escalate_at ?? h.auto_escalate_at ?? null;

const SEEN_KEY = "aura_seen_handoffs";
function useSeen() {
  const [seen, setSeen] = useState<Set<number>>(new Set());
  useEffect(() => {
    try {
      setSeen(new Set(JSON.parse(localStorage.getItem(SEEN_KEY) ?? "[]")));
    } catch {
      /* ignore */
    }
  }, []);
  const mark = useCallback((id: number) => {
    setSeen((prev) => {
      if (prev.has(id)) return prev;
      const next = new Set(prev).add(id);
      try {
        localStorage.setItem(SEEN_KEY, JSON.stringify([...next].slice(-500)));
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);
  return { seen, mark };
}

const APPROVE_RX = /approve|accept|proceed|confirm|go|yes|release|sign/i;
const REJECT_RX = /reject|decline|hold|block|no\b|pause|defer|stop|cancel/i;

function findPath(options: HandoffOption[], kind: "approve" | "reject", rec?: string) {
  const rx = kind === "approve" ? APPROVE_RX : REJECT_RX;
  return (
    options.find((o) => rx.test(o.id) || rx.test(o.label)) ??
    (kind === "approve" ? options.find((o) => o.id === rec || o.label === rec) ?? options[0] : options[options.length - 1])
  );
}

/* ----------------------------- Confidence meter ---------------------------- */

function ConfidenceMeter({ value }: { value: number }) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  const filled = Math.round(pct / 10);
  const tone = pct >= 75 ? "bg-success" : pct >= 50 ? "bg-accent" : "bg-warning";
  return (
    <div className="flex items-center gap-2.5" role="meter" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="Recommendation confidence">
      <div className="flex gap-[2px]">
        {Array.from({ length: 10 }).map((_, i) => (
          <span key={i} className={cx("h-2.5 w-1.5 rounded-[1px]", i < filled ? tone : "bg-control-active")} />
        ))}
      </div>
      <span className="num font-mono text-[12px] text-fg-2">{pct}%</span>
      <span className="text-[12px] text-muted">confidence</span>
    </div>
  );
}

/* -------------------------------- Detail pane ------------------------------ */

function ThinkingDetail() {
  return (
    <div className="mx-auto max-w-[760px] px-10 py-10" aria-busy="true" aria-label="Loading decision brief">
      <div className="flex items-center gap-2 text-[12px]">
        <Sparkles className="h-3.5 w-3.5 text-accent" />
        <span className="thinking-text font-medium">Aura is assembling the brief…</span>
      </div>
      <Skel className="mt-5 h-7 w-[85%]" />
      <Skel className="mt-2.5 h-7 w-[60%]" />
      <Skel className="mt-8 h-24 w-full rounded-md" />
      <Skel className="mt-6 h-28 w-full rounded-md" />
      <div className="mt-6 space-y-2">
        <Skel className="h-16 w-full rounded-md" />
        <Skel className="h-16 w-full rounded-md" />
      </div>
    </div>
  );
}

const CONDITION_PRESETS = [
  "When the agent returns its next draft",
  "Before anything is sent outside the firm",
  "At the next stage move on this deal",
];
const ESCALATE_PRESETS = [
  "The counterparty changes the terms",
  "Agent confidence falls below 0.80",
  "Any amount above ₹1 Cr is involved",
];

function Presets({ options, onPick, label }: { options: string[]; onPick: (v: string) => void; label: string }) {
  return (
    <div className="mt-1.5 flex flex-wrap gap-1" aria-label={label}>
      {options.map((o) => (
        <button
          key={o}
          type="button"
          onClick={() => onPick(o)}
          className="inline-flex h-6 items-center rounded-full border border-line bg-well px-2 text-[11px] text-fg-2 transition-colors hover:border-line-strong hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50"
        >
          {o}
        </button>
      ))}
    </div>
  );
}

/** Chip input for do_not_revisit; Enter or comma adds, Backspace on empty removes the last. */
function ChipInput({ id, value, onChange, suggestions, placeholder }: { id: string; value: string[]; onChange: (v: string[]) => void; suggestions: string[]; placeholder: string }) {
  const [text, setText] = useState("");
  const add = (v: string) => {
    const t = v.trim();
    if (t && !value.includes(t)) onChange([...value, t]);
    setText("");
  };
  const unused = suggestions.filter((s) => s && !value.includes(s));
  return (
    <div>
      <div className={cx(inputCls, "flex h-auto min-h-8 flex-wrap items-center gap-1 py-1")}>
        {value.map((v) => (
          <span key={v} className="inline-flex h-5 items-center gap-1 rounded-xs border border-line bg-well pl-1.5 pr-0.5 font-mono text-[11px] text-fg-2">
            {v}
            <button type="button" aria-label={`Remove ${v}`} onClick={() => onChange(value.filter((x) => x !== v))} className="flex h-4 w-4 items-center justify-center rounded-xs text-muted hover:bg-control-hover hover:text-fg">
              <X className="h-3 w-3" />
            </button>
          </span>
        ))}
        <input
          id={id}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault();
              add(text);
            } else if (e.key === "Backspace" && !text && value.length) {
              onChange(value.slice(0, -1));
            }
          }}
          onBlur={() => text.trim() && add(text)}
          placeholder={value.length ? "" : placeholder}
          className="h-6 min-w-[140px] flex-1 bg-transparent text-[13px] text-fg outline-none placeholder:text-muted"
        />
      </div>
      {unused.length ? (
        <div className="mt-1.5 flex flex-wrap items-center gap-1">
          <span className="text-[11px] text-muted">Quick add</span>
          {unused.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => add(s)}
              className="inline-flex h-6 items-center gap-1 rounded-full border border-dashed border-line-strong px-2 font-mono text-[11px] text-fg-2 hover:border-accent hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50"
            >
              <Plus className="h-3 w-3" /> {s}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function EscalatedBanner({ handoff }: { handoff: Handoff }) {
  const role = handoff.context_package?.if_you_do_nothing?.escalates_to_role;
  return (
    <section aria-label="Escalated" className="mt-6 flex gap-4 rounded-md border border-danger-border bg-danger-soft p-4">
      <Siren className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
      <div className="min-w-0 flex-1">
        <div className="text-[12px] font-semibold uppercase tracking-[0.06em] text-danger">Escalated</div>
        <p className="mt-1 text-[14px] leading-relaxed text-fg">
          Nobody answered in time, so this was escalated{role ? ` to ${roleLabel(role).toLowerCase()}` : ""}. It still needs a decision.
        </p>
      </div>
    </section>
  );
}

function HandoffDetail({ handoff, deal, onResolved }: { handoff: Handoff; deal?: Deal; onResolved: () => void }) {
  const toast = useToast();
  const now = useNow();
  const { user } = useAuth();
  const allowed = canResolve(user, handoff.trigger);
  const ctx = handoff.context_package ?? {};
  const dr = ctx.decision_required;
  const idn = ctx.if_you_do_nothing;
  const evidenceItems = isDraftEmail(handoff) ? (ctx.evidence ?? []).filter((ev) => !isRecipientEvidence(ev)) : (ctx.evidence ?? []);
  const escalated = isEscalated(handoff);
  const esc = escalated ? null : escalateAt(handoff);
  const [decision, setDecision] = useState("");
  const [reasoning, setReasoning] = useState("");
  const [dnr, setDnr] = useState<string[]>([]);
  const [condition, setCondition] = useState("");
  const [escalateIf, setEscalateIf] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ title: string; body: string } | null>(null);
  const [confirm, setConfirm] = useState(false);
  const reasonRef = useRef<HTMLTextAreaElement>(null);
  const injection = handoff.trigger === "untrusted_content";
  const level1 = (ctx.what_happened ?? []).some((w) => show(w).includes("is at level 1"));
  const jobTrace = useApi(handoff.job_id ? () => getJob(handoff.job_id as number) : null, null, [handoff.job_id]);
  const traceId = jobTrace.data?.trace_id ?? null;

  useEffect(() => {
    setDecision("");
    setReasoning("");
    setDnr([]);
    setCondition("");
    setEscalateIf("");
    setError(null);
  }, [handoff.id]);
  useEffect(() => setConfirm(false), [decision]);

  // A = approve path, R = reject path: select it and drop the cursor into reasoning.
  useEffect(() => {
    if (!dr?.options.length || !allowed) return;
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e.target) || e.metaKey || e.ctrlKey || e.altKey || document.querySelector("[role=dialog]")) return;
      const k = e.key.toLowerCase();
      if (k !== "a" && k !== "r") return;
      e.preventDefault();
      const o = findPath(dr.options, k === "a" ? "approve" : "reject", dr.recommendation);
      if (o) setDecision(o.id);
      requestAnimationFrame(() => reasonRef.current?.focus());
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [dr, allowed]);

  const len = reasoning.trim().length;
  const chosen = dr?.options.find((o) => o.id === decision);
  const irreversible = chosen ? !chosen.reversible : false;
  const recOption = dr?.options.find((o) => o.id === dr.recommendation || o.label === dr.recommendation);

  let blocker: string | null = null;
  if (!allowed) blocker = whoCanResolve(handoff.trigger);
  else if (!decision) blocker = "Choose an option.";
  else if (len < 30) blocker = `${30 - len} more character${30 - len === 1 ? "" : "s"} of reasoning needed.`;
  else if (!condition.trim()) blocker = "Set the next checkpoint.";
  else if (!escalateIf.trim()) blocker = "Say when the agent should escalate.";
  else if (irreversible && !confirm) blocker = "Confirm this can’t be undone.";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (blocker) return;
    setBusy(true);
    setError(null);
    try {
      await resolveHandoff(handoff.id, {
        decision,
        reasoning: reasoning.trim(),
        new_constraints: { do_not_revisit: dnr },
        next_checkpoint: { condition: condition.trim(), escalate_if: escalateIf.trim() },
      });
      toast(`Decision recorded — “${chosen?.label ?? decision}” handed back to the agent`);
      onResolved();
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setError({ title: "Your role can’t record this decision", body: errMessage(err) });
      } else if (err instanceof ApiError && err.status === 409) {
        setError({ title: "Already decided", body: "Someone resolved this while you were reading. Refreshing the inbox." });
        onResolved();
      } else {
        setError({ title: "Couldn’t record the decision", body: errMessage(err) });
      }
    } finally {
      setBusy(false);
    }
  }

  const cd = esc ? countdown(esc, now) : null;

  return (
    <article className="a-fade mx-auto max-w-[760px] px-10 pb-16 pt-9">
      {/* Eyebrow */}
      <div className="flex flex-wrap items-center gap-2 text-[12px] text-muted">
        {escalated ? <Badge tone="danger"><Siren className="h-3 w-3" /> Escalated</Badge> : null}
        {injection ? (
          <Badge tone="danger"><ShieldAlert className="h-3 w-3" /> Possible prompt injection</Badge>
        ) : (
          <Badge tone="accent">{humanize(handoff.trigger)}</Badge>
        )}
        {handoff.task_type ? <span className="font-mono text-[11px]">{handoff.task_type}</span> : null}
        {handoff.deal_id ? (
          <Link href={`/deals/${handoff.deal_id}`} className="inline-flex items-center gap-1 text-fg-2 hover:text-fg">
            {deal ? deal.name : `Deal #${handoff.deal_id}`}
            {deal ? <span className="font-mono text-[11px] text-muted">{deal.external_id}</span> : null}
            <ArrowUpRight className="h-3 w-3" />
          </Link>
        ) : null}
        {traceId ? (
          <Link href={`/traces/${traceId}`} className="inline-flex items-center gap-1 text-fg-2 hover:text-fg">
            View trace <ArrowUpRight className="h-3 w-3" />
          </Link>
        ) : null}
        <span className="ml-auto num font-mono text-[11px]">raised {formatStamp(handoff.created_at)}</span>
      </div>

      <h1 className="mt-4 font-serif text-[28px] leading-[1.2] text-fg">{dr?.question ?? "A decision is needed"}</h1>
      {level1 ? (
        <div className="mt-4 flex items-start gap-2.5 rounded-md border border-info-border bg-info-soft px-3.5 py-2.5 text-[13px] text-fg">
          <Info className="mt-0.5 h-4 w-4 shrink-0 text-info" />
          <span>
            Supervised capability (autonomy level 1): every result goes to a person.{" "}
            <Link href="/quality" className="text-accent hover:underline">See agent quality</Link>
          </span>
        </div>
      ) : null}
      {!allowed ? (
        <RoleNote className="mt-3">
          {whoCanResolve(handoff.trigger)} You can read the brief.
        </RoleNote>
      ) : null}

      {escalated ? <EscalatedBanner handoff={handoff} /> : null}

      {/* If you do nothing */}
      {idn && !escalated ? (
        <section
          aria-label="If you do nothing"
          className={cx(
            "mt-6 flex gap-4 rounded-md border p-4",
            cd?.urgent ? "border-danger-border bg-danger-soft" : "border-warning-border bg-warning-soft",
          )}
        >
          <Hourglass className={cx("mt-0.5 h-4 w-4 shrink-0", cd?.urgent ? "text-danger" : "text-warning")} />
          <div className="min-w-0 flex-1">
            <div className={cx("text-[12px] font-semibold uppercase tracking-[0.06em]", cd?.urgent ? "text-danger" : "text-warning")}>If you do nothing</div>
            <p className="mt-1 text-[14px] leading-relaxed text-fg">{idn.consequence}</p>
            {idn.escalates_to_role ? <p className="mt-1.5 text-[12px] text-fg-2">Escalates to {roleLabel(idn.escalates_to_role).toLowerCase()}.</p> : null}
          </div>
          {cd ? (
            <div className="shrink-0 text-right">
              <div className="text-[11px] text-muted">{cd.overdue ? "Escalating" : "Auto-escalates in"}</div>
              <div aria-live="off" className={cx("num mt-0.5 font-mono text-[20px] font-medium leading-none", cd.urgent ? "text-danger" : "text-warning")}>
                {cd.text}
              </div>
            </div>
          ) : null}
        </section>
      ) : null}

      {/* AI recommendation */}
      {dr?.recommendation ? (
        <section aria-label="Aura recommendation" className="mt-8">
          <div className="mb-2 flex items-center gap-2 text-[12px] text-muted">
            <Sparkles className="h-3.5 w-3.5 text-accent" /> Aura recommends
          </div>
          <blockquote className="border-l-2 border-accent pl-5">
            <p className="font-serif text-[22px] leading-snug text-fg">{recOption?.label ?? dr.recommendation}</p>
            {dr.rationale ? <p className="mt-2 font-serif text-[16px] leading-relaxed text-fg-2">“{dr.rationale}”</p> : null}
            {recOption?.consequence && !dr.rationale ? (
              <p className="mt-2 font-serif text-[16px] leading-relaxed text-fg-2">{recOption.consequence}</p>
            ) : null}
            {dr.confidence != null ? <div className="mt-3"><ConfidenceMeter value={dr.confidence} /></div> : null}
            {dr.dissent ? (
              <p className="mt-3 rounded-sm border border-line bg-surface px-3 py-2 text-[13px] leading-relaxed text-fg-2">
                <span className="font-medium text-fg">Dissent · </span>{dr.dissent}
              </p>
            ) : null}
          </blockquote>
        </section>
      ) : null}

      {isDraftEmail(handoff) ? <DraftRecipientPanel handoff={handoff} /> : null}

      {/* Options */}
      {dr ? (
        <fieldset className="mt-8">
          <legend className="mb-2.5 flex w-full items-center text-[12px] font-medium text-fg-2">
            Options
            <span className="ml-auto flex items-center gap-3 font-normal text-muted">
              <span className="flex items-center gap-1"><Kbd>A</Kbd> approve path</span>
              <span className="flex items-center gap-1"><Kbd>R</Kbd> reject path</span>
            </span>
          </legend>
          <div className="space-y-2" role="radiogroup">
            {dr.options.map((o) => {
              const sel = decision === o.id;
              const recommended = dr.recommendation === o.id || dr.recommendation === o.label;
              return (
                <label
                  key={o.id}
                  className={cx(
                    "flex cursor-pointer gap-3 rounded-md border bg-surface p-4 transition-[border-color,background-color,box-shadow] duration-[var(--dur-1)] focus-within:ring-2 focus-within:ring-accent/40",
                    sel ? "border-accent shadow-[0_0_0_1px_var(--accent)]" : "border-line shadow-card hover:border-line-strong",
                  )}
                >
                  <input type="radio" name={`opt-${handoff.id}`} className="sr-only" checked={sel} disabled={!allowed} onChange={() => setDecision(o.id)} />
                  <span className={cx("mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border", sel ? "border-accent bg-accent text-on-accent" : "border-line-strong")}>
                    {sel ? <Check className="h-2.5 w-2.5" strokeWidth={3.5} /> : null}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="text-[14px] font-medium text-fg">{o.label}</span>
                      {recommended ? <Badge tone="accent"><Sparkles className="h-3 w-3" /> Recommended</Badge> : null}
                      <span className="ml-auto">
                        {o.reversible ? (
                          <Badge tone="neutral"><RotateCcw className="h-3 w-3" /> Reversible</Badge>
                        ) : (
                          <Badge tone="danger"><Lock className="h-3 w-3" /> Can’t be undone</Badge>
                        )}
                      </span>
                    </span>
                    <span className="mt-1 block text-[13px] leading-relaxed text-fg-2">{o.consequence}</span>
                  </span>
                </label>
              );
            })}
          </div>
        </fieldset>
      ) : null}

      {/* Context */}
      {(ctx.what_happened?.length || evidenceItems.length) ? (
        <div className="mt-8 grid grid-cols-1 gap-6 md:grid-cols-2">
          {ctx.what_happened?.length ? (
            <section>
              <h2 className="mb-2.5 text-[12px] font-medium text-fg-2">What happened</h2>
              <ol className="relative space-y-2.5 border-l border-line pl-4">
                {ctx.what_happened.map((w, i) => (
                  <li key={i} className="relative text-[13px] leading-relaxed text-fg-2">
                    <span className="absolute -left-[20.5px] top-[7px] h-2 w-2 rounded-full border-2 border-surface bg-line-strong" />
                    {show(w)}
                  </li>
                ))}
              </ol>
            </section>
          ) : null}
          {evidenceItems.length ? (
            <section>
              <h2 className="mb-2.5 text-[12px] font-medium text-fg-2">Evidence</h2>
              <EvidenceList items={evidenceItems} dealId={handoff.deal_id} />
            </section>
          ) : null}
        </div>
      ) : null}

      {/* Decision form */}
      <form onSubmit={submit} className="mt-10 rounded-md border border-line bg-surface shadow-card">
        <div className="border-b border-line-subtle px-5 py-3.5">
          <h2 className="font-serif text-[18px] text-fg">Record your decision</h2>
          <p className="text-[12px] text-muted">Stored with the audit chain and handed back to the agent as a directive.</p>
        </div>
        <fieldset disabled={!allowed} className="space-y-4 px-5 py-5 disabled:opacity-60">
          {!allowed ? <RoleNote className="-mt-1">{whoCanResolve(handoff.trigger)} You’re signed in as {roleLabel(user?.role).toLowerCase()}.</RoleNote> : null}
          <div>
            <label htmlFor="h-reason" className={cx(labelCls, "flex items-center")}>
              Reasoning
              <span className={cx("num ml-auto font-mono text-[11px] font-normal", len >= 30 ? "text-success" : "text-muted")}>
                {len}/30 min
              </span>
            </label>
            <textarea ref={reasonRef} id="h-reason" rows={3} value={reasoning} onChange={(e) => setReasoning(e.target.value)} className={textareaCls} placeholder={chosen ? `Why “${chosen.label}”?` : "Pick an option, then explain why."} />
          </div>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div>
              <label htmlFor="h-cond" className={labelCls}>Next checkpoint <span className="font-normal text-danger">*</span></label>
              <input id="h-cond" required aria-required value={condition} onChange={(e) => setCondition(e.target.value)} className={inputCls} placeholder="When should the agent check back in?" />
              <Presets label="Checkpoint presets" options={CONDITION_PRESETS} onPick={setCondition} />
            </div>
            <div>
              <label htmlFor="h-esc" className={labelCls}>Escalate if <span className="font-normal text-danger">*</span></label>
              <input id="h-esc" required aria-required value={escalateIf} onChange={(e) => setEscalateIf(e.target.value)} className={inputCls} placeholder="What should bring this back to a human?" />
              <Presets label="Escalation presets" options={ESCALATE_PRESETS} onPick={setEscalateIf} />
            </div>
          </div>
          <div>
            <label htmlFor="h-dnr" className={labelCls}>Don’t revisit <span className="font-normal text-muted">· optional — work the agent must treat as settled</span></label>
            <ChipInput id="h-dnr" value={dnr} onChange={setDnr} suggestions={handoff.task_type ? [handoff.task_type] : []} placeholder="Type and press Enter" />
          </div>
          {irreversible ? (
            <label className="flex items-start gap-2.5 rounded-sm border border-danger-border bg-danger-soft px-3 py-2.5 text-[13px] text-fg">
              <input type="checkbox" className="mt-[3px]" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />
              I understand “{chosen?.label}” can’t be undone.
            </label>
          ) : null}
          {error ? <Notice tone="error" title={error.title}>{error.body}</Notice> : null}
        </fieldset>
        <div className="flex items-center gap-3 border-t border-line-subtle px-5 py-3.5">
          <span className={cx("flex-1 text-[12px]", blocker ? "text-muted" : "text-success")}>{blocker ?? "Ready to record."}</span>
          <Permit allow={allowed} why={whoCanResolve(handoff.trigger)}>
            <Button type="submit" loading={busy} disabled={blocker !== null} variant={irreversible ? "danger" : "primary"}>
              Record decision
            </Button>
          </Permit>
        </div>
      </form>
    </article>
  );
}

/* ------------------------------ Resolved detail ----------------------------- */

const isNo = (decision: string | undefined) => /reject|discard|decline/i.test(decision ?? "");

function ResolvedDetail({ handoff, deal }: { handoff: Handoff; deal?: Deal }) {
  const ctx = handoff.context_package ?? {};
  const dr = ctx.decision_required;
  const d = handoff.directive ?? {};
  const chosen = dr?.options.find((o) => o.id === d.decision);
  const rejected = isNo(d.decision);
  const dnr = d.new_constraints?.do_not_revisit ?? [];
  const rows: [string, React.ReactNode][] = [
    ["Chose", <span key="c" className={cx("font-medium", rejected ? "text-danger" : "text-fg")}>{chosen?.label ?? humanize(d.decision ?? "—")}</span>],
    ["Reasoning", d.reasoning || "—"],
    ["Next checkpoint", d.next_checkpoint?.condition || "—"],
    ["Escalate if", d.next_checkpoint?.escalate_if || "—"],
    [
      "Don’t revisit",
      dnr.length ? (
        <span key="d" className="flex flex-wrap gap-1">
          {dnr.map((x) => (
            <Badge key={x} mono>{x}</Badge>
          ))}
        </span>
      ) : (
        <span key="d" className="text-muted">Nothing ruled out</span>
      ),
    ],
  ];
  return (
    <article className="a-fade mx-auto max-w-[760px] px-10 pb-16 pt-9">
      <div className="flex flex-wrap items-center gap-2 text-[12px] text-muted">
        <Badge tone={rejected ? "danger" : "success"}>
          {rejected ? <XCircle className="h-3 w-3" /> : <CheckCircle2 className="h-3 w-3" />} {rejected ? "Rejected" : "Resolved"}
        </Badge>
        <Badge tone="neutral">{humanize(handoff.trigger)}</Badge>
        {handoff.deal_id ? (
          <Link href={`/deals/${handoff.deal_id}`} className="inline-flex items-center gap-1 text-fg-2 hover:text-fg">
            {deal ? deal.name : `Deal #${handoff.deal_id}`}
            <ArrowUpRight className="h-3 w-3" />
          </Link>
        ) : null}
        <span className="ml-auto num font-mono text-[11px]">raised {formatStamp(handoff.created_at)}</span>
      </div>
      <h1 className="mt-4 font-serif text-[28px] leading-[1.2] text-fg">{dr?.question ?? "A decision was needed"}</h1>

      <section className="mt-8 rounded-md border border-line bg-surface shadow-card">
        <div className="flex items-center gap-2 border-b border-line-subtle px-5 py-3.5">
          <h2 className="font-serif text-[18px] text-fg">Decision on record</h2>
          <span className="ml-auto text-[12px] text-muted">
            {handoff.resolved_by ? (
              <>
                by <span className="text-fg-2">{titleCase(handoff.resolved_by)}</span>
              </>
            ) : null}
            {handoff.resolved_at ? <span className="num font-mono"> · {formatDateTime(handoff.resolved_at)}</span> : null}
          </span>
        </div>
        <dl className="divide-y divide-line-subtle text-[13px]">
          {rows.map(([k, v]) => (
            <div key={k} className="grid grid-cols-[150px_1fr] gap-4 px-5 py-3">
              <dt className="text-muted">{k}</dt>
              <dd className="leading-relaxed text-fg-2">{v}</dd>
            </div>
          ))}
        </dl>
      </section>
      {isDraftEmail(handoff) && !rejected ? <OutboundResult handoffId={handoff.id} /> : null}
    </article>
  );
}

/* ---------------------------------- Inbox ---------------------------------- */

export function DecisionsInbox() {
  const [view, setView] = useState<"open" | "resolved">("open");
  const open = useApi<Handoff[]>(listHandoffs, [], [], { live: handoffEvents });
  const resolved = useApi<Handoff[]>(view === "resolved" ? listResolvedHandoffs : null, [], [view], { live: handoffEvents });
  const { data, loading, error, unavailable, refresh } = view === "open" ? open : resolved;
  const { deals } = useDeals();
  const dealMap = useMemo(() => new Map(deals.map((d) => [d.id, d])), [deals]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  // Deep link from the activity feed: /decisions?handoff=7 — opens the resolved view if it is no longer open.
  const [linked, setLinked] = useState<number | null>(null);
  useEffect(() => {
    const id = Number(new URLSearchParams(window.location.search).get("handoff"));
    if (Number.isInteger(id) && id > 0) {
      setLinked(id);
      setSelectedId(id);
    }
  }, []);
  useEffect(() => {
    if (linked === null || open.loading) return;
    if (!open.data.some((h) => h.id === linked)) setView("resolved");
    setLinked(null);
  }, [linked, open.loading, open.data]);
  const { seen, mark } = useSeen();
  const now = useNow(30000);

  const ordered = useMemo(
    () =>
      [...data].sort((a, b) => {
        if (view === "resolved") return (a.resolved_at ?? a.created_at) < (b.resolved_at ?? b.created_at) ? 1 : -1;
        // Escalated first, then soonest to escalate, then newest.
        const xa = isEscalated(a);
        const xb = isEscalated(b);
        if (xa !== xb) return xa ? -1 : 1;
        const ea = escalateAt(a);
        const eb = escalateAt(b);
        if (ea && eb) return ea < eb ? -1 : 1;
        if (ea) return -1;
        if (eb) return 1;
        return a.created_at < b.created_at ? 1 : -1;
      }),
    [data, view],
  );

  useEffect(() => {
    if (loading || linked !== null) return;
    if (ordered.length === 0) setSelectedId(null);
    else if (selectedId === null || !ordered.some((h) => h.id === selectedId)) setSelectedId(ordered[0].id);
  }, [ordered, selectedId, loading, linked]);

  useEffect(() => {
    if (selectedId != null && view === "open") {
      const t = setTimeout(() => mark(selectedId), 1200);
      return () => clearTimeout(t);
    }
  }, [selectedId, mark, view]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e.target) || e.metaKey || e.ctrlKey || e.altKey || document.querySelector("[role=dialog]")) return;
      if (e.key !== "j" && e.key !== "k") return;
      e.preventDefault();
      const i = ordered.findIndex((h) => h.id === selectedId);
      const next = ordered[Math.max(0, Math.min(ordered.length - 1, i + (e.key === "j" ? 1 : -1)))];
      if (next) {
        setSelectedId(next.id);
        document.querySelector(`[data-handoff="${next.id}"]`)?.scrollIntoView({ block: "nearest" });
        document.getElementById("decision-detail")?.scrollTo({ top: 0 });
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [ordered, selectedId]);

  const selected = ordered.find((h) => h.id === selectedId) ?? null;
  const unread = view === "open" ? ordered.filter((h) => !seen.has(h.id)).length : 0;
  const escalatedCount = open.data.filter(isEscalated).length;

  return (
    <div className="flex h-[calc(100vh-48px)] min-h-0">
      {/* List */}
      <section aria-label="Decision queue" className="flex w-[360px] shrink-0 flex-col border-r border-line bg-canvas">
        <div className="flex h-14 shrink-0 items-center gap-2 border-b border-line px-4">
          <h1 className="font-serif text-[20px] text-fg">Decisions</h1>
          {unread ? <Badge tone="accent">{unread} new</Badge> : null}
          <span className="ml-auto">
            <Segmented
              label="Queue"
              value={view}
              onChange={setView}
              options={[
                {
                  value: "open",
                  label: (
                    <>
                      Open <span className="num font-mono text-[11px] opacity-70">{open.data.length}</span>
                    </>
                  ),
                },
                { value: "resolved", label: "Resolved" },
              ]}
            />
          </span>
        </div>
        {view === "open" && escalatedCount ? (
          <div className="flex h-8 shrink-0 items-center gap-1.5 border-b border-danger-border bg-danger-soft px-4 text-[12px] font-medium text-danger">
            <Siren className="h-3.5 w-3.5" /> {escalatedCount} escalated — past their response window
          </div>
        ) : null}
        <div className="scroll min-h-0 flex-1 overflow-y-auto">
          {unavailable ? (
            <div className="p-4"><Unavailable what="Decisions" /></div>
          ) : error ? (
            <div className="p-4"><InlineError message={error} onRetry={refresh} /></div>
          ) : loading && data.length === 0 ? (
            <div aria-busy="true">
              {[0, 1, 2, 3, 4].map((i) => (
                <div key={i} className="border-b border-line-subtle px-4 py-3.5">
                  <Skel className="h-2.5 w-28" />
                  <Skel className="mt-2.5 h-3 w-[90%]" />
                  <Skel className="mt-1.5 h-3 w-[60%]" />
                </div>
              ))}
            </div>
          ) : ordered.length === 0 ? (
            view === "open" ? (
              <EmptyState compact title="You’re all caught up" description="When an agent needs a human call, it lands here with options and what happens if you wait." />
            ) : (
              <EmptyState compact title="No resolved decisions yet" description="Every decision recorded here keeps its reasoning and the directive handed back to the agent." />
            )
          ) : (
            <ul>
              {ordered.map((h) => {
                const sel = h.id === selectedId;
                const isNew = view === "open" && !seen.has(h.id);
                const escalated = isEscalated(h);
                const esc = escalated || view === "resolved" ? null : escalateAt(h);
                const cd = esc ? countdown(esc, now) : null;
                const deal = h.deal_id ? dealMap.get(h.deal_id) : undefined;
                const rejected = view === "resolved" && isNo(h.directive?.decision);
                return (
                  <li key={h.id} data-handoff={h.id}>
                    <button
                      onClick={() => setSelectedId(h.id)}
                      aria-current={sel}
                      className={cx(
                        "relative w-full border-b border-line-subtle px-4 py-3 text-left transition-colors duration-[var(--dur-1)]",
                        sel ? "bg-surface dark:bg-raised" : "hover:bg-well",
                      )}
                    >
                      {sel ? <span aria-hidden className={cx("absolute inset-y-0 left-0 w-[2px]", escalated ? "bg-danger" : "bg-accent")} /> : null}
                      <div className="flex items-center gap-2">
                        <span className={cx("h-1.5 w-1.5 shrink-0 rounded-full", isNew ? "bg-accent" : "bg-transparent")} aria-label={isNew ? "Unread" : undefined} />
                        {escalated ? (
                          <Badge tone="danger" className="h-[18px] text-[11px]">
                            <Siren className="h-3 w-3" /> Escalated
                          </Badge>
                        ) : null}
                        {view === "resolved" ? (
                          <Badge tone={rejected ? "danger" : "success"} className="h-[18px] text-[11px]">
                            {rejected ? "Rejected" : "Resolved"}
                          </Badge>
                        ) : null}
                        {h.trigger === "untrusted_content" ? (
                          <Badge tone="danger" className="h-[18px] text-[11px]"><ShieldAlert className="h-3 w-3" /> Possible prompt injection</Badge>
                        ) : (
                          <Badge tone="neutral" className="h-[18px] text-[11px]">{humanize(h.trigger)}</Badge>
                        )}
                        <span className="num ml-auto font-mono text-[11px] text-muted" title={formatStamp(h.resolved_at ?? h.created_at)}>
                          {shortAgo(h.resolved_at ?? h.created_at)}
                        </span>
                      </div>
                      <div className={cx("mt-1.5 line-clamp-2 pl-3.5 text-[13px] leading-snug", isNew ? "font-medium text-fg" : "text-fg-2")}>
                        {h.context_package?.decision_required?.question ?? "A decision is needed"}
                      </div>
                      <div className="mt-1.5 flex items-center gap-2 pl-3.5 text-[11px] text-muted">
                        {deal ? <span className="truncate">{deal.name}</span> : h.deal_id ? <span>Deal #{h.deal_id}</span> : null}
                        {view === "resolved" && h.resolved_by ? <span className="ml-auto shrink-0">by {titleCase(h.resolved_by)}</span> : null}
                        {cd ? (
                          <span className={cx("num ml-auto inline-flex shrink-0 items-center gap-1 font-mono", cd.urgent ? "text-danger" : "text-warning")}>
                            <AlarmClock className="h-3 w-3" /> {cd.text.split(":").slice(0, 2).join(":")}
                          </span>
                        ) : null}
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
        <div className="flex h-9 shrink-0 items-center gap-3 border-t border-line px-4 text-[11px] text-muted">
          <span className="flex items-center gap-1">
            <Keys keys="j k" /> move
          </span>
          {view === "open" ? (
            <>
              <span className="flex items-center gap-1"><Kbd>A</Kbd> approve path</span>
              <span className="flex items-center gap-1"><Kbd>R</Kbd> reject path</span>
            </>
          ) : null}
        </div>
      </section>

      {/* Detail */}
      <section id="decision-detail" aria-label="Decision brief" className="scroll min-h-0 flex-1 overflow-y-auto bg-canvas">
        {loading && data.length === 0 ? (
          <ThinkingDetail />
        ) : selected ? (
          view === "open" ? (
            <HandoffDetail key={selected.id} handoff={selected} deal={selected.deal_id ? dealMap.get(selected.deal_id) : undefined} onResolved={refresh} />
          ) : (
            <ResolvedDetail key={selected.id} handoff={selected} deal={selected.deal_id ? dealMap.get(selected.deal_id) : undefined} />
          )
        ) : !unavailable && !error ? (
          <EmptyState
            title={view === "open" ? "Nothing needs you right now" : "Nothing resolved yet"}
            description={
              view === "open"
                ? "Agents keep working. Anything that touches money, legal execution or a counterparty will wait here for you."
                : "Resolved decisions appear here with the directive handed back to the agent."
            }
            action={
              <Link href="/activity">
                <Button variant="secondary">Review recent activity</Button>
              </Link>
            }
          />
        ) : null}
      </section>
    </div>
  );
}

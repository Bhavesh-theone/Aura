"use client";

import { AlertTriangle, CheckCircle2, ExternalLink, Hourglass, Mail, ShieldX, XCircle } from "lucide-react";
import { useEffect } from "react";
import type { Handoff } from "@/features/handoffs/api";
import { anyEvent } from "@/shared/api/events";
import { formatDateTime } from "@/shared/lib/format";
import { useApi } from "@/shared/lib/useApi";
import { Badge } from "@/shared/ui/primitives";
import { MODE_LABEL, blockReason, listOutbound, type Outbound, type OutboundMode } from "../api";

export const GMAIL_DRAFTS_URL = "https://mail.google.com/mail/u/0/#drafts";
const gmailSentUrl = (threadId: string | null) => `https://mail.google.com/mail/u/0/#sent${threadId ? `/${encodeURIComponent(threadId)}` : ""}`;

type Recipient = { email: string | null; verified: boolean; mode: OutboundMode | null; actionLabel: string | null };

function asObj(v: unknown): Record<string, unknown> | null {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
}
const s = (v: unknown) => (typeof v === "string" && v ? v : null);
const isMode = (v: unknown): v is OutboundMode => v === "off" || v === "gmail_draft" || v === "gmail_send";

export const isDraftEmail = (h: Pick<Handoff, "task_type">) => h.task_type === "draft_email";

/** Recipient evidence items are shown by the panel, not as raw evidence rows. */
export const isRecipientEvidence = (ev: unknown) => asObj(ev)?.type === "recipient";

export function recipientOf(h: Handoff): Recipient {
  const ctx = h.context_package ?? {};
  const ev = asObj((ctx.evidence ?? []).find(isRecipientEvidence));
  const args = asObj(ctx.proposed_action?.arguments) ?? {};
  const mode = isMode(ev?.mode) ? ev.mode : isMode(args.outbound_mode) ? args.outbound_mode : null;
  return {
    email: s(ev?.email) ?? s(args.to_email),
    verified: ev ? ev.verified === true : args.to_email_verified === true,
    mode,
    actionLabel: s(ev?.action_label),
  };
}

/** Who the email goes to and what approving will do — shown above the options of a draft_email handoff. */
export function DraftRecipientPanel({ handoff }: { handoff: Handoff }) {
  const r = recipientOf(handoff);
  const noVerified = !r.email || !r.verified;
  const approve = handoff.context_package?.decision_required?.options.find((o) => /approve/i.test(o.id) || /^approve/i.test(o.label));
  const what = r.actionLabel ?? approve?.label ?? null;
  return (
    <section aria-label="Recipient" className="mt-8 rounded-md border border-line bg-surface shadow-card">
      <div className="flex items-center gap-2 border-b border-line-subtle px-5 py-3">
        <Mail className="h-4 w-4 text-muted" />
        <h2 className="text-[13px] font-medium text-fg">Recipient</h2>
        {r.mode ? <Badge tone={r.mode === "off" ? "neutral" : r.mode === "gmail_send" ? "danger" : "accent"} className="ml-auto">{MODE_LABEL[r.mode]}</Badge> : null}
      </div>
      <dl className="divide-y divide-line-subtle text-[13px]">
        <div className="grid grid-cols-[150px_1fr] gap-4 px-5 py-2.5">
          <dt className="text-muted">To</dt>
          <dd className="flex min-w-0 flex-wrap items-center gap-2">
            {r.email ? <span className="break-all font-mono text-[12px] text-fg">{r.email}</span> : <span className="text-muted">No address</span>}
            {r.email ? (r.verified ? <Badge tone="success"><CheckCircle2 className="h-3 w-3" /> Verified</Badge> : <Badge tone="warning">Unverified</Badge>) : null}
          </dd>
        </div>
        {what ? (
          <div className="grid grid-cols-[150px_1fr] gap-4 px-5 py-2.5">
            <dt className="text-muted">If you approve</dt>
            <dd className="text-fg-2">{what}</dd>
          </div>
        ) : null}
      </dl>
      {noVerified ? (
        <div role="alert" className="flex items-start gap-2.5 border-t border-warning-border bg-warning-soft px-5 py-3 text-[13px] text-warning">
          <AlertTriangle className="mt-[3px] h-3.5 w-3.5 shrink-0" />
          <p className="leading-relaxed">
            This party has no verified email, so nothing can be sent or drafted even if you approve. A dealmaker can verify a contact on the deal’s Parties tab.
          </p>
        </div>
      ) : null}
    </section>
  );
}

function ResultLine({ o }: { o: Outbound }) {
  const link = "inline-flex items-center gap-1 font-medium text-accent hover:underline";
  if (o.status === "queued") {
    return <span className="inline-flex items-center gap-1.5 text-fg-2"><Hourglass className="h-3.5 w-3.5 a-pulse" /> Sending…</span>;
  }
  if (o.status === "drafted") {
    return (
      <a href={GMAIL_DRAFTS_URL} target="_blank" rel="noopener noreferrer" className={link}>
        <CheckCircle2 className="h-3.5 w-3.5 text-success" /> Gmail draft created <ExternalLink className="h-3 w-3" />
      </a>
    );
  }
  if (o.status === "sent") {
    return (
      <span className="inline-flex flex-wrap items-center gap-x-2 gap-y-1">
        <CheckCircle2 className="h-3.5 w-3.5 text-success" />
        <span className="text-fg">Sent via Gmail</span>
        {o.gmail_id ? <span className="font-mono text-[11px] text-muted">{o.gmail_id}</span> : null}
        {o.gmail_thread_id ? (
          <a href={gmailSentUrl(o.gmail_thread_id)} target="_blank" rel="noopener noreferrer" className={link}>
            Open thread <ExternalLink className="h-3 w-3" />
          </a>
        ) : null}
      </span>
    );
  }
  if (o.status === "blocked") {
    return (
      <span className="inline-flex items-center gap-1.5 text-warning">
        <ShieldX className="h-3.5 w-3.5" /> Blocked: {o.error ? blockReason(o.error) : "no reason recorded"}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 text-danger">
      <XCircle className="h-3.5 w-3.5" /> Failed: {o.error ?? "unknown error"}
    </span>
  );
}

/** The outcome of an approved draft_email handoff. The worker runs it a few seconds after approval, so poll until it leaves "queued". */
export function OutboundResult({ handoffId }: { handoffId: number }) {
  const res = useApi<Outbound[]>(() => listOutbound(handoffId), [], [handoffId], { live: anyEvent, pollMs: 5000 });
  const rows = [...res.data].sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
  const pending = res.data.length === 0 || res.data.some((o) => o.status === "queued");

  // Light poll until the worker has run it (also covers a missed socket event).
  useEffect(() => {
    if (!pending) return;
    const t = setInterval(res.refresh, 4000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending, handoffId]);

  if (res.forbidden || res.unavailable || res.error) return null;
  return (
    <section aria-label="Outbound result" className="mt-6 rounded-md border border-line bg-surface shadow-card">
      <div className="flex items-center gap-2 border-b border-line-subtle px-5 py-3.5">
        <Mail className="h-4 w-4 text-muted" />
        <h2 className="font-serif text-[18px] text-fg">Outbound result</h2>
      </div>
      {rows.length === 0 ? (
        <p className="flex items-center gap-1.5 px-5 py-3 text-[13px] text-muted">
          {res.loading ? "Checking…" : <><Hourglass className="h-3.5 w-3.5" /> Nothing sent for this decision (yet). If it was approved, the worker picks it up in a few seconds.</>}
        </p>
      ) : (
        <ul className="divide-y divide-line-subtle">
          {rows.map((o) => (
            <li key={o.id} className="space-y-1 px-5 py-3 text-[13px]">
              <ResultLine o={o} />
              <div className="flex flex-wrap items-center gap-x-3 text-[12px] text-muted">
                <span className="font-mono">{o.to_email}</span>
                {o.subject ? <span className="truncate">“{o.subject}”</span> : null}
                <Badge tone="neutral">{MODE_LABEL[o.mode] ?? o.mode}</Badge>
                <span className="num font-mono text-[11px]">{formatDateTime(o.completed_at ?? o.created_at)}</span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

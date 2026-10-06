"use client";

import { Anchor, Link2Off, Loader2, ShieldCheck } from "lucide-react";
import { apiFetch } from "@/shared/api/client";
import { anyEvent } from "@/shared/api/events";
import { cx, formatDateTime } from "@/shared/lib/format";
import { useApi } from "@/shared/lib/useApi";
import { Tip } from "@/shared/ui/primitives";

export type AuditAnchor = { head_id: number | null; head_hash: string | null; written_at: string | null; ok: boolean };
/** AuditVerifyOut (api/schemas/deals.py). */
export type AuditVerify = { ok: boolean; broken_at: number | null; anchor: AuditAnchor };

export const getAuditVerify = () => apiFetch<AuditVerify>("/api/audit/verify");

/** Hash-chain status pill (Verified / Broken at #N) plus the local anchor. Click to re-verify. */
export function AuditChainStatus() {
  const { data, loading, error, refresh } = useApi<AuditVerify | null>(getAuditVerify, null, [], {
    live: anyEvent,
    pollMs: 60000,
  });
  let tone = "border-line bg-well text-muted";
  let icon = <Loader2 className="h-3.5 w-3.5 animate-spin" />;
  let text = "Verifying chain…";
  let tip: React.ReactNode = "Recomputing SHA-256 over every audit row";
  if (error) {
    text = "Chain check failed";
    tone = "border-warning-border bg-warning-soft text-warning";
    icon = <Link2Off className="h-3.5 w-3.5" />;
    tip = error;
  } else if (!loading && data) {
    if (data.ok) {
      text = "Chain verified";
      tone = "border-success-border bg-success-soft text-success";
      icon = <ShieldCheck className="h-3.5 w-3.5" />;
      tip = "Every row’s hash matches its predecessor. Click to re-verify.";
    } else {
      text = `Broken at #${data.broken_at ?? "?"}`;
      tone = "border-danger-border bg-danger-soft text-danger";
      icon = <Link2Off className="h-3.5 w-3.5" />;
      tip = "A row was altered after it was written. Escalate to compliance.";
    }
  }
  const anchor = data ? data.anchor : null;
  return (
    <div className="flex items-center gap-2">
      <Tip label={tip}>
        <button
          onClick={refresh}
          className={cx("inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-[12px] font-medium transition-opacity hover:opacity-85", tone)}
        >
          {icon}
          {text}
        </button>
      </Tip>
      {anchor ? <AnchorChip anchor={anchor} /> : null}
    </div>
  );
}

function AnchorChip({ anchor }: { anchor: AuditAnchor }) {
  const written = anchor.written_at ? formatDateTime(anchor.written_at) : null;
  return (
    <Tip
      label={
        <span className="block max-w-[300px] leading-relaxed">
          {anchor.ok ? "The local anchor file matches the chain head." : "The anchor file does not match the chain — the head may have been rewritten."}
          {anchor.head_hash ? (
            <span className="mt-1 block font-mono text-[11px] text-muted">
              head #{anchor.head_id ?? "?"} · {anchor.head_hash.slice(0, 16)}…
            </span>
          ) : null}
          {written ? <span className="block text-[11px] text-muted">written {written}</span> : null}
        </span>
      }
    >
      <span
        tabIndex={0}
        className={cx(
          "inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-[12px] font-medium outline-none focus-visible:ring-2 focus-visible:ring-accent/50",
          anchor.ok ? "border-line bg-surface text-fg-2" : "border-danger-border bg-danger-soft text-danger",
        )}
      >
        <Anchor className="h-3.5 w-3.5" />
        {anchor.ok ? "Anchor matches" : "Anchor mismatch"}
        {anchor.head_id != null ? <span className="num font-mono text-[11px] text-muted">#{anchor.head_id}</span> : null}
      </span>
    </Tip>
  );
}

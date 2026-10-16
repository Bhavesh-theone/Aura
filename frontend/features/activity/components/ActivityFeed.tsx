"use client";

import { ArrowUpRight, Bot, Search } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { cx, formatDateTime, formatStamp, parseApiDate, titleCase } from "@/shared/lib/format";
import { PageHeader } from "@/shared/ui/PageHeader";
import { Avatar, Segmented, Tip, inputCls } from "@/shared/ui/primitives";
import { EmptyState, InlineError, Skel } from "@/shared/ui/States";
import { useDeals } from "@/features/deals/hooks";
import { useActivity } from "../hooks";
import { isRejection, isSystemActor, linkFor, payloadFacts, toneFor, traceIdFor, verbFor } from "../present";
import type { ActivityEntry } from "../types";
import { AuditChainStatus } from "./AuditChainStatus";

const dotTone: Record<string, string> = {
  accent: "bg-accent",
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-danger",
  info: "bg-info",
  neutral: "bg-line-strong",
};

export function ActorChip({ actor }: { actor: string }) {
  const system = isSystemActor(actor);
  return (
    <span
      className={cx(
        "inline-flex h-5 shrink-0 items-center gap-1.5 rounded-full pr-2 text-[12px] font-medium",
        system ? "bg-accent-soft pl-1.5 text-accent" : "bg-well pl-0.5 text-fg",
      )}
    >
      {system ? <Bot className="h-3 w-3" /> : <Avatar name={actor} size={16} />}
      {system ? actor : titleCase(actor)}
    </span>
  );
}

function dayLabel(iso: string) {
  const d = parseApiDate(iso);
  const today = new Date();
  const y = new Date(Date.now() - 86400000);
  const same = (a: Date, b: Date) => a.toDateString() === b.toDateString();
  if (same(d, today)) return "Today";
  if (same(d, y)) return "Yesterday";
  return new Intl.DateTimeFormat("en-IN", { weekday: "short", day: "numeric", month: "short" }).format(d);
}

function Row({ entry, dealRef }: { entry: ActivityEntry; dealRef?: string }) {
  const tone = toneFor(entry.action, entry.payload);
  const facts = payloadFacts(entry.payload);
  const link = linkFor(entry);
  const traceId = traceIdFor(entry.payload);
  return (
    <li className="group relative grid grid-cols-[64px_20px_1fr] gap-x-3 py-2.5">
      <Tip label={formatDateTime(entry.created_at)} side="left">
        <span className="num pt-0.5 font-mono text-[12px] text-muted">{formatStamp(entry.created_at).split(" ").slice(2).join(" ") || formatStamp(entry.created_at)}</span>
      </Tip>
      <span className="relative flex justify-center pt-[7px]">
        <span className={cx("relative z-10 h-2 w-2 rounded-full ring-4 ring-canvas", dotTone[tone])} />
      </span>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px]">
          <ActorChip actor={entry.actor} />
          <span className={cx(isRejection(entry.action, entry.payload) ? "font-medium text-danger" : "text-fg-2")}>{verbFor(entry.action, entry.payload)}</span>
          {entry.deal_id ? <span className="font-mono text-[11px] text-muted">{dealRef ?? `DEAL-${entry.deal_id}`}</span> : null}
          {entry.job_id ? <span className="font-mono text-[11px] text-muted">JOB-{entry.job_id}</span> : null}
          {link ? (
            <Link href={link.href} className="inline-flex items-center gap-0.5 rounded-xs text-[11px] text-muted hover:text-fg">
              {link.label}
              <ArrowUpRight className="h-3 w-3" />
            </Link>
          ) : null}
          {traceId ? (
            <Link href={`/traces/${traceId}`} className="inline-flex items-center gap-0.5 rounded-xs text-[11px] text-muted hover:text-fg">
              Trace
              <ArrowUpRight className="h-3 w-3" />
            </Link>
          ) : null}
          <Tip label={entry.row_hash ? <span className="font-mono">{entry.prev_hash ? `${entry.prev_hash.slice(0, 8)} → ` : ""}{entry.row_hash.slice(0, 16)}</span> : `Audit row ${entry.id}`} side="left">
            <span className="ml-auto font-mono text-[11px] text-muted">#{entry.id}</span>
          </Tip>
        </div>
        {facts.length ? (
          <dl className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-[12px]">
            {facts.map((f) => (
              <div key={f.key} className="flex min-w-0 max-w-full items-baseline gap-1.5">
                <dt className="shrink-0 text-muted">{f.key}</dt>
                <dd className={cx("truncate text-fg-2", f.mono && "num font-mono text-[11px]")}>{f.value}</dd>
              </div>
            ))}
          </dl>
        ) : null}
      </div>
    </li>
  );
}

export function ActivityFeed() {
  const { activity, loading, error, refresh } = useActivity();
  const { deals } = useDeals();
  const refs = useMemo(() => new Map(deals.map((d) => [d.id, d.external_id])), [deals]);
  const [query, setQuery] = useState("");
  const [who, setWho] = useState<"all" | "human" | "system">("all");

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = [...activity]
      .sort((a, b) => (a.created_at < b.created_at ? 1 : -1))
      .filter((e) => (who === "all" ? true : who === "system" ? isSystemActor(e.actor) : !isSystemActor(e.actor)))
      .filter((e) => (!q ? true : (e.actor + " " + e.action + " " + verbFor(e.action, e.payload) + " " + JSON.stringify(e.payload)).toLowerCase().includes(q)));
    const out: { day: string; items: ActivityEntry[] }[] = [];
    for (const e of list) {
      const d = dayLabel(e.created_at);
      if (out.at(-1)?.day !== d) out.push({ day: d, items: [] });
      out.at(-1)!.items.push(e);
    }
    return out;
  }, [activity, query, who]);

  return (
    <div className="flex flex-1 flex-col pb-12">
      <PageHeader
        title="Activity"
        description="Every agent step and human decision, in order. Each row is hash-chained to the one before it."
        actions={<AuditChainStatus />}
      />
      <div className="flex flex-wrap items-center gap-2 px-8 pb-4">
        <div className="relative w-72">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Filter activity"
            placeholder="Filter by actor, action or detail…"
            className={cx(inputCls, "h-7 pl-8 text-[12px]")}
          />
        </div>
        <Segmented
          label="Actor type"
          value={who}
          onChange={setWho}
          options={[
            { value: "all", label: "All" },
            { value: "human", label: "People" },
            { value: "system", label: "Agents" },
          ]}
        />
      </div>

      <div className="px-8">
        {error ? <InlineError message={error} onRetry={refresh} className="mb-4" /> : null}
        {loading && activity.length === 0 ? (
          <div className="max-w-4xl space-y-4 pt-2" aria-busy="true">
            {Array.from({ length: 7 }).map((_, i) => (
              <div key={i} className="grid grid-cols-[64px_20px_1fr] gap-x-3">
                <Skel className="h-3 w-16" />
                <Skel className="mx-auto h-2 w-2 rounded-full" />
                <div className="space-y-2">
                  <Skel className="h-3" style={{ width: `${40 + ((i * 13) % 30)}%` }} />
                  <Skel className="h-2.5 w-1/3" />
                </div>
              </div>
            ))}
          </div>
        ) : groups.length === 0 ? (
          <EmptyState
            title={query || who !== "all" ? "No activity matches" : "The ledger is empty"}
            description={query || who !== "all" ? "Try a different actor or clear the filter." : "Agent steps, stage moves and decisions will appear here as they happen."}
          />
        ) : (
          <div className="max-w-4xl">
            {groups.map((g) => (
              <section key={g.day} className="mb-4">
                <h2 className="sticky top-12 z-10 -mx-2 bg-canvas/90 px-2 py-2 text-[12px] font-medium text-fg-2 backdrop-blur">
                  {g.day} <span className="num ml-1 font-mono text-[11px] font-normal text-muted">{g.items.length}</span>
                </h2>
                <ol className="relative">
                  <span aria-hidden className="absolute bottom-3 left-[86px] top-3 w-px bg-line" />
                  {g.items.map((e) => (
                    <Row key={e.id} entry={e} dealRef={e.deal_id ? refs.get(e.deal_id) : undefined} />
                  ))}
                </ol>
              </section>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

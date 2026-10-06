"use client";

import { AlarmClock, ArrowRight, ArrowUpRight } from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";
import { ActorChip } from "@/features/activity/components/ActivityFeed";
import { linkFor, verbFor } from "@/features/activity/present";
import { useAuth } from "@/features/auth/hooks";
import { CLASS_LABEL } from "@/features/deals/components/ui";
import { useDeals } from "@/features/deals/hooks";
import { STAGES, isTerminal } from "@/features/deals/types";
import { isEscalated, listHandoffs, type Handoff } from "@/features/handoffs/api";
import { cx, humanize, parseApiDate, shortAgo, stageLabel, timeUntil, titleCase } from "@/shared/lib/format";
import { anyEvent, handoffEvents } from "@/shared/api/events";
import { useApi } from "@/shared/lib/useApi";
import { Badge, Card, CardHeader } from "@/shared/ui/primitives";
import { Sparkline } from "@/shared/ui/Sparkline";
import { EmptyState, InlineError, Skel } from "@/shared/ui/States";
import { getDashboardSummary, type DashboardSummary } from "../api";

const DAY = 86400000;

/** Count events per bucket over the last n buckets (oldest → newest). */
function series(dates: string[], buckets: number, size: number, cumulative = false) {
  const now = Date.now();
  const out = Array<number>(buckets).fill(0);
  let before = 0;
  for (const iso of dates) {
    const t = parseApiDate(iso).getTime();
    if (Number.isNaN(t)) continue;
    const idx = buckets - 1 - Math.floor((now - t) / size);
    if (idx < 0) before += 1;
    else if (idx < buckets) out[idx] += 1;
  }
  if (!cumulative) return out;
  let run = before;
  return out.map((v) => (run += v));
}

const FUNNEL_LABEL: Record<string, string> = { BID_AUCTION: "Auction", CONDITIONS_PRECEDENT: "Conditions", DOCUMENTATION: "Docs" };

const CLASS_COLORS =["var(--accent)", "var(--info)", "var(--success)", "var(--warning)", "#7a5af8", "var(--text-muted)", "var(--danger)"];

function Kpi({
  label,
  value,
  foot,
  href,
  children,
  tone,
}: {
  label: string;
  value: React.ReactNode;
  foot?: React.ReactNode;
  href: string;
  children?: React.ReactNode;
  tone?: "danger";
}) {
  return (
    <Link href={href} className="group flex flex-col rounded-md border border-line bg-surface p-4 shadow-card transition-colors duration-[var(--dur-1)] hover:border-line-strong">
      <div className="flex items-center gap-2 text-[12px] text-muted">
        {label}
        <ArrowUpRight className="ml-auto h-3.5 w-3.5 text-faint opacity-0 transition-opacity group-hover:opacity-100" />
      </div>
      <div className="mt-2 flex items-end justify-between gap-3">
        <span className={cx("num font-serif text-[36px] leading-none", tone === "danger" ? "text-danger" : "text-fg")}>{value}</span>
        <span className="pb-1">{children}</span>
      </div>
      {foot ? <div className="mt-auto pt-3 text-[12px] text-muted">{foot}</div> : null}
    </Link>
  );
}

function KpiSkeleton() {
  return (
    <div className="rounded-md border border-line bg-surface p-4 shadow-card">
      <Skel className="h-3 w-20" />
      <Skel className="mt-3 h-8 w-14" />
      <Skel className="mt-4 h-2.5 w-32" />
    </div>
  );
}

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

export function DashboardOverview() {
  const { user } = useAuth();
  const summary = useApi<DashboardSummary | null>(getDashboardSummary, null, [], { live: anyEvent });
  const { deals } = useDeals();
  const handoffs = useApi<Handoff[]>(listHandoffs, [], [], { live: handoffEvents });

  const s = summary.data;
  const loading = summary.loading && !summary.data;
  const recent = useMemo(
    () => [...(s?.recent_activity ?? [])].sort((a, b) => (a.created_at < b.created_at ? 1 : -1)).slice(0, 8),
    [s?.recent_activity],
  );

  const openTrend = useMemo(() => series(deals.filter((d) => !isTerminal(d.stage)).map((d) => d.opened_at), 12, 7 * DAY, true), [deals]);
  const decisionTrend = useMemo(() => series(handoffs.data.map((h) => h.created_at), 14, DAY), [handoffs.data]);

  const classes = Object.entries(s?.deals_by_class ?? {}).filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1]);
  const classTotal = classes.reduce((a, [, n]) => a + n, 0) || 1;
  const stageCounts = (STAGES as readonly string[]).map((st) => s?.deals_by_stage?.[st] ?? 0);
  const stageMax = Math.max(...stageCounts, 1);
  const ended = s?.ended_deals ?? 0;
  const closed = s?.closed_deals ?? 0;
  const escalatingSoon = handoffs.data.filter((h) => {
    const at = h.context_package?.if_you_do_nothing?.auto_escalate_at ?? h.auto_escalate_at;
    return at && parseApiDate(at).getTime() - Date.now() < DAY;
  }).length;

  const name = titleCase(user?.username ?? "there");
  const today = new Intl.DateTimeFormat("en-IN", { weekday: "long", day: "numeric", month: "long" }).format(new Date());

  return (
    <div className="flex-1 px-8 pb-14 pt-7">
      <div className="flex flex-wrap items-end gap-4">
        <div>
          <p className="text-[12px] text-muted">{today}</p>
          <h1 className="mt-1 font-serif text-[28px] leading-tight text-fg">
            {greeting()}, {name}
          </h1>
          <p className="mt-1 text-[13px] text-muted">
            {s
              ? s.decisions_waiting > 0
                ? `${s.decisions_waiting} decision${s.decisions_waiting === 1 ? "" : "s"} waiting on the desk${escalatingSoon ? ` — ${escalatingSoon} escalate within 24 hours` : ""}.`
                : "Nothing is waiting on you. The agents are running clean."
              : "Loading the desk…"}
          </p>
        </div>
      </div>

      {summary.error ? <InlineError className="mt-5" message={summary.error} onRetry={summary.refresh} /> : null}

      {/* KPI bento */}
      <div className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {loading || !s ? (
          [0, 1, 2, 3].map((i) => <KpiSkeleton key={i} />)
        ) : (
          <>
            <Kpi label="Open deals" value={s.open_deals} href="/deals" foot={<>Cumulative, last 12 weeks</>}>
              <Sparkline values={openTrend} label="Open deals, last 12 weeks" />
            </Kpi>
            <Link href="/deals" className="group block rounded-md border border-line bg-surface p-4 shadow-card transition-colors hover:border-line-strong">
              <div className="flex items-center text-[12px] text-muted">
                Deals by class
                <ArrowUpRight className="ml-auto h-3.5 w-3.5 text-faint opacity-0 transition-opacity group-hover:opacity-100" />
              </div>
              <div className="mt-3 flex h-2 overflow-hidden rounded-full bg-control-active">
                {classes.map(([c, n], i) => (
                  <span key={c} style={{ width: `${(n / classTotal) * 100}%`, background: CLASS_COLORS[i % CLASS_COLORS.length] }} className="h-full border-r-2 border-surface last:border-0" />
                ))}
              </div>
              <ul className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1.5">
                {classes.slice(0, 6).map(([c, n], i) => (
                  <li key={c} className="flex items-center gap-1.5 text-[12px]">
                    <span className="h-2 w-2 rounded-[2px]" style={{ background: CLASS_COLORS[i % CLASS_COLORS.length] }} />
                    <span className="truncate text-fg-2">{CLASS_LABEL[c] ?? c}</span>
                    <span className="num ml-auto font-mono text-[11px] text-fg">{n}</span>
                  </li>
                ))}
                {classes.length === 0 ? <li className="text-[12px] text-muted">No open deals</li> : null}
              </ul>
            </Link>
            <Kpi
              label="Decisions waiting"
              value={s.decisions_waiting}
              href="/decisions"
              foot={escalatingSoon ? <span className="text-warning">{escalatingSoon} escalate within 24h</span> : "Raised per day, last 14 days"}
            >
              <Sparkline values={decisionTrend} color="var(--warning)" label="Decisions raised per day" />
            </Kpi>
            <Kpi
              label="Diligence blockers open"
              value={s.blockers_open}
              tone={s.blockers_open ? "danger" : undefined}
              href="/deals"
              foot={
                s.blockers_open
                  ? `Holding ${s.deals_by_stage.DILIGENCE ?? 0} deal${(s.deals_by_stage.DILIGENCE ?? 0) === 1 ? "" : "s"} at Diligence`
                  : "No deal is blocked"
              }
            >
              {s.blockers_open ? (
                <span className="flex gap-[3px]" aria-hidden>
                  {Array.from({ length: Math.min(s.blockers_open, 8) }).map((_, i) => (
                    <span key={i} className="h-5 w-1.5 rounded-[2px] bg-danger/80" />
                  ))}
                </span>
              ) : null}
            </Kpi>
          </>
        )}
      </div>

      {/* Stage funnel strip */}
      <Card className="mt-3">
        <CardHeader
          title="Stage funnel"
          aside={
            <span className="text-[12px] text-muted">
              {closed ? <>{closed} closed · </> : null}
              {ended ? <>{ended} ended · </> : null}
              <Link href="/deals" className="text-fg-2 hover:text-fg">All deals</Link>
            </span>
          }
        />
        <div className="grid grid-cols-6 gap-px overflow-hidden rounded-b-md bg-line-subtle lg:grid-cols-12">
          {(STAGES as readonly string[]).map((st, i) => {
            const n = stageCounts[i];
            return (
              <Link key={st} href="/deals" className="group flex flex-col bg-surface px-3 pb-3.5 pt-3 transition-colors hover:bg-well" title={`${stageLabel(st)}: ${n}`}>
                <span className="font-mono text-[11px] text-muted">{String(i + 1).padStart(2, "0")}</span>
                <span className={cx("num mt-1.5 font-serif text-[28px] leading-none", n ? "text-fg" : "text-muted")}>{loading ? "–" : n}</span>
                <span className={cx("mt-2 truncate text-[12px]", n ? "text-fg-2" : "text-muted")}>{FUNNEL_LABEL[st] ?? stageLabel(st)}</span>
                <span className="mt-2.5 h-[3px] w-full overflow-hidden rounded-full bg-control-active">
                  <span className="block h-full rounded-full bg-accent transition-[width]" style={{ width: `${(n / stageMax) * 100}%` }} />
                </span>
              </Link>
            );
          })}
        </div>
      </Card>

      <div className="mt-3 grid grid-cols-1 items-start gap-3 xl:grid-cols-[1.1fr_1fr]">
        {/* Recent decisions */}
        <Card>
          <CardHeader
            title="Decisions waiting"
            aside={
              <Link href="/decisions" className="inline-flex items-center gap-1 text-[12px] text-fg-2 hover:text-fg">
                Open inbox <ArrowRight className="h-3 w-3" />
              </Link>
            }
          />
          {handoffs.loading && handoffs.data.length === 0 ? (
            <div className="space-y-3 p-4">
              {[0, 1, 2].map((i) => (
                <div key={i}>
                  <Skel className="h-2.5 w-24" />
                  <Skel className="mt-2 h-3 w-4/5" />
                </div>
              ))}
            </div>
          ) : handoffs.data.length === 0 ? (
            <EmptyState compact title="Inbox zero" description="No agent is waiting on a human call right now." />
          ) : (
            <ul>
              {handoffs.data.slice(0, 5).map((h) => {
                const at = h.context_package?.if_you_do_nothing?.auto_escalate_at ?? h.auto_escalate_at;
                const deal = deals.find((d) => d.id === h.deal_id);
                return (
                  <li key={h.id} className="border-b border-line-subtle last:border-0">
                    <Link href="/decisions" className="block px-4 py-3 transition-colors hover:bg-well">
                      <div className="flex items-center gap-2 text-[11px] text-muted">
                        {isEscalated(h) ? <Badge tone="danger" className="h-[18px]">Escalated</Badge> : null}
                        <Badge className="h-[18px]">{humanize(h.trigger)}</Badge>
                        {deal ? <span className="truncate">{deal.name}</span> : null}
                        <span className="num ml-auto shrink-0 font-mono">{shortAgo(h.created_at)}</span>
                      </div>
                      <p className="mt-1.5 line-clamp-2 text-[13px] leading-snug text-fg">{h.context_package?.decision_required?.question ?? "A decision is needed"}</p>
                      {at && !isEscalated(h) ? (
                        <p className="mt-1 inline-flex items-center gap-1 text-[11px] text-warning">
                          <AlarmClock className="h-3 w-3" /> auto-escalates {timeUntil(at) === "now" ? "now" : `in ${timeUntil(at)}`}
                        </p>
                      ) : null}
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>

        {/* Recent activity */}
        <Card>
          <CardHeader
            title="Recent activity"
            aside={
              <Link href="/activity" className="inline-flex items-center gap-1 text-[12px] text-fg-2 hover:text-fg">
                Audit trail <ArrowRight className="h-3 w-3" />
              </Link>
            }
          />
          {recent.length === 0 ? (
            loading ? (
              <div className="space-y-3 p-4">
                {[0, 1, 2, 3].map((i) => <Skel key={i} className="h-3" style={{ width: `${80 - i * 10}%` }} />)}
              </div>
            ) : (
              <EmptyState compact title="Quiet so far" description="Stage moves, agent steps and decisions will show up here." />
            )
          ) : (
            <ul className="py-1">
              {recent.map((e) => {
                const link = linkFor(e);
                const body = (
                  <>
                    <ActorChip actor={e.actor} />
                    <span className="truncate text-fg-2">{verbFor(e.action, e.payload)}</span>
                    <span className="num ml-auto shrink-0 font-mono text-[11px] text-muted">{shortAgo(e.created_at)}</span>
                  </>
                );
                return (
                  <li key={e.id}>
                    {link ? (
                      <Link href={link.href} className="flex h-9 items-center gap-2 px-4 text-[13px] transition-colors hover:bg-well">{body}</Link>
                    ) : (
                      <div className="flex h-9 items-center gap-2 px-4 text-[13px]">{body}</div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}

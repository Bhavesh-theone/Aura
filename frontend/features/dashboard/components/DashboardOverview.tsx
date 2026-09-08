"use client";

import Link from "next/link";
import { cx, formatINR, timeAgo, titleCase } from "@/shared/lib/format";
import { ErrorBanner, OfflineBanner } from "@/shared/ui/shell/Panes";
import { CategoryTag, StatusPill } from "@/shared/ui/Tag";
import { ChevronRight, ClockIcon } from "@/shared/ui/icons";
import { useApprovals } from "@/features/approvals/provider";
import { useJobs } from "@/features/jobs/hooks";
import { useActivity } from "@/features/activity/hooks";
import { useDeals } from "@/features/deals/hooks";
import { useAuth } from "@/features/auth/hooks";

function StatCard({
  label,
  value,
  hint,
  href,
  accent,
}: {
  label: string;
  value: string | number;
  hint: string;
  href: string;
  accent: string;
}) {
  return (
    <Link
      href={href}
      className="group rounded-xl border border-line bg-surface p-4 transition-colors hover:border-navy/20 hover:bg-[#fcfdff]"
    >
      <div className="flex items-center gap-2">
        <span className={cx("h-2 w-2 rounded-full", accent)} />
        <span className="text-[11px] font-semibold uppercase tracking-[0.09em] text-muted">{label}</span>
        <ChevronRight className="ml-auto h-4 w-4 text-line transition-colors group-hover:text-muted" />
      </div>
      <p className="mt-3 text-[30px] font-semibold leading-none tabular-nums text-ink">{value}</p>
      <p className="mt-2 text-[12px] text-muted">{hint}</p>
    </Link>
  );
}

export function DashboardOverview() {
  const { user } = useAuth();
  const { approvals, offline, error, refresh } = useApprovals();
  const { jobs } = useJobs();
  const { activity } = useActivity();
  const { deals, offline: dealsOffline } = useDeals();

  const pending = approvals.filter((a) => a.status === "pending");
  // Backend JobStatus is pending|running|awaiting_approval|complete|failed|rejected.
  // "queued" is a *segment* status and never appears on a job, so matching it
  // here silently under-counted every freshly submitted job as zero.
  const running = jobs.filter((j) => j.status === "running" || j.status === "pending");
  const waiting = jobs.filter((j) => j.status === "awaiting_approval");
  const pipeline = deals.reduce((sum, d) => sum + (d.value_inr || 0), 0);
  const recent = [...activity].sort((a, b) => (a.created_at < b.created_at ? 1 : -1)).slice(0, 7);

  const moneyAtRisk = pending
    .filter((a) => a.category === "money")
    .reduce((sum, a) => {
      const args = a.proposed_action.arguments ?? {};
      const amount = Object.entries(args).find(([k]) => /(amount_inr|total_inr)/i.test(k))?.[1];
      return sum + (typeof amount === "number" ? amount : 0);
    }, 0);

  return (
    <>
      {offline ? <OfflineBanner /> : null}
      {error ? <ErrorBanner message={error} onRetry={refresh} /> : null}
      <div className="yuki-scroll min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-6xl px-8 py-7">
          <h1 className="text-[20px] font-semibold text-ink">
            Good day, {titleCase(user?.username ?? "there")}
          </h1>
          <p className="mt-1 text-[13px] text-muted">
            {pending.length > 0
              ? pending.length + " agent actions are held for your decision."
              : "Nothing is waiting on you. The crew is running clean."}
          </p>

          <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard
              label="Pending approvals"
              value={pending.length}
              hint={
                moneyAtRisk > 0
                  ? formatINR(moneyAtRisk) + " of fund movement held"
                  : "No fund movement held"
              }
              href="/approvals"
              accent="bg-amber"
            />
            <StatCard
              label="Running jobs"
              value={running.length}
              hint={waiting.length + " more blocked on an approval"}
              href="/jobs"
              accent="bg-[#4c6ef5]"
            />
            <StatCard
              label="Recent activity"
              value={activity.length}
              hint="Audit events in the current window"
              href="/activity"
              accent="bg-cat-money"
            />
            <StatCard
              label={dealsOffline ? "Deals (sample)" : "Live deals"}
              value={deals.length}
              hint={
                dealsOffline
                  ? "Sample data — no deals API yet"
                  : formatINR(pipeline) + " aggregate value"
              }
              href="/deals"
              accent="bg-cat-legal"
            />
          </div>

          <div className="mt-7 grid items-start gap-5 lg:grid-cols-[1.15fr_1fr]">
            <section className="rounded-xl border border-line bg-surface">
              <div className="flex items-center justify-between border-b border-line px-4 py-3">
                <h2 className="text-[13px] font-semibold text-ink">Needs your decision</h2>
                <Link href="/approvals" className="text-[12px] font-medium text-[#1c62d0] hover:underline">
                  Open queue
                </Link>
              </div>
              {pending.length === 0 ? (
                <p className="px-4 py-8 text-center text-[13px] text-muted">Queue clear.</p>
              ) : (
                <ul>
                  {pending.slice(0, 5).map((approval) => (
                    <li key={approval.id} className="border-b border-line-soft last:border-0">
                      <Link
                        href="/approvals"
                        className="flex items-start gap-3 px-4 py-3 transition-colors hover:bg-[#f9fbfe]"
                      >
                        <CategoryTag category={approval.category} className="mt-0.5 shrink-0" />
                        <span className="min-w-0 flex-1">
                          <span className="line-clamp-2 block text-[13px] leading-snug text-ink">
                            {approval.proposed_action.summary}
                          </span>
                          <span className="mt-1 block text-[11px] text-muted">
                            {approval.requested_by ?? "Agent"}
                            {approval.created_at ? " · " + timeAgo(approval.created_at) : ""}
                          </span>
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <div className="space-y-5">
              <section className="rounded-xl border border-line bg-surface">
                <div className="flex items-center justify-between border-b border-line px-4 py-3">
                  <h2 className="text-[13px] font-semibold text-ink">Jobs in flight</h2>
                  <Link href="/jobs" className="text-[12px] font-medium text-[#1c62d0] hover:underline">
                    All jobs
                  </Link>
                </div>
                {jobs.slice(0, 4).map((job) => (
                  <div
                    key={job.id}
                    className="flex items-center gap-3 border-b border-line-soft px-4 py-2.5 last:border-0"
                  >
                    <span className="font-mono text-[11px] text-muted">JOB-{job.id}</span>
                    <span className="min-w-0 flex-1 truncate text-[12.5px] text-ink">
                      {String(job.inputs?.brief ?? "Job " + job.id)}
                    </span>
                    <StatusPill status={job.status} />
                  </div>
                ))}
              </section>

              <section className="rounded-xl border border-line bg-surface">
                <div className="flex items-center justify-between border-b border-line px-4 py-3">
                  <h2 className="text-[13px] font-semibold text-ink">Latest activity</h2>
                  <Link href="/activity" className="text-[12px] font-medium text-[#1c62d0] hover:underline">
                    Audit feed
                  </Link>
                </div>
                <ul className="px-4 py-1.5">
                  {recent.map((entry) => (
                    <li key={entry.id} className="flex items-center gap-2.5 py-1.5 text-[12.5px]">
                      <ClockIcon className="h-3.5 w-3.5 shrink-0 text-line" />
                      <span className="font-medium text-ink">{entry.actor}</span>
                      <span className="truncate text-muted">{titleCase(entry.action)}</span>
                      <span className="ml-auto shrink-0 text-[11px] text-muted">
                        {timeAgo(entry.created_at)}
                      </span>
                    </li>
                  ))}
                </ul>
              </section>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

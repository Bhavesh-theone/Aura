"use client";

import { useMemo, useState } from "react";
import { cx, formatDateTime, timeAgo, titleCase } from "@/shared/lib/format";
import { ErrorBanner, OfflineBanner } from "@/shared/ui/shell/Panes";
import { EmptyState, SkeletonRows } from "@/shared/ui/States";
import { ActivityIcon, SearchIcon } from "@/shared/ui/icons";
import { useActivity } from "../hooks";

const actionAccent: Record<string, string> = {
  approval_required: "bg-amber",
  approval_decided: "bg-cat-money",
  job_submitted: "bg-[#4c6ef5]",
  job_complete: "bg-cat-money",
  job_failed: "bg-cat-outbound",
  segment_complete: "bg-[#adb5bd]",
  approval_requested: "bg-amber",
  job_completed: "bg-cat-money",
  segment_completed: "bg-[#adb5bd]",
};

function summarise(payload: Record<string, unknown> | null): string {
  if (!payload) return "";
  return Object.entries(payload)
    .map(([k, v]) => titleCase(k) + ": " + (typeof v === "object" ? JSON.stringify(v) : String(v)))
    .join("  ·  ");
}

export function ActivityFeed() {
  const { activity, loading, offline, error, refresh } = useActivity();
  const [query, setQuery] = useState("");

  const entries = useMemo(() => {
    const q = query.trim().toLowerCase();
    return [...activity]
      .sort((a, b) => (a.created_at < b.created_at ? 1 : -1))
      .filter((e) =>
        !q
          ? true
          : (e.actor + " " + e.action + " " + JSON.stringify(e.payload ?? {}))
              .toLowerCase()
              .includes(q),
      );
  }, [activity, query]);

  return (
    <>
      {offline ? <OfflineBanner /> : null}
      {error ? <ErrorBanner message={error} onRetry={refresh} /> : null}
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="flex shrink-0 items-center gap-4 border-b border-line bg-surface px-6 py-3.5">
          <div>
            <h1 className="text-[15px] font-semibold text-ink">Activity</h1>
            <p className="text-[12px] text-muted">
              Every agent step and human decision, in order. This is the audit trail.
            </p>
          </div>
          <div className="relative ml-auto w-72">
            <SearchIcon className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Filter by actor, action or payload"
              className="w-full rounded-md border border-line bg-appbg py-1.5 pl-8 pr-3 text-[12.5px] text-ink outline-none transition-colors placeholder:text-muted/80 focus:border-navy/30 focus:bg-white"
            />
          </div>
        </div>

        <div className="yuki-scroll min-h-0 flex-1 overflow-y-auto px-6 py-5">
          {loading && entries.length === 0 ? (
            <SkeletonRows count={6} />
          ) : entries.length === 0 ? (
            <EmptyState
              className="py-20"
              icon={<ActivityIcon className="h-10 w-10" />}
              title="No activity"
              description="Agent steps and approval decisions will stream in here."
            />
          ) : (
            <ol className="mx-auto max-w-4xl">
              {entries.map((entry) => (
                <li key={entry.id} className="flex gap-4 border-b border-line-soft py-3.5 last:border-0">
                  <span
                    className={cx(
                      "mt-1.5 h-2 w-2 shrink-0 rounded-full",
                      actionAccent[entry.action] ?? "bg-line",
                    )}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-baseline gap-x-2.5">
                      <span className="text-[13px] font-semibold text-ink">{entry.actor}</span>
                      <span className="text-[13px] text-[#4a5261]">{titleCase(entry.action)}</span>
                      {entry.job_id ? (
                        <span className="font-mono text-[11px] text-muted">JOB-{entry.job_id}</span>
                      ) : null}
                      <span
                        className="ml-auto shrink-0 text-[11px] text-muted"
                        title={formatDateTime(entry.created_at)}
                      >
                        {timeAgo(entry.created_at)}
                      </span>
                    </div>
                    {entry.payload ? (
                      <p className="mt-1 truncate text-[12px] text-muted">{summarise(entry.payload)}</p>
                    ) : null}
                  </div>
                </li>
              ))}
            </ol>
          )}
        </div>
      </div>
    </>
  );
}

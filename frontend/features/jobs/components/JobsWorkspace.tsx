"use client";

import { useEffect, useMemo, useState } from "react";
import { cx, formatDateTime, timeAgo } from "@/shared/lib/format";
import { DetailPane, ErrorBanner, ListPane, OfflineBanner, ThreePane } from "@/shared/ui/shell/Panes";
import { EmptyState, SkeletonRows } from "@/shared/ui/States";
import { JobsIcon } from "@/shared/ui/icons";
import { StatusPill } from "@/shared/ui/Tag";
import { useActivity } from "@/features/activity/hooks";
import { titleCase } from "@/shared/lib/format";
import { useJobs } from "../hooks";
import { JobTimeline } from "./JobTimeline";
import type { Job, JobSegment } from "../types";
import type { ActivityEntry } from "@/features/activity/types";

const failedActions = new Set(["job_failed", "segment_failed"]);

/**
 * The API does not embed a segment timeline on the job, so when one is absent
 * we reconstruct it from the audit trail for that job.
 */
function segmentsFromActivity(job: Job, activity: ActivityEntry[]): JobSegment[] {
  return activity
    .filter((e) => e.job_id === job.id)
    .sort((a, b) => (a.created_at < b.created_at ? -1 : 1))
    .map((e) => {
      const payload = e.payload ?? {};
      const detail =
        typeof payload.summary === "string"
          ? payload.summary
          : Object.keys(payload).length > 0
            ? JSON.stringify(payload)
            : null;
      return {
        id: e.id,
        name: titleCase(e.action),
        agent: e.actor,
        status: failedActions.has(e.action) ? "failed" : "complete",
        started_at: e.created_at,
        finished_at: null,
        detail,
      };
    });
}

function briefOf(job: Job): string {
  const brief = job.inputs?.brief ?? job.inputs?.prompt ?? job.inputs?.task;
  if (typeof brief === "string") return brief;
  return JSON.stringify(job.inputs ?? {});
}

export function JobsWorkspace() {
  const { jobs, loading, offline, error, refresh } = useJobs();
  const { activity } = useActivity();
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const ordered = useMemo(
    () => [...jobs].sort((a, b) => (a.created_at < b.created_at ? 1 : -1)),
    [jobs],
  );

  useEffect(() => {
    if (ordered.length === 0) {
      setSelectedId(null);
      return;
    }
    if (selectedId === null || !ordered.some((j) => j.id === selectedId)) {
      setSelectedId(ordered[0].id);
    }
  }, [ordered, selectedId]);

  const selected = ordered.find((j) => j.id === selectedId) ?? null;
  // "queued" is a segment status, never a job status — jobs start as "pending".
  const active = ordered.filter((j) => j.status === "running" || j.status === "pending").length;

  return (
    <>
      {offline ? <OfflineBanner /> : null}
      {error ? <ErrorBanner message={error} onRetry={refresh} /> : null}
      <ThreePane>
        <ListPane title="Jobs" subtitle={active + " active"}>
          {loading && ordered.length === 0 ? (
            <SkeletonRows />
          ) : ordered.length === 0 ? (
            <EmptyState className="py-16" title="No jobs yet" description="Submitted jobs appear here." />
          ) : (
            <div className="space-y-2 p-3">
              {ordered.map((job) => (
                <button
                  key={job.id}
                  onClick={() => setSelectedId(job.id)}
                  className={cx(
                    "block w-full rounded-lg border px-3.5 py-3 text-left transition-colors",
                    job.id === selectedId
                      ? "border-navy/25 bg-white shadow-[0_1px_3px_rgba(27,36,54,0.08)] ring-1 ring-navy/10"
                      : "border-line bg-surface hover:bg-[#f7f9fc]",
                  )}
                >
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-[11px] text-muted">JOB-{job.id}</span>
                    <StatusPill status={job.status} className="ml-auto" />
                  </div>
                  <p className="mt-2 line-clamp-2 text-[13px] font-medium leading-[1.45] text-ink">
                    {briefOf(job)}
                  </p>
                  <p className="mt-2 text-[11px] text-muted">
                    {job.deal_id ? "Deal #" + job.deal_id + " · " : ""}
                    {timeAgo(job.created_at)}
                  </p>
                </button>
              ))}
            </div>
          )}
        </ListPane>

        <DetailPane>
          {selected ? (
            <div className="yuki-fade">
              <div className="border-b border-line px-7 pb-5 pt-6">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[11px] text-muted">JOB-{selected.id}</span>
                  <StatusPill status={selected.status} />
                </div>
                <h1 className="mt-3 text-[19px] font-semibold leading-snug text-ink">
                  {briefOf(selected)}
                </h1>
                <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-[12px] text-muted">
                  <span>Submitted {formatDateTime(selected.created_at)}</span>
                  {selected.deal_id ? (
                    <span>Deal #{selected.deal_id}</span>
                  ) : (
                    <span>No deal linked</span>
                  )}
                  {typeof selected.inputs?.requested_by === "string" ? (
                    <span>By {String(selected.inputs.requested_by)}</span>
                  ) : null}
                </div>
              </div>

              <div className="space-y-7 px-7 py-6">
                <section>
                  <h2 className="mb-3 text-[11px] font-semibold uppercase tracking-[0.1em] text-muted">
                    Segment timeline
                  </h2>
                  <JobTimeline
                    segments={
                      selected.segments && selected.segments.length > 0
                        ? selected.segments
                        : segmentsFromActivity(selected, activity)
                    }
                  />
                </section>

                <section>
                  <h2 className="mb-2.5 text-[11px] font-semibold uppercase tracking-[0.1em] text-muted">
                    Inputs
                  </h2>
                  <pre className="yuki-scroll overflow-x-auto rounded-lg border border-line bg-[#fcfdff] p-3.5 font-mono text-[11.5px] leading-relaxed text-[#40485a]">
                    {JSON.stringify(selected.inputs ?? {}, null, 2)}
                  </pre>
                </section>

                <section>
                  <h2 className="mb-2.5 text-[11px] font-semibold uppercase tracking-[0.1em] text-muted">
                    Result
                  </h2>
                  {selected.result ? (
                    <pre className="yuki-scroll overflow-x-auto rounded-lg border border-line bg-[#fcfdff] p-3.5 font-mono text-[11.5px] leading-relaxed text-[#40485a]">
                      {JSON.stringify(selected.result, null, 2)}
                    </pre>
                  ) : (
                    <p className="text-[13px] text-muted">
                      No result yet — the job is still in flight or waiting on an approval.
                    </p>
                  )}
                </section>
              </div>
            </div>
          ) : (
            <EmptyState
              icon={<JobsIcon className="h-12 w-12" />}
              title="No job selected"
              description="Choose a job to see its segment timeline, inputs and result."
            />
          )}
        </DetailPane>
      </ThreePane>
    </>
  );
}

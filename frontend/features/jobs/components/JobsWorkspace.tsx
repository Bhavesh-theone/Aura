"use client";

import { useEffect, useMemo, useState } from "react";
import { cx, formatDateTime, humanize, shortAgo, titleCase } from "@/shared/lib/format";
import { Badge, type Tone } from "@/shared/ui/primitives";
import { EmptyState, InlineError, Skel } from "@/shared/ui/States";
import { useActivity } from "@/features/activity/hooks";
import { verbFor } from "@/features/activity/present";
import { useJobs } from "../hooks";
import { JobTimeline } from "./JobTimeline";
import type { Job, JobSegment } from "../types";
import type { ActivityEntry } from "@/features/activity/types";

const failedActions = new Set(["segment_failed"]);

export const jobTone = (s: string): Tone =>
  s === "complete" ? "success" : s === "failed" || s === "rejected" ? "danger" : s === "awaiting_approval" ? "warning" : s === "running" ? "accent" : s === "pending" ? "info" : "neutral";

const STATUS_LABEL: Record<string, string> = {
  pending: "Queued",
  running: "Running",
  awaiting_approval: "Awaiting decision",
  complete: "Complete",
  failed: "Failed",
  rejected: "Rejected",
};
const statusLabel = (s: string) => STATUS_LABEL[s] ?? humanize(s);

/** The API does not embed a segment timeline on the job, so it is rebuilt from the job's audit rows. */
function segmentsFromActivity(job: Job, activity: ActivityEntry[]): JobSegment[] {
  return activity
    .filter((e) => e.job_id === job.id)
    .sort((a, b) => (a.created_at < b.created_at ? -1 : 1))
    .map((e) => {
      const payload = e.payload;
      const detail =
        typeof payload.error === "string" ? payload.error : Object.keys(payload).length > 0 ? JSON.stringify(payload) : null;
      const verb = verbFor(e.action, payload);
      return {
        id: e.id,
        name: verb.charAt(0).toUpperCase() + verb.slice(1),
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
  if (typeof brief === "string" && brief.trim()) return brief;
  const cap = job.inputs?.capability;
  if (typeof cap === "string") {
    const target = job.inputs?.document_id ? ` · document #${job.inputs.document_id}` : job.inputs?.party_id ? ` · party #${job.inputs.party_id}` : "";
    return humanize(cap) + target;
  }
  return JSON.stringify(job.inputs ?? {});
}

const preCls = "scroll overflow-x-auto rounded-md border border-line bg-well p-3.5 font-mono text-[12px] leading-relaxed text-fg-2";

export function JobsWorkspace() {
  const { jobs, loading, error, refresh } = useJobs();
  const { activity } = useActivity();
  const [selectedId, setSelectedId] = useState<number | null>(null);

  // Deep link from the activity feed: /jobs?job=12 (read once; no Suspense needed).
  useEffect(() => {
    const id = Number(new URLSearchParams(window.location.search).get("job"));
    if (Number.isInteger(id) && id > 0) setSelectedId(id);
  }, []);

  const ordered = useMemo(() => [...jobs].sort((a, b) => (a.created_at < b.created_at ? 1 : -1)), [jobs]);

  useEffect(() => {
    if (ordered.length === 0) {
      setSelectedId(null);
      return;
    }
    if (loading) return;
    if (selectedId === null || !ordered.some((j) => j.id === selectedId)) setSelectedId(ordered[0].id);
  }, [ordered, selectedId, loading]);

  const selected = ordered.find((j) => j.id === selectedId) ?? null;
  // "queued" is a segment status, never a job status — jobs start as "pending".
  const active = ordered.filter((j) => j.status === "running" || j.status === "pending").length;

  return (
    <div className="flex h-[calc(100vh-48px)] min-h-0 flex-col">
      <div className="flex min-h-0 flex-1">
        <section aria-label="Jobs" className="flex w-[360px] shrink-0 flex-col border-r border-line bg-canvas">
          <div className="flex h-14 shrink-0 items-center gap-2 border-b border-line px-4">
            <h1 className="font-serif text-[20px] text-fg">Agent jobs</h1>
            <span className="num ml-auto text-[12px] text-muted">{active} active</span>
          </div>
          <div className="scroll min-h-0 flex-1 overflow-y-auto">
            {error ? (
              <div className="p-4"><InlineError message={error} onRetry={refresh} /></div>
            ) : loading && ordered.length === 0 ? (
              [0, 1, 2, 3].map((i) => (
                <div key={i} className="border-b border-line-subtle px-4 py-3.5">
                  <Skel className="h-2.5 w-20" />
                  <Skel className="mt-2.5 h-3 w-4/5" />
                </div>
              ))
            ) : ordered.length === 0 ? (
              <EmptyState compact title="No jobs yet" description="Jobs the agents run for the desk will appear here." />
            ) : (
              <ul>
                {ordered.map((job) => {
                  const sel = job.id === selectedId;
                  return (
                    <li key={job.id}>
                      <button
                        onClick={() => setSelectedId(job.id)}
                        aria-current={sel}
                        className={cx("relative w-full border-b border-line-subtle px-4 py-3 text-left transition-colors", sel ? "bg-surface dark:bg-raised" : "hover:bg-well")}
                      >
                        {sel ? <span aria-hidden className="absolute inset-y-0 left-0 w-[2px] bg-accent" /> : null}
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-[11px] text-muted">JOB-{job.id}</span>
                          <Badge tone={jobTone(job.status)} className="ml-auto">{statusLabel(job.status)}</Badge>
                        </div>
                        <p className="mt-1.5 line-clamp-2 text-[13px] leading-snug text-fg">{briefOf(job)}</p>
                        <p className="num mt-1.5 font-mono text-[11px] text-muted">
                          {job.deal_id ? `Deal #${job.deal_id} · ` : ""}
                          {shortAgo(job.created_at)}
                        </p>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </section>

        <section className="scroll min-h-0 flex-1 overflow-y-auto">
          {selected ? (
            <div className="a-fade mx-auto max-w-[760px] px-10 py-9">
              <div className="flex items-center gap-2">
                <span className="font-mono text-[12px] text-muted">JOB-{selected.id}</span>
                <Badge tone={jobTone(selected.status)}>{statusLabel(selected.status)}</Badge>
              </div>
              <h2 className="mt-3 font-serif text-[24px] leading-snug text-fg">{briefOf(selected)}</h2>
              <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-[12px] text-muted">
                <span className="num font-mono">Submitted {formatDateTime(selected.created_at)}</span>
                <span>{selected.deal_id ? `Deal #${selected.deal_id}` : "No deal linked"}</span>
                {selected.created_by ? <span>By {titleCase(selected.created_by)}</span> : null}
                {typeof selected.inputs?.capability === "string" ? <span>{humanize(String(selected.inputs.capability))}</span> : null}
              </div>

              <section className="mt-8">
                <h3 className="mb-3 text-[12px] font-medium text-fg-2">Segment timeline</h3>
                <JobTimeline segments={segmentsFromActivity(selected, activity)} />
              </section>
              <section className="mt-8">
                <h3 className="mb-2.5 text-[12px] font-medium text-fg-2">Inputs</h3>
                <pre className={preCls}>{JSON.stringify(selected.inputs ?? {}, null, 2)}</pre>
              </section>
              <section className="mt-8">
                <h3 className="mb-2.5 text-[12px] font-medium text-fg-2">Result</h3>
                {selected.result ? (
                  <pre className={preCls}>{JSON.stringify(selected.result, null, 2)}</pre>
                ) : (
                  <p className="text-[13px] text-muted">No result yet — the job is still in flight or waiting on a decision.</p>
                )}
              </section>
            </div>
          ) : !loading ? (
            <EmptyState title="No job selected" description="Choose a job to see its segment timeline, inputs and result." />
          ) : null}
        </section>
      </div>
    </div>
  );
}

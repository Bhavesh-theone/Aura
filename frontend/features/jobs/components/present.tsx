"use client";

import { useEffect, useState } from "react";
import { humanize, parseApiDate, formatDateTime } from "@/shared/lib/format";
import type { Tone } from "@/shared/ui/primitives";
import type { Job } from "../types";

const STATUS_LABEL: Record<string, string> = {
  pending: "Queued",
  running: "Running",
  awaiting_approval: "Awaiting decision",
  complete: "Complete",
  failed: "Failed",
  rejected: "Rejected",
};

const baseTone = (s: string): Tone =>
  s === "complete" ? "success" : s === "failed" || s === "rejected" ? "danger" : s === "awaiting_approval" ? "warning" : s === "running" ? "accent" : s === "pending" ? "info" : "neutral";

/** Seconds until an instant (0 when past), re-rendering every second while positive. */
export function useCountdown(iso: string | null | undefined): number {
  const target = iso ? parseApiDate(iso).getTime() : NaN;
  const calc = () => (Number.isNaN(target) ? 0 : Math.max(0, Math.ceil((target - Date.now()) / 1000)));
  const [secs, setSecs] = useState(calc);
  useEffect(() => {
    setSecs(calc());
    if (Number.isNaN(target)) return;
    const t = setInterval(() => setSecs(calc()), 1000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target]);
  return secs;
}

export const fmtSecs = (s: number) => (s < 60 ? `${s}s` : s < 3600 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`);

/** Status shown to people: the derived phase wins over the raw status when set. */
export function statusView(job: Pick<Job, "status" | "phase" | "attempts" | "next_attempt_at">): { label: string; tone: Tone } {
  if (job.phase === "retrying") return { label: `Retrying · attempt ${Math.max(job.attempts, 1)}`, tone: "warning" };
  if (job.phase === "deferred")
    return { label: job.next_attempt_at ? `Deferred until ${formatDateTime(job.next_attempt_at)}` : "Deferred", tone: "info" };
  if (job.phase === "dead_letter") return { label: "Dead letter", tone: "danger" };
  return { label: STATUS_LABEL[job.status] ?? humanize(job.status), tone: baseTone(job.status) };
}

"use client";

import { RotateCw } from "lucide-react";
import { useState } from "react";
import { formatDateTime, humanize } from "@/shared/lib/format";
import { errMessage } from "@/shared/lib/useApi";
import { Badge, Button, Tip } from "@/shared/ui/primitives";
import { InlineError } from "@/shared/ui/States";
import { useToast } from "@/shared/ui/toast";
import { retryJob } from "../api";
import { useDeadLetters } from "../hooks";
import { TraceLink } from "@/features/traces/components/TraceLink";

/** Segments that ran out of attempts. Dealmakers and analysts can put them back in the queue.
 * Shown above the job detail only while something is stuck. */
export function DeadLetters({ onChanged }: { onChanged: () => void }) {
  const { items, error, refresh } = useDeadLetters(true);
  const toast = useToast();
  const [busy, setBusy] = useState<number | null>(null);

  const retry = async (jobId: number) => {
    setBusy(jobId);
    try {
      await retryJob(jobId);
      toast(`JOB-${jobId} queued for another attempt.`);
      refresh();
      onChanged();
    } catch (err) {
      toast(errMessage(err), "error");
    } finally {
      setBusy(null);
    }
  };

  if (!error && items.length === 0) return null;

  return (
    <section aria-label="Dead letters" className="mx-auto max-w-[760px] px-10 pt-9">
      <div className="mb-3 flex items-center gap-2">
        <h3 className="text-[12px] font-medium text-fg-2">Dead letters</h3>
        <span className="text-[12px] text-muted">Ran out of attempts. Retry queues the last segment again.</span>
        {items.length > 0 ? <Badge tone="danger">{items.length}</Badge> : null}
      </div>
      {error ? (
        <InlineError message={error} onRetry={refresh} />
      ) : (
        <ul className="divide-y divide-line-subtle rounded-md border border-danger-border bg-surface">
          {items.map((d) => {
            const cap = typeof d.job.inputs?.capability === "string" ? humanize(String(d.job.inputs.capability)) : "Agent job";
            return (
              <li key={d.segment_id} className="flex items-start gap-3 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-[11px] text-muted">JOB-{d.job.id}</span>
                    <span className="text-[13px] text-fg">{cap}</span>
                    {d.job.deal_id ? <span className="text-[12px] text-muted">Deal #{d.job.deal_id}</span> : null}
                    <span className="num text-[12px] text-muted">{d.attempts} attempts</span>
                    {d.job.trace_id ? <TraceLink traceId={d.job.trace_id} compact /> : null}
                  </div>
                  {d.last_error ? (
                    <Tip label={d.last_error} side="bottom">
                      <p className="mt-1 line-clamp-2 cursor-default font-mono text-[11.5px] leading-snug text-danger">{d.last_error}</p>
                    </Tip>
                  ) : null}
                  <p className="num mt-1 font-mono text-[11px] text-muted">
                    {d.ended_at ? `Ended ${formatDateTime(d.ended_at)}` : "Ended —"}
                    {d.claimed_by ? ` · last claimed by ${d.claimed_by}` : ""}
                  </p>
                </div>
                <Button variant="secondary" size="sm" loading={busy === d.job.id} disabled={busy !== null} onClick={() => retry(d.job.id)}>
                  <RotateCw className="h-3.5 w-3.5" /> Retry
                </Button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

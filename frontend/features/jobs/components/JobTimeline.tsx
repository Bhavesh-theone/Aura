import { cx, formatDateTime, humanize } from "@/shared/lib/format";
import type { JobSegment } from "../types";

const dot: Record<string, string> = {
  complete: "bg-success border-success",
  running: "bg-accent border-accent",
  awaiting_approval: "bg-warning border-warning",
  queued: "bg-surface border-line-strong",
  failed: "bg-danger border-danger",
};

export function JobTimeline({ segments }: { segments: JobSegment[] }) {
  if (segments.length === 0) {
    return <p className="text-[13px] text-muted">No segment timeline was returned for this job.</p>;
  }

  return (
    <ol className="relative ml-1 border-l border-line pl-6">
      {segments.map((segment) => (
        <li key={segment.id} className="relative pb-6 last:pb-0">
          <span className={cx("absolute -left-[30.5px] top-1 h-2.5 w-2.5 rounded-full border-2", dot[segment.status] ?? "bg-surface border-line-strong")} />
          <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
            <p className="text-[13px] font-medium text-fg">{segment.name}</p>
            <span className={cx("text-[12px]", segment.status === "failed" ? "text-danger" : segment.status === "awaiting_approval" ? "text-warning" : "text-muted")}>
              {humanize(segment.status)}
            </span>
          </div>
          <p className="num mt-0.5 font-mono text-[11px] text-muted">
            {segment.agent ? segment.agent + " · " : ""}
            {segment.started_at ? formatDateTime(segment.started_at) : "not started"}
            {segment.finished_at ? " → " + formatDateTime(segment.finished_at) : ""}
          </p>
          {segment.detail ? <p className="mt-1.5 break-words text-[12px] leading-relaxed text-fg-2">{segment.detail}</p> : null}
        </li>
      ))}
    </ol>
  );
}

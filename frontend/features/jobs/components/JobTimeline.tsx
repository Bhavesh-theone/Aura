import { cx, formatDateTime, titleCase } from "@/shared/lib/format";
import type { JobSegment } from "../types";

const dot: Record<string, string> = {
  complete: "bg-cat-money border-cat-money",
  completed: "bg-cat-money border-cat-money",
  running: "bg-[#1c62d0] border-[#1c62d0]",
  awaiting_approval: "bg-amber border-amber",
  queued: "bg-white border-line",
  failed: "bg-cat-outbound border-cat-outbound",
};

export function JobTimeline({ segments }: { segments: JobSegment[] }) {
  if (segments.length === 0) {
    return <p className="text-[13px] text-muted">No segment timeline was returned for this job.</p>;
  }

  return (
    <ol className="relative ml-1 border-l border-line pl-6">
      {segments.map((segment) => (
        <li key={segment.id} className="relative pb-6 last:pb-0">
          <span
            className={cx(
              "absolute -left-[29px] top-0.5 h-3 w-3 rounded-full border-2",
              dot[segment.status] ?? "bg-white border-line",
            )}
          />
          <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
            <p className="text-[13.5px] font-medium text-ink">{segment.name}</p>
            <span
              className={cx(
                "text-[10px] font-semibold uppercase tracking-[0.08em]",
                segment.status === "failed"
                  ? "text-cat-outbound-fg"
                  : segment.status === "awaiting_approval"
                    ? "text-[#8a6100]"
                    : "text-muted",
              )}
            >
              {titleCase(segment.status)}
            </span>
          </div>
          <p className="mt-0.5 text-[11.5px] text-muted">
            {segment.agent ? segment.agent + " · " : ""}
            {segment.started_at ? formatDateTime(segment.started_at) : "not started"}
            {segment.finished_at ? " → " + formatDateTime(segment.finished_at) : ""}
          </p>
          {segment.detail ? (
            <p className="mt-1.5 text-[12.5px] leading-relaxed text-[#4a5261]">{segment.detail}</p>
          ) : null}
        </li>
      ))}
    </ol>
  );
}

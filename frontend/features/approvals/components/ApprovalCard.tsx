"use client";

import { cx, timeAgo } from "@/shared/lib/format";
import { CategoryTag, categoryStyle } from "@/shared/ui/Tag";
import type { Approval } from "../types";

export function ApprovalCard({
  approval,
  selected,
  onSelect,
}: {
  approval: Approval;
  selected: boolean;
  onSelect: () => void;
}) {
  const style = categoryStyle(approval.category);
  const decided = approval.status !== "pending";

  return (
    <button
      onClick={onSelect}
      aria-current={selected ? "true" : undefined}
      className={cx(
        "relative block w-full overflow-hidden rounded-lg border px-3.5 py-3 pl-4 text-left transition-colors",
        selected
          ? "border-navy/25 bg-white shadow-[0_1px_3px_rgba(27,36,54,0.08)] ring-1 ring-navy/10"
          : "border-line bg-surface hover:border-line hover:bg-[#f7f9fc]",
      )}
    >
      <span className={cx("absolute inset-y-0 left-0 w-[3px]", style.stripe, decided && "opacity-40")} />

      <div className="flex items-center gap-2">
        <CategoryTag category={approval.category} className={cx(decided && "opacity-60")} />
        {decided ? (
          <span
            className={cx(
              "text-[10px] font-semibold uppercase tracking-[0.08em]",
              approval.status === "approved" ? "text-cat-money-fg" : "text-cat-outbound-fg",
            )}
          >
            {approval.status}
          </span>
        ) : null}
        <span className="ml-auto shrink-0 text-[11px] text-muted">
          {approval.created_at ? timeAgo(approval.created_at) : `#${approval.id}`}
        </span>
      </div>

      <p
        className={cx(
          "mt-2 line-clamp-2 text-[13px] font-medium leading-[1.45]",
          decided ? "text-muted" : "text-ink",
        )}
      >
        {approval.proposed_action.summary}
      </p>

      <div className="mt-2 flex items-center gap-2 text-[11px] text-muted">
        <code className="rounded bg-line-soft px-1.5 py-0.5 font-mono text-[10px] text-[#5c6675]">
          {approval.proposed_action.tool}
        </code>
        <span className="truncate">
          {approval.requested_by ? approval.requested_by : `Segment ${approval.segment_id}`}
        </span>
      </div>
    </button>
  );
}

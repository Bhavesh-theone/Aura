"use client";

import { CornerUpLeft } from "lucide-react";
import { cx, formatDateTime, stageLabel, timeAgo } from "@/shared/lib/format";
import { Tip } from "@/shared/ui/primitives";
import { STAGES, isTerminal, type DealDetail } from "../types";

/**
 * Segmented 12-step rail. Done = solid accent, current = accent with a halo,
 * a terminal stop = danger, revisited (after a regression) = marked.
 */
const SHORT: Record<string, string> = { CONDITIONS_PRECEDENT: "Conditions", BID_AUCTION: "Auction", DOCUMENTATION: "Docs", NEGOTIATION: "Negotiate" };

export function StageRail({ deal }: { deal: DealDetail }) {
  const stages = STAGES as readonly string[];
  const terminal = isTerminal(deal.stage);
  const closed = deal.stage === "CLOSED";
  const reachedIdx = terminal
    ? Math.max(-1, ...deal.history.map((h) => stages.indexOf(h.to_stage)))
    : stages.indexOf(deal.stage);
  const regressedTo = new Set(deal.history.filter((h) => h.is_regression).map((h) => h.to_stage));
  const enteredAt = (s: string) =>
    [...deal.history].filter((h) => h.to_stage === s).sort((a, b) => (a.entered_at < b.entered_at ? 1 : -1))[0]?.entered_at;
  const currentEntered = enteredAt(deal.stage);

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-[12px] text-muted">
          {terminal ? "Ended" : closed ? "Completed" : "Stage"}{" "}
          <span className="num font-mono text-fg-2">
            {Math.max(reachedIdx + 1, 0)}/{stages.length}
          </span>
        </span>
        <span className={cx("text-[14px] font-medium", terminal ? "text-danger" : "text-fg")}>{stageLabel(deal.stage)}</span>
        {currentEntered ? (
          <span className="text-[12px] text-muted">
            entered {timeAgo(currentEntered)}
            {deal.history.length ? ` · ${deal.history.length} ${deal.history.length === 1 ? "transition" : "transitions"}` : ""}
          </span>
        ) : null}
        {regressedTo.size > 0 ? (
          <span className="ml-auto inline-flex items-center gap-1 text-[12px] text-warning">
            <CornerUpLeft className="h-3 w-3" /> {regressedTo.size} regression{regressedTo.size === 1 ? "" : "s"}
          </span>
        ) : null}
      </div>

      <ol className="grid grid-cols-12 gap-[3px]" aria-label="Deal stage progress">
        {stages.map((s, i) => {
          const done = i < reachedIdx || (closed && i === reachedIdx);
          const current = !terminal && !closed && i === reachedIdx;
          const stopped = terminal && i === reachedIdx;
          const revisited = regressedTo.has(s);
          const at = enteredAt(s);
          return (
            <li key={s} aria-current={current ? "step" : undefined} className="min-w-0">
              <Tip
                side="top"
                label={
                  <span className="flex flex-col">
                    <span className="font-medium">
                      {i + 1}. {stageLabel(s)}
                    </span>
                    <span className="text-muted">
                      {stopped
                        ? `Ended here as ${stageLabel(deal.stage)}`
                        : current
                          ? "Current stage"
                          : done
                            ? at
                              ? `Entered ${formatDateTime(at)}`
                              : "Completed"
                            : "Not reached"}
                      {revisited ? " · revisited after a regression" : ""}
                    </span>
                  </span>
                }
              >
                <div tabIndex={0} className="group cursor-default outline-none">
                  <div className="relative h-[18px]">
                    {revisited ? (
                      <CornerUpLeft aria-label="Revisited" className="absolute left-0 top-0.5 h-3 w-3 text-warning" />
                    ) : null}
                    {current || stopped ? (
                      <svg aria-hidden viewBox="0 0 10 6" className={cx("absolute bottom-1 left-1/2 h-1.5 w-2.5 -translate-x-1/2", stopped ? "fill-danger" : "fill-accent")}>
                        <path d="M0 0h10L5 6z" />
                      </svg>
                    ) : null}
                  </div>
                  <div className="flex h-2.5 items-center">
                  <div
                    className={cx(
                      "w-full rounded-[2px] transition-[background-color,box-shadow,height] duration-[var(--dur-2)]",
                      current || stopped ? "h-2.5" : "h-1.5",
                      i === 0 && "rounded-l-full",
                      i === stages.length - 1 && "rounded-r-full",
                      done && "bg-accent",
                      current && "bg-accent",
                      stopped && "bg-danger",
                      !done && !current && !stopped && "bg-control-active group-hover:bg-line-strong",
                    )}
                  />
                  </div>
                  <div
                    className={cx(
                      "mt-2 truncate text-[11px] leading-tight",
                      current ? "font-semibold text-fg" : stopped ? "font-medium text-danger" : done ? "text-fg-2" : "text-muted",
                    )}
                  >
                    {SHORT[s] ?? stageLabel(s)}
                  </div>
                </div>
              </Tip>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

"use client";

import { useEffect, useMemo, useState } from "react";
import { cx } from "@/shared/lib/format";
import { DetailPane, ErrorBanner, ListPane, OfflineBanner, ThreePane } from "@/shared/ui/shell/Panes";
import { EmptyState, SkeletonRows } from "@/shared/ui/States";
import { InboxEmptyIcon, SearchIcon } from "@/shared/ui/icons";
import { useApprovals } from "../provider";
import { ApprovalCard } from "./ApprovalCard";
import { ApprovalDetail } from "./ApprovalDetail";

type Filter = "pending" | "all" | "outbound" | "legal" | "money";

const filters: { key: Filter; label: string }[] = [
  { key: "pending", label: "Pending" },
  { key: "money", label: "Money" },
  { key: "legal", label: "Legal" },
  { key: "outbound", label: "Outbound" },
  { key: "all", label: "All" },
];

export function ApprovalsWorkspace() {
  const { approvals, loading, offline, error, decide, pendingId, decisionError, refresh } =
    useApprovals();
  const [filter, setFilter] = useState<Filter>("pending");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return approvals
      .filter((a) => {
        if (filter === "pending") return a.status === "pending";
        if (filter === "all") return true;
        return a.category === filter;
      })
      .filter((a) => {
        if (!q) return true;
        return (
          a.proposed_action.summary.toLowerCase().includes(q) ||
          a.proposed_action.tool.toLowerCase().includes(q) ||
          JSON.stringify(a.proposed_action.arguments).toLowerCase().includes(q)
        );
      });
  }, [approvals, filter, query]);

  // Keep a row selected as the queue changes underneath us.
  useEffect(() => {
    if (visible.length === 0) {
      setSelectedId(null);
      return;
    }
    if (selectedId === null || !visible.some((a) => a.id === selectedId)) {
      setSelectedId(visible[0].id);
    }
  }, [visible, selectedId]);

  const selected = approvals.find((a) => a.id === selectedId) ?? null;
  const pendingCount = approvals.filter((a) => a.status === "pending").length;

  return (
    <>
      {offline ? <OfflineBanner /> : null}
      {error ? <ErrorBanner message={error} onRetry={refresh} /> : null}
      <ThreePane>
        <ListPane
          title="Approvals queue"
          subtitle={`${pendingCount} pending`}
          toolbar={
            <div className="space-y-2.5">
              <div className="relative">
                <SearchIcon className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search actions, tools, counterparties"
                  className="w-full rounded-md border border-line bg-appbg py-1.5 pl-8 pr-3 text-[12.5px] text-ink outline-none transition-colors placeholder:text-muted/80 focus:border-navy/30 focus:bg-white"
                />
              </div>
              <div className="flex flex-wrap gap-1.5">
                {filters.map((f) => (
                  <button
                    key={f.key}
                    onClick={() => setFilter(f.key)}
                    className={cx(
                      "rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors",
                      filter === f.key
                        ? "bg-navy text-white"
                        : "bg-line-soft text-muted hover:bg-line hover:text-ink",
                    )}
                  >
                    {f.label}
                  </button>
                ))}
              </div>
            </div>
          }
        >
          {loading && approvals.length === 0 ? (
            <SkeletonRows />
          ) : visible.length === 0 ? (
            <EmptyState
              className="py-16"
              icon={<InboxEmptyIcon className="h-10 w-10" />}
              title="Queue clear"
              description="No approvals match this filter. Agents will raise a request here the moment one is needed."
            />
          ) : (
            <div className="space-y-2 p-3">
              {visible.map((approval) => (
                <ApprovalCard
                  key={approval.id}
                  approval={approval}
                  selected={approval.id === selectedId}
                  onSelect={() => setSelectedId(approval.id)}
                />
              ))}
            </div>
          )}
        </ListPane>

        <DetailPane>
          {selected ? (
            <ApprovalDetail
              approval={selected}
              busy={pendingId === selected.id}
              error={decisionError}
              readOnly={offline}
              onDecide={(decision) => decide(selected.id, decision)}
            />
          ) : (
            <EmptyState
              icon={<InboxEmptyIcon className="h-12 w-12" />}
              title="Nothing selected"
              description="Pick a request from the queue to review the exact action the agent proposes before it runs."
            />
          )}
        </DetailPane>
      </ThreePane>
    </>
  );
}

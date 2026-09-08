"use client";

import { useMemo, useState } from "react";
import { cx, formatINR, timeAgo } from "@/shared/lib/format";
import { ErrorBanner, OfflineBanner } from "@/shared/ui/shell/Panes";
import { EmptyState, SkeletonRows } from "@/shared/ui/States";
import { DealsIcon, SearchIcon } from "@/shared/ui/icons";
import { useDeals } from "../hooks";

const stageStyle: Record<string, string> = {
  Origination: "bg-[#f1f3f5] text-[#495057]",
  "Mandate Signed": "bg-[#edf2ff] text-[#3b5bdb]",
  Diligence: "bg-amber-soft text-[#8a6100]",
  "Term Sheet": "bg-cat-legal-bg text-cat-legal-fg",
  Closing: "bg-cat-money-bg text-cat-money-fg",
};

export function DealsTable() {
  const { deals, loading, offline, error, refresh } = useDeals();
  const [query, setQuery] = useState("");

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return deals.filter((d) =>
      !q ? true : (d.name + " " + d.client + " " + d.sector + " " + d.owner).toLowerCase().includes(q),
    );
  }, [deals, query]);

  const total = rows.reduce((sum, d) => sum + (d.value_inr || 0), 0);

  return (
    <>
      {offline ? (
        <OfflineBanner message="The deals endpoint is not available on the API yet." />
      ) : null}
      {error ? <ErrorBanner message={error} onRetry={refresh} /> : null}
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="flex shrink-0 items-center gap-4 border-b border-line bg-surface px-6 py-3.5">
          <div>
            <h1 className="text-[15px] font-semibold text-ink">Deals</h1>
            <p className="text-[12px] text-muted">
              {rows.length} live mandates · {formatINR(total)} aggregate transaction value
            </p>
          </div>
          <div className="relative ml-auto w-72">
            <SearchIcon className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search deals, clients, owners"
              className="w-full rounded-md border border-line bg-appbg py-1.5 pl-8 pr-3 text-[12.5px] text-ink outline-none transition-colors placeholder:text-muted/80 focus:border-navy/30 focus:bg-white"
            />
          </div>
        </div>

        <div className="yuki-scroll min-h-0 flex-1 overflow-auto p-6">
          {loading && rows.length === 0 ? (
            <SkeletonRows count={5} />
          ) : rows.length === 0 ? (
            <EmptyState
              className="py-20"
              icon={<DealsIcon className="h-10 w-10" />}
              title="No deals"
              description="Deals linked to agent jobs will be listed here."
            />
          ) : (
            <div className="overflow-hidden rounded-xl border border-line bg-surface">
              <table className="w-full border-collapse text-left">
                <thead>
                  <tr className="border-b border-line bg-[#f8fafc]">
                    {["Deal", "Client", "Sector", "Stage", "Value", "Owner", "Updated"].map((h) => (
                      <th
                        key={h}
                        className={cx(
                          "px-4 py-2.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted",
                          h === "Value" && "text-right",
                        )}
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((deal) => (
                    <tr key={deal.id} className="border-b border-line-soft last:border-0 hover:bg-[#f9fbfe]">
                      <td className="px-4 py-3 text-[13px] font-medium text-ink">{deal.name}</td>
                      <td className="px-4 py-3 text-[13px] text-[#4a5261]">{deal.client}</td>
                      <td className="px-4 py-3 text-[12.5px] text-muted">{deal.sector}</td>
                      <td className="px-4 py-3">
                        <span
                          className={cx(
                            "inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium",
                            stageStyle[deal.stage] ?? "bg-line-soft text-muted",
                          )}
                        >
                          {deal.stage}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right text-[13px] font-semibold tabular-nums text-ink">
                        {formatINR(deal.value_inr)}
                      </td>
                      <td className="px-4 py-3 text-[12.5px] text-[#4a5261]">{deal.owner}</td>
                      <td className="px-4 py-3 text-[12px] text-muted">{timeAgo(deal.updated_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

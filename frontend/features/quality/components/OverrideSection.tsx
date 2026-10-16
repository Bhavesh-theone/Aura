"use client";

import { Card } from "@/shared/ui/primitives";
import { EmptyState, InlineError, SkeletonRows } from "@/shared/ui/States";
import { useOverrideRates } from "../hooks";
import { capLabel, ScoreBar } from "./shared";

const DEMOTE_AT = 0.2;

export function OverrideSection() {
  const { data, loading, error, refresh } = useOverrideRates();
  return (
    <section aria-labelledby="q-override">
      <h2 id="q-override" className="font-serif text-[18px] text-fg">Override rates</h2>
      <p className="mb-3 mt-0.5 text-[13px] text-muted">
        How often people change what an agent proposed. A capability is demoted automatically when at least 20 decisions are in the window and more than 20% were overrides.
      </p>
      <Card className="divide-y divide-line-subtle">
        {error ? (
          <div className="p-4"><InlineError message={error} onRetry={refresh} /></div>
        ) : loading ? (
          <SkeletonRows rows={3} />
        ) : data.length === 0 ? (
          <EmptyState compact title="No decisions yet" />
        ) : (
          data.map((o) => {
            const over = o.rate !== null && o.rate > DEMOTE_AT;
            return (
              <div key={o.capability} className="grid grid-cols-1 items-center gap-x-6 gap-y-2 px-4 py-3 sm:grid-cols-[200px_1fr_auto]">
                <div>
                  <p className="text-[13px] font-medium text-fg">{capLabel(o.capability)}</p>
                  <p className="text-[11.5px] text-muted">last {o.window_days} days</p>
                </div>
                {o.rate === null ? (
                  <p className="text-[12.5px] text-muted">No decisions yet</p>
                ) : (
                  <div className="flex items-center gap-3">
                    <ScoreBar value={o.rate} threshold={DEMOTE_AT} tone={over ? "danger" : "success"} className="max-w-sm flex-1" />
                    <span className="num w-12 text-right text-[13px] font-medium text-fg">{(o.rate * 100).toFixed(0)}%</span>
                  </div>
                )}
                <p className="num text-[12px] text-muted sm:text-right">
                  {o.overrides} of {o.decisions} decisions overridden
                </p>
              </div>
            );
          })
        )}
        <p className="px-4 py-2 text-[11.5px] text-muted">The tick on each bar marks the 20% demotion threshold.</p>
      </Card>
    </section>
  );
}

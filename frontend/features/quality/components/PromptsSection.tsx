"use client";

import { useMemo } from "react";
import { Badge, Card } from "@/shared/ui/primitives";
import { EmptyState, InlineError, SkeletonRows } from "@/shared/ui/States";
import { usePrompts } from "../hooks";
import { CopyChip } from "./shared";

export function PromptsSection() {
  const { data, loading, error, refresh } = usePrompts();
  const rows = useMemo(
    () =>
      [...data].sort(
        (a, b) =>
          a.template_id.localeCompare(b.template_id) ||
          Number(b.active) - Number(a.active) ||
          b.version.localeCompare(a.version, undefined, { numeric: true }),
      ),
    [data],
  );
  return (
    <section aria-labelledby="q-prompts">
      <h2 id="q-prompts" className="font-serif text-[18px] text-fg">Prompt registry</h2>
      <p className="mb-3 mt-0.5 text-[13px] text-muted">Versioned prompt templates the agents run. The hash pins the exact text used in a run.</p>
      <Card className="overflow-hidden">
        {error ? (
          <div className="p-4"><InlineError message={error} onRetry={refresh} /></div>
        ) : loading ? (
          <SkeletonRows rows={4} />
        ) : rows.length === 0 ? (
          <EmptyState compact title="No prompts registered" />
        ) : (
          <div className="scroll overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-[12.5px]">
              <thead>
                <tr className="border-b border-line-subtle text-[11px] uppercase tracking-[0.06em] text-muted">
                  {["Prompt", "Role", "sha256", "Status", "Path"].map((h) => (
                    <th key={h} className="px-3 py-2 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((p) => (
                  <tr key={p.ref} className="border-b border-line-subtle last:border-0">
                    <td className="whitespace-nowrap px-3 py-2.5 font-mono text-[12px] text-fg">{p.ref}</td>
                    <td className="px-3 py-2.5 text-fg-2">{p.role}</td>
                    <td className="px-3 py-2.5"><CopyChip value={p.sha256} shown={p.sha256.slice(0, 12)} /></td>
                    <td className="px-3 py-2.5">{p.active ? <Badge tone="success">active</Badge> : <Badge tone="neutral">inactive</Badge>}</td>
                    <td className="max-w-[280px] truncate px-3 py-2.5 font-mono text-[11px] text-muted" title={p.path}>{p.path}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </section>
  );
}

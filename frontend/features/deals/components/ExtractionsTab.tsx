"use client";

import { BadgeCheck, ChevronRight, ScanText, ShieldAlert } from "lucide-react";
import { Fragment, useState } from "react";
import { WHO_CAN } from "@/features/auth/roles";
import { useCan } from "@/features/auth/useCan";
import { dealEvents } from "@/shared/api/events";
import { cx, formatDateTime, formatINRCompact, humanize, shortDate, titleCase } from "@/shared/lib/format";
import { errMessage, useApi } from "@/shared/lib/useApi";
import { Badge, Button } from "@/shared/ui/primitives";
import { Permit } from "@/shared/ui/Permit";
import { useToast } from "@/shared/ui/toast";
import { listDocuments, listExtractions, verifyExtraction } from "../api";
import { VALUATION_CONFIDENCE, type DealDocument, type Extraction } from "../types";
import { EmptyState, InlineError, SkeletonRows, Unavailable } from "./ui";

/** Confidence as a 10-cell meter: green from the 0.95 valuation bar, amber below. */
export function ConfidenceCells({ value }: { value: number | null }) {
  if (value == null) return <span className="text-[12px] text-muted">—</span>;
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  const filled = Math.round(pct / 10);
  const tone = value >= VALUATION_CONFIDENCE ? "bg-success" : value >= 0.75 ? "bg-accent" : "bg-warning";
  return (
    <span className="inline-flex items-center gap-2" role="meter" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="Confidence">
      <span className="flex gap-[2px]">
        {Array.from({ length: 10 }).map((_, i) => (
          <span key={i} className={cx("h-2.5 w-1 rounded-[1px]", i < filled ? tone : "bg-control-active")} />
        ))}
      </span>
      <span className="num font-mono text-[12px] text-fg-2">{value.toFixed(2)}</span>
    </span>
  );
}

function fieldValue(k: string, v: unknown): string {
  if (typeof v === "number" && /(_inr|revenue|ebitda|pat|debt|cash|assets|liabilities|profit|income)/i.test(k)) return formatINRCompact(v);
  if (typeof v === "number") return new Intl.NumberFormat("en-IN").format(v);
  if (v && typeof v === "object") return JSON.stringify(v);
  return String(v ?? "—");
}

export function ExtractionsTab({ dealId }: { dealId: number }) {
  const toast = useToast();
  const allowed = useCan()("work");
  const live = dealEvents(dealId, ["extraction", "document"]);
  const ex = useApi<Extraction[]>(() => listExtractions(dealId), [], [dealId], { live });
  const docs = useApi<DealDocument[]>(() => listDocuments(dealId), [], [dealId], { live });
  const [open, setOpen] = useState<number | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const docName = new Map(docs.data.map((d) => [d.id, d.filename]));

  async function verify(x: Extraction) {
    setBusy(x.id);
    try {
      await verifyExtraction(x.id);
      toast(`${humanize(x.schema_name)} verified — now usable for valuation`);
      ex.refresh();
    } catch (err) {
      toast(errMessage(err), "error");
    } finally {
      setBusy(null);
    }
  }

  if (ex.unavailable) return <Unavailable what="Extractions" />;
  if (ex.loading)
    return (
      <div className="rounded-md border border-line bg-surface">
        <SkeletonRows rows={3} />
      </div>
    );
  if (ex.error) return <InlineError message={ex.error} onRetry={ex.refresh} />;
  if (ex.data.length === 0)
    return (
      <div className="rounded-md border border-line bg-surface">
        <EmptyState
          compact
          title="No extractions yet"
          description="Run “Extract financials” on a document from the Documents tab. Figures appear here for a person to verify before they feed valuation."
        />
      </div>
    );

  return (
    <div className="space-y-3">
      <p className="text-[12px] text-muted">
        Figures feed valuation only at confidence ≥ {VALUATION_CONFIDENCE.toFixed(2)} or after a person verifies them.
      </p>
      <div className="overflow-hidden rounded-md border border-line bg-surface shadow-card">
        <table className="w-full border-collapse text-left">
          <thead>
            <tr className="h-9 border-b border-line text-[12px] text-muted">
              <th className="w-8" />
              <th className="px-2 font-medium">Extraction</th>
              <th className="px-2 font-medium">Confidence</th>
              <th className="px-2 font-medium">Valuation use</th>
              <th className="px-4 text-right font-medium">Verification</th>
            </tr>
          </thead>
          <tbody>
            {ex.data.map((x) => {
              const usable = x.human_verified_by != null || (x.confidence ?? 0) >= VALUATION_CONFIDENCE;
              const expanded = open === x.id;
              const fields = Object.entries(x.payload ?? {});
              return (
                <Fragment key={x.id}>
                  <tr className={cx("h-12 border-b border-line-subtle text-[13px]", expanded && "bg-well")}>
                    <td className="pl-2">
                      <button
                        onClick={() => setOpen(expanded ? null : x.id)}
                        aria-expanded={expanded}
                        aria-label={expanded ? "Hide figures" : "Show figures"}
                        className="flex h-6 w-6 items-center justify-center rounded-xs text-muted outline-none hover:bg-control-hover hover:text-fg focus-visible:ring-2 focus-visible:ring-accent/50"
                      >
                        <ChevronRight className={cx("h-3.5 w-3.5 transition-transform", expanded && "rotate-90")} />
                      </button>
                    </td>
                    <td className="px-2">
                      <div className="flex items-center gap-1.5 font-medium text-fg">
                        <ScanText className="h-3.5 w-3.5 text-muted" /> {humanize(x.schema_name)}
                      </div>
                      <div className="mt-0.5 truncate text-[11px] text-muted">
                        {docName.get(x.document_id) ?? `Document #${x.document_id}`} · {fields.length} field{fields.length === 1 ? "" : "s"} · {shortDate(x.created_at)}
                      </div>
                    </td>
                    <td className="px-2"><ConfidenceCells value={x.confidence} /></td>
                    <td className="px-2">
                      {usable ? (
                        <Badge tone="success">{x.feeds_valuation ? "Feeds valuation" : "Usable"}</Badge>
                      ) : (
                        <Badge tone="warning"><ShieldAlert className="h-3 w-3" /> Needs verification</Badge>
                      )}
                    </td>
                    <td className="px-4 text-right">
                      {x.human_verified_by ? (
                        <span className="inline-flex flex-col items-end text-[12px]">
                          <span className="inline-flex items-center gap-1 text-success"><BadgeCheck className="h-3.5 w-3.5" /> {titleCase(x.human_verified_by)}</span>
                          {x.human_verified_at ? <span className="num font-mono text-[11px] text-muted">{formatDateTime(x.human_verified_at)}</span> : null}
                        </span>
                      ) : (
                        <Permit allow={allowed} why={WHO_CAN.work}>
                          <Button size="sm" variant="secondary" loading={busy === x.id} onClick={() => verify(x)}>
                            Verify figures
                          </Button>
                        </Permit>
                      )}
                    </td>
                  </tr>
                  {expanded ? (
                    <tr className="border-b border-line-subtle bg-well">
                      <td />
                      <td colSpan={4} className="pb-4 pl-2 pr-4 pt-1">
                        {fields.length === 0 ? (
                          <p className="text-[12px] text-muted">The extraction returned no fields.</p>
                        ) : (
                          <dl className="grid grid-cols-2 gap-x-8 gap-y-1.5 lg:grid-cols-3">
                            {fields.map(([k, v]) => (
                              <div key={k} className="flex items-baseline justify-between gap-3 border-b border-line-subtle py-1 text-[12px]">
                                <dt className="truncate text-muted">{humanize(k.replace(/_inr$/, ""))}</dt>
                                <dd className="num shrink-0 font-mono text-fg">{fieldValue(k, v)}</dd>
                              </div>
                            ))}
                          </dl>
                        )}
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

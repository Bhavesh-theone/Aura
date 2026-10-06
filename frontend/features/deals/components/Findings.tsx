"use client";

import { AlertOctagon, Flag, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { WHO_CAN } from "@/features/auth/roles";
import { useCan } from "@/features/auth/useCan";
import { cx, formatINRCompact, humanize, shortDate, titleCase } from "@/shared/lib/format";
import { errMessage, type Api } from "@/shared/lib/useApi";
import { InrInput, toRupees, type InrUnit } from "@/shared/ui/InrInput";
import { Badge, Button, Segmented, labelCls, textareaCls, type Tone } from "@/shared/ui/primitives";
import { Permit } from "@/shared/ui/Permit";
import { Sheet } from "@/shared/ui/Sheet";
import { useToast } from "@/shared/ui/toast";
import { createFinding } from "../api";
import { FINDING_TYPES, type DiligenceItem, type Finding, type FindingType } from "../types";
import { EmptyState, InlineError, Notice, Section, SkeletonRows, Unavailable, selectCls } from "./ui";

export const FINDING_TONE: Record<string, Tone> = { red_flag: "danger", qualification: "warning", adjustment: "info", observation: "neutral" };
const FINDING_HINT: Record<FindingType, string> = {
  red_flag: "Could stop the deal or force a re-price.",
  qualification: "Needs a caveat, condition or indemnity.",
  adjustment: "Changes the numbers — EBITDA, net debt, working capital.",
  observation: "Worth recording; no action needed yet.",
};

/** Raise a finding, optionally against a diligence item. Enforces impact → affects-valuation. */
export function RaiseFindingSheet({
  dealId,
  open,
  item,
  items,
  onClose,
  onRaised,
}: {
  dealId: number;
  open: boolean;
  item: DiligenceItem | null;
  items: DiligenceItem[];
  onClose: () => void;
  onRaised: () => void;
}) {
  const toast = useToast();
  const allowed = useCan()("work");
  const [itemId, setItemId] = useState<string>("");
  const [type, setType] = useState<FindingType>("red_flag");
  const [desc, setDesc] = useState("");
  const [amount, setAmount] = useState("");
  const [unit, setUnit] = useState<InrUnit>("crore");
  const [affects, setAffects] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setItemId(item ? String(item.id) : "");
    setType("red_flag");
    setDesc("");
    setAmount("");
    setAffects(false);
    setError(null);
  }, [open, item]);

  const rupees = toRupees(amount, unit);
  const amountBad = amount.trim() !== "" && rupees === null;
  // Rule: a finding can only affect valuation when its impact is quantified.
  useEffect(() => {
    if (rupees === null && affects) setAffects(false);
  }, [rupees, affects]);

  let blocker: string | null = null;
  if (!allowed) blocker = WHO_CAN.work;
  else if (!itemId) blocker = "Pick the diligence item this finding is about.";
  else if (desc.trim().length < 10) blocker = "Describe the finding (at least 10 characters).";
  else if (amountBad) blocker = "Fix the impact amount.";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (blocker) return;
    setBusy(true);
    setError(null);
    try {
      await createFinding(dealId, {
        diligence_item_id: Number(itemId),
        finding_type: type,
        description: desc.trim(),
        quantified_impact_inr: rupees,
        affects_valuation: affects && rupees !== null,
      });
      toast(`${humanize(type)} recorded${rupees !== null ? ` · ${formatINRCompact(rupees)}` : ""}`);
      onRaised();
      onClose();
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet
      open={open}
      onClose={onClose}
      width={520}
      eyebrow={<span className="inline-flex items-center gap-1.5"><Flag className="h-3.5 w-3.5" /> Diligence</span>}
      title="Raise a finding"
      description={item ? <>Against “{item.prompt}”</> : "Record what diligence turned up, and what it is worth."}
      footer={
        <div className="flex items-center gap-3">
          <p className={cx("min-w-0 flex-1 text-[12px]", blocker ? "text-muted" : "text-success")}>{blocker ?? "Ready to record."}</p>
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Permit allow={allowed} why={WHO_CAN.work}>
            <Button type="submit" form="raise-finding" loading={busy} disabled={blocker !== null}>Record finding</Button>
          </Permit>
        </div>
      }
    >
      <form id="raise-finding" onSubmit={submit} className="space-y-5">
        <div>
          <span className={labelCls}>Type</span>
          <Segmented label="Finding type" value={type} onChange={setType} options={FINDING_TYPES.map((t) => ({ value: t, label: humanize(t) }))} />
          <p className="mt-1.5 text-[12px] text-muted">{FINDING_HINT[type]}</p>
        </div>
        <div>
          <label htmlFor="f-item" className={labelCls}>Diligence item</label>
          <select id="f-item" value={itemId} onChange={(e) => setItemId(e.target.value)} className={selectCls}>
            <option value="" disabled>Choose a checklist item…</option>
            {items.map((i) => (
              <option key={i.id} value={i.id}>{i.prompt}</option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="f-desc" className={labelCls}>What was found</label>
          <textarea id="f-desc" rows={4} value={desc} onChange={(e) => setDesc(e.target.value)} className={textareaCls} placeholder="e.g. Contingent GST liability from FY22 assessment not provided for in the audited accounts." />
        </div>
        <div>
          <label htmlFor="f-amt" className={labelCls}>Quantified impact <span className="font-normal text-muted">· optional</span></label>
          <InrInput id="f-amt" text={amount} unit={unit} onText={setAmount} onUnit={setUnit} />
        </div>
        <label className={cx("flex items-start gap-2.5 rounded-sm border px-3 py-2.5 text-[13px]", rupees === null ? "border-line text-muted" : "border-line text-fg")}>
          <input type="checkbox" className="mt-[3px]" checked={affects} disabled={rupees === null} onChange={(e) => setAffects(e.target.checked)} />
          <span>
            Affects valuation
            <span className="block text-[12px] text-muted">
              {rupees === null ? "Quantify the impact first — only a finding with a rupee figure can move the valuation." : "Feeds the valuation adjustments for this deal."}
            </span>
          </span>
        </label>
        {error ? <Notice tone="error">{error}</Notice> : null}
      </form>
    </Sheet>
  );
}

export function FindingsSection({
  findings,
  items,
  onRaise,
}: {
  findings: Api<Finding[]>;
  items: DiligenceItem[];
  onRaise: () => void;
}) {
  const allowed = useCan()("work");
  const byItem = new Map(items.map((i) => [i.id, i]));
  const total = findings.data.reduce((a, f) => a + (f.affects_valuation && f.quantified_impact_inr ? f.quantified_impact_inr : 0), 0);
  const red = findings.data.filter((f) => f.finding_type === "red_flag").length;

  return (
    <Section
      flush
      title={
        <span className="flex items-center gap-2">
          Findings {findings.data.length ? <span className="num font-mono text-[11px] font-normal text-muted">{findings.data.length}</span> : null}
          {red ? <Badge tone="danger"><AlertOctagon className="h-3 w-3" /> {red} red flag{red === 1 ? "" : "s"}</Badge> : null}
        </span>
      }
      aside={
        <>
          {total ? <span className="num text-[12px] text-muted">Valuation impact <span className="font-medium text-fg">{formatINRCompact(total)}</span></span> : null}
          <Permit allow={allowed} why={WHO_CAN.work}>
            <Button size="sm" variant="secondary" onClick={onRaise}>
              <Plus className="h-3.5 w-3.5" /> Raise finding
            </Button>
          </Permit>
        </>
      }
    >
      {findings.unavailable ? (
        <div className="p-4"><Unavailable what="Findings" /></div>
      ) : findings.loading ? (
        <SkeletonRows rows={2} />
      ) : findings.error ? (
        <div className="p-4"><InlineError message={findings.error} onRetry={findings.refresh} /></div>
      ) : findings.data.length === 0 ? (
        <EmptyState compact title="No findings yet" description="Red flags, qualifications and adjustments raised during diligence collect here with their rupee impact." />
      ) : (
        <ul>
          {findings.data.map((f) => {
            const item = byItem.get(f.diligence_item_id);
            return (
              <li key={f.id} className="flex gap-3 border-b border-line-subtle px-4 py-3 last:border-0">
                <Badge tone={FINDING_TONE[f.finding_type] ?? "neutral"} className="mt-px w-[100px] justify-center">{humanize(f.finding_type)}</Badge>
                <div className="min-w-0 flex-1">
                  <p className="text-[13px] leading-relaxed text-fg">{f.description}</p>
                  <p className="mt-1 flex flex-wrap gap-x-2 text-[11px] text-muted">
                    {item ? <span className="truncate">On: {item.prompt}</span> : <span>Item #{f.diligence_item_id}</span>}
                    <span>· {titleCase(f.raised_by)}</span>
                    <span>· {shortDate(f.raised_at)}</span>
                  </p>
                </div>
                <div className="shrink-0 text-right">
                  {f.quantified_impact_inr != null ? (
                    <div className="num font-mono text-[13px] font-medium text-fg">{formatINRCompact(f.quantified_impact_inr)}</div>
                  ) : (
                    <div className="text-[12px] text-muted">Not quantified</div>
                  )}
                  {f.affects_valuation ? <div className="mt-0.5 text-[11px] text-warning">Affects valuation</div> : null}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Section>
  );
}

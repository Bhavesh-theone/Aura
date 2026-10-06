"use client";

import { Plus, Scale, X } from "lucide-react";
import { useState } from "react";
import { WHO_CAN } from "@/features/auth/roles";
import { useCan } from "@/features/auth/useCan";
import { dealEvents } from "@/shared/api/events";
import { cx, formatDateTime, formatINRCompact, humanize } from "@/shared/lib/format";
import { errMessage, useApi } from "@/shared/lib/useApi";
import { Badge, Button, IconButton, Segmented, inputCls, labelCls, type Tone } from "@/shared/ui/primitives";
import { Permit } from "@/shared/ui/Permit";
import { useToast } from "@/shared/ui/toast";
import { createMandate, listMandates } from "../api";
import {
  HARDNESS, MANDATE_SIDES, MANDATE_STATUSES, OPERATORS,
  type Criterion, type CriterionValue, type Hardness, type Mandate, type MandateSide, type MandateStatus, type Operator,
} from "../types";
import { EmptyState, InlineError, Notice, Section, SkeletonRows, Unavailable, selectCls } from "./ui";

const OP_LABEL: Record<Operator, string> = {
  eq: "is",
  in: "is one of",
  not_in: "is not one of",
  gte: "at least",
  lte: "at most",
  between: "between",
  contains: "contains",
};

const HARD_TONE: Record<string, Tone> = { hard: "danger", soft: "accent", preference: "neutral" };
const HARD_HINT: Record<Hardness, string> = {
  hard: "Must hold — a counterparty failing it is out.",
  soft: "Scored — weight says how much it counts.",
  preference: "Nice to have — breaks ties.",
};

const SIDE_LABEL: Record<MandateSide, string> = {
  sell: "Sell-side",
  buy: "Buy-side",
  raise: "Raise",
  deploy: "Deploy",
  partner: "Partner",
};
const STATUS_TONE: Record<MandateStatus, Tone> = {
  draft: "neutral",
  active: "success",
  paused: "warning",
  fulfilled: "accent",
  expired: "neutral",
  withdrawn: "danger",
};

const KEY_SUGGESTIONS = ["sector", "geography", "ticket_size_inr", "revenue_inr", "ebitda_inr", "ebitda_margin_pct", "ownership_pct", "investor_type", "listing_status", "promoter_holding_pct"];

type Row = { key: string; operator: Operator; value: string; value2: string; hardness: Hardness; weight: string };
const blankRow = (): Row => ({ key: "", operator: "eq", value: "", value2: "", hardness: "hard", weight: "" });

function one(key: string, v: string): string {
  const n = Number(v.replace(/[,\s]/g, ""));
  if (/_inr$/.test(key) && v.trim() !== "" && Number.isFinite(n)) return formatINRCompact(n);
  return v.trim();
}

function valueText(c: Criterion): string {
  const v = c.value;
  if (Array.isArray(v)) return v.map((x) => one(c.criterion_key, String(x))).join(c.operator === "between" ? " – " : ", ");
  return one(c.criterion_key, String(v));
}

/** A number when the text parses as one (commas stripped), else the trimmed text. */
function scalar(text: string): string | number {
  const t = text.trim();
  const n = Number(t.replace(/,/g, ""));
  return t !== "" && Number.isFinite(n) ? n : t;
}
const listOf = (text: string) => text.split(",").map((x) => x.trim()).filter(Boolean).map(scalar);

/** Wire value per the server's shape rules (422 otherwise). */
function wireValue(r: Row): CriterionValue {
  if (r.operator === "between") return [scalar(r.value), scalar(r.value2)];
  if (r.operator === "in" || r.operator === "not_in") return listOf(r.value);
  return scalar(r.value);
}

function rowProblem(r: Row): string | null {
  if (!r.key.trim()) return "Name the criterion.";
  if (r.key.trim().length > 100) return "Criterion names are at most 100 characters.";
  if (!r.value.trim()) return "Give it a value.";
  if (r.operator === "between" && !r.value2.trim()) return "A range needs both ends.";
  if ((r.operator === "in" || r.operator === "not_in") && listOf(r.value).length === 0) return "List at least one value.";
  if ((r.operator === "gte" || r.operator === "lte") && typeof scalar(r.value) !== "number") return "“At least” and “at most” need a number.";
  if (r.hardness !== "hard" && r.weight.trim()) {
    const w = Number(r.weight);
    if (!Number.isFinite(w) || w < 0 || w > 1) return "Weight is a number from 0 to 1.";
  } else if (r.hardness === "soft") return "Soft criteria need a weight (0 to 1).";
  return null;
}

function MandateCard({ m }: { m: Mandate }) {
  const hard = m.criteria.filter((c) => c.hardness === "hard").length;
  return (
    <Section
      title={
        <span className="flex items-center gap-2">
          <Scale className="h-3.5 w-3.5 text-muted" /> {m.title}
        </span>
      }
      aside={
        <span className="flex items-center gap-2">
          <Badge tone="neutral">{SIDE_LABEL[m.side] ?? humanize(m.side)}</Badge>
          <Badge tone={STATUS_TONE[m.status] ?? "neutral"} className="capitalize">{m.status}</Badge>
          <span className="num text-[12px] text-muted">{formatDateTime(m.created_at)}</span>
        </span>
      }
      flush
    >
      {m.notes ? <p className="border-b border-line-subtle px-4 py-3 text-[13px] leading-relaxed text-fg-2">{m.notes}</p> : null}
      {m.criteria.length === 0 ? (
        <p className="px-4 py-4 text-[13px] text-muted">No criteria recorded.</p>
      ) : (
        <table className="w-full border-collapse text-left text-[13px]">
          <thead>
            <tr className="h-8 border-b border-line-subtle text-[11px] text-muted">
              <th className="px-4 font-medium">Criterion</th>
              <th className="px-2 font-medium">Rule</th>
              <th className="px-2 font-medium">Kind</th>
              <th className="px-4 text-right font-medium">Weight</th>
            </tr>
          </thead>
          <tbody>
            {m.criteria.map((c, i) => {
              const h = c.hardness;
              return (
                <tr key={i} className="h-10 border-b border-line-subtle last:border-0">
                  <td className="px-4 font-mono text-[12px] text-fg">{c.criterion_key}</td>
                  <td className="px-2 text-fg-2">
                    <span className="text-muted">{OP_LABEL[c.operator] ?? humanize(c.operator)}</span>{" "}
                    <span className="font-medium text-fg">{valueText(c)}</span>
                  </td>
                  <td className="px-2"><Badge tone={HARD_TONE[h] ?? "neutral"} className="capitalize">{h}</Badge></td>
                  <td className="num px-4 text-right font-mono text-[12px] text-fg-2">{c.weight != null ? c.weight : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      <div className="border-t border-line-subtle px-4 py-2.5 text-[12px] text-muted">
        {hard ? `${hard} hard ${hard === 1 ? "criterion" : "criteria"} — satisfies the Prepared gate.` : "No hard criterion yet — the Prepared gate needs at least one."}
      </div>
    </Section>
  );
}

function MandateForm({ dealId, onCreated, onCancel }: { dealId: number; onCreated: () => void; onCancel: () => void }) {
  const toast = useToast();
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState("");
  const [side, setSide] = useState<MandateSide | "">("");
  const [status, setStatus] = useState<MandateStatus>("active");
  const [rows, setRows] = useState<Row[]>([blankRow()]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tried, setTried] = useState(false);

  const set = (i: number, patch: Partial<Row>) => setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const problems = rows.map(rowProblem);
  const firstProblem = !title.trim()
    ? "Give the mandate a title."
    : !side
      ? "Pick the mandate's side."
      : problems.find(Boolean) ?? null;
  const hasHard = rows.some((r) => r.hardness === "hard");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setTried(true);
    if (firstProblem || !side) return;
    setBusy(true);
    setError(null);
    try {
      await createMandate(dealId, {
        title: title.trim(),
        notes: notes.trim(),
        side,
        status,
        criteria: rows.map((r) => ({
          criterion_key: r.key.trim(),
          operator: r.operator,
          value: wireValue(r),
          hardness: r.hardness,
          weight: r.hardness !== "hard" && r.weight.trim() ? Number(r.weight) : null,
        })),
      });
      toast(`Mandate “${title.trim()}” recorded`);
      onCreated();
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section
      title="New mandate"
      aside={
        <IconButton size="sm" label="Close" onClick={onCancel}>
          <X className="h-3.5 w-3.5" />
        </IconButton>
      }
    >
      <form onSubmit={submit} className="space-y-4" noValidate>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-[1fr_1fr]">
          <div>
            <label htmlFor="m-title" className={labelCls}>Title</label>
            <input id="m-title" autoFocus value={title} onChange={(e) => setTitle(e.target.value)} className={cx(inputCls, tried && !title.trim() && "border-danger")} placeholder="Buy-side mandate — specialty chemicals" />
          </div>
          <div>
            <label htmlFor="m-notes" className={labelCls}>Notes <span className="font-normal text-muted">· optional</span></label>
            <input id="m-notes" value={notes} onChange={(e) => setNotes(e.target.value)} className={inputCls} placeholder="Context for the team" />
          </div>
          <div>
            <label htmlFor="m-side" className={labelCls}>Side</label>
            <select id="m-side" value={side} onChange={(e) => setSide(e.target.value as MandateSide)} className={cx(selectCls, "w-full", tried && !side && "border-danger")}>
              <option value="" disabled>Choose a side…</option>
              {MANDATE_SIDES.map((s) => (
                <option key={s} value={s}>{SIDE_LABEL[s]}</option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="m-status" className={labelCls}>Status</label>
            <select id="m-status" value={status} onChange={(e) => setStatus(e.target.value as MandateStatus)} className={cx(selectCls, "w-full")}>
              {MANDATE_STATUSES.map((s) => (
                <option key={s} value={s}>{humanize(s)}</option>
              ))}
            </select>
          </div>
        </div>

        <div>
          <div className="mb-1.5 flex items-baseline">
            <span className={cx(labelCls, "mb-0")}>Criteria</span>
            <span className="ml-auto text-[11px] text-muted">Separate lists with commas; numbers are sent as numbers.</span>
          </div>
          <datalist id="crit-keys">
            {KEY_SUGGESTIONS.map((k) => (
              <option key={k} value={k} />
            ))}
          </datalist>
          <ol className="space-y-2">
            {rows.map((r, i) => {
              const bad = tried && problems[i];
              return (
                <li key={i} className={cx("rounded-md border bg-canvas p-3", bad ? "border-danger-border" : "border-line")}>
                  <div className="grid grid-cols-[minmax(0,1.1fr)_130px_minmax(0,1fr)_auto] items-center gap-2">
                    <input aria-label={`Criterion ${i + 1} key`} list="crit-keys" value={r.key} onChange={(e) => set(i, { key: e.target.value })} className={cx(inputCls, "font-mono text-[12px]")} placeholder="sector" />
                    <select aria-label={`Criterion ${i + 1} operator`} value={r.operator} onChange={(e) => set(i, { operator: e.target.value as Operator })} className={selectCls}>
                      {OPERATORS.map((o) => (
                        <option key={o} value={o}>{OP_LABEL[o]}</option>
                      ))}
                    </select>
                    {r.operator === "between" ? (
                      <div className="flex items-center gap-1.5">
                        <input aria-label={`Criterion ${i + 1} from`} value={r.value} onChange={(e) => set(i, { value: e.target.value })} className={inputCls} placeholder="from" />
                        <span className="text-muted">–</span>
                        <input aria-label={`Criterion ${i + 1} to`} value={r.value2} onChange={(e) => set(i, { value2: e.target.value })} className={inputCls} placeholder="to" />
                      </div>
                    ) : (
                      <input aria-label={`Criterion ${i + 1} value`} value={r.value} onChange={(e) => set(i, { value: e.target.value })} className={inputCls} placeholder={r.operator === "in" || r.operator === "not_in" ? "chemicals, pharma" : "chemicals"} />
                    )}
                    <IconButton type="button" label={`Remove criterion ${i + 1}`} disabled={rows.length === 1} onClick={() => setRows(rows.filter((_, j) => j !== i))}>
                      <X className="h-3.5 w-3.5" />
                    </IconButton>
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-3">
                    <Segmented
                      label={`Criterion ${i + 1} kind`}
                      value={r.hardness}
                      onChange={(h) => set(i, { hardness: h })}
                      options={HARDNESS.map((h) => ({ value: h, label: humanize(h), title: HARD_HINT[h] }))}
                    />
                    {r.hardness !== "hard" ? (
                      <label className="flex items-center gap-1.5 text-[12px] text-fg-2">
                        Weight{r.hardness === "soft" ? <span className="text-danger">*</span> : null}
                        <input
                          aria-label={`Criterion ${i + 1} weight`}
                          inputMode="decimal"
                          value={r.weight}
                          onChange={(e) => set(i, { weight: e.target.value })}
                          className={cx(inputCls, "num h-7 w-20! font-mono text-[12px]")}
                          placeholder={r.hardness === "soft" ? "0–1" : "optional"}
                        />
                      </label>
                    ) : null}
                    <span className="text-[12px] text-muted">{HARD_HINT[r.hardness]}</span>
                  </div>
                  {bad ? <p className="mt-2 text-[12px] text-danger">{problems[i]}</p> : null}
                </li>
              );
            })}
          </ol>
          <Button type="button" size="sm" variant="ghost" className="mt-2" onClick={() => setRows([...rows, { ...blankRow(), hardness: "soft" }])}>
            <Plus className="h-3.5 w-3.5" /> Add criterion
          </Button>
        </div>

        {!hasHard ? <Notice tone="warn">Add at least one hard criterion — the Prepared stage gate requires it.</Notice> : null}
        {error ? <Notice tone="error">{error}</Notice> : null}
        <div className="flex items-center justify-end gap-2 border-t border-line-subtle pt-4">
          {tried && firstProblem ? <span className="mr-auto text-[12px] text-danger">{firstProblem}</span> : null}
          <Button type="button" variant="ghost" onClick={onCancel}>Cancel</Button>
          <Button type="submit" loading={busy}>Record mandate</Button>
        </div>
      </form>
    </Section>
  );
}

export function MandateTab({ dealId }: { dealId: number }) {
  const allowed = useCan()("work");
  const mandates = useApi<Mandate[]>(() => listMandates(dealId), [], [dealId], { live: dealEvents(dealId, ["deal"]) });
  const [adding, setAdding] = useState(false);

  if (mandates.unavailable) return <Unavailable what="Mandates" />;
  if (mandates.error) return <InlineError message={mandates.error} onRetry={mandates.refresh} />;
  if (mandates.loading)
    return (
      <div className="rounded-md border border-line bg-surface">
        <SkeletonRows rows={4} />
      </div>
    );

  const newButton = (
    <Permit allow={allowed} why={WHO_CAN.work}>
      <Button size="sm" variant="secondary" onClick={() => setAdding(true)}>
        <Plus className="h-3.5 w-3.5" /> New mandate
      </Button>
    </Permit>
  );

  return (
    <div className="space-y-5">
      {adding ? (
        <MandateForm
          dealId={dealId}
          onCancel={() => setAdding(false)}
          onCreated={() => {
            setAdding(false);
            mandates.refresh();
          }}
        />
      ) : null}
      {mandates.data.length === 0 && !adding ? (
        <div className="rounded-md border border-line bg-surface">
          <EmptyState
            compact
            title="No mandate recorded"
            description="Write down what the client will and won’t accept — hard limits, weighted preferences and tie-breakers. The Prepared gate needs one hard criterion."
            action={newButton}
          />
        </div>
      ) : (
        <>
          {!adding ? <div className="flex justify-end">{newButton}</div> : null}
          {mandates.data.map((m) => (
            <MandateCard key={m.id} m={m} />
          ))}
        </>
      )}
    </div>
  );
}

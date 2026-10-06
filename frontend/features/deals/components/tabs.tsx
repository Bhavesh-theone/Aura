"use client";

import { CornerUpLeft, Flag, Mail, Plus, X } from "lucide-react";
import { useState } from "react";
import { WHO_CAN } from "@/features/auth/roles";
import { useCan } from "@/features/auth/useCan";
import { dealEvents } from "@/shared/api/events";
import { cx, formatDateTime, humanize, stageLabel, titleCase } from "@/shared/lib/format";
import { errMessage, useApi } from "@/shared/lib/useApi";
import { Avatar, Badge, Button, IconButton, Segmented, Tip } from "@/shared/ui/primitives";
import { Permit, RoleNote } from "@/shared/ui/Permit";
import { useToast } from "@/shared/ui/toast";
import {
  addDealParty, createCondition, createParty, listConditions, listDiligence, listDocuments, listFindings, listParties,
  patchCondition, patchDiligence,
} from "../api";
import { CONDITION_STATUSES, CP_TYPES, DILIGENCE_STATUSES, PARTY_TYPES, ROLES, SCHEMES } from "../types";
import type { DealDetail, DealDocument, DealParty, DiligenceItem, Finding } from "../types";
import { DraftEmailSheet } from "./AgentActions";
import { FindingsSection, RaiseFindingSheet } from "./Findings";
import {
  EmptyState, InlineError, Notice, Section, SkeletonRows, Unavailable, inputCls, labelCls, selectCls, textareaCls,
} from "./ui";

function Loading() {
  return (
    <div className="rounded-md border border-line bg-surface">
      <SkeletonRows rows={4} />
    </div>
  );
}

const statusTone = (s: string) =>
  s === "satisfied" ? "success" : s === "waived" ? "info" : s === "failed" ? "danger" : s === "open" ? "neutral" : "warning";

/* ---------------------------------- Parties --------------------------------- */

export function PartiesTab({ deal, onChanged }: { deal: DealDetail; onChanged: () => void }) {
  const allowed = useCan()("work");
  const parties = useApi(listParties, [], [], { live: dealEvents(deal.id, ["deal"]) });
  const [emailTo, setEmailTo] = useState<DealParty | null>(null);
  const [adding, setAdding] = useState(false);
  const [mode, setMode] = useState<"existing" | "new">("existing");
  const [partyId, setPartyId] = useState("");
  const [role, setRole] = useState<string>(ROLES[0]);
  const [partyType, setPartyType] = useState("company");
  const [name, setName] = useState("");
  const [ids, setIds] = useState<{ scheme: string; value: string }[]>([{ scheme: SCHEMES[0], value: "" }]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      let pid = Number(partyId);
      if (mode === "new") {
        const p = await createParty({
          party_type: partyType,
          display_name: name.trim(),
          identifiers: ids.filter((i) => i.value.trim()).map((i) => ({ scheme: i.scheme, value: i.value.trim() })),
        });
        pid = p.id;
      }
      await addDealParty(deal.id, { party_id: pid, role });
      setName("");
      setIds([{ scheme: SCHEMES[0], value: "" }]);
      setPartyId("");
      setAdding(false);
      parties.refresh();
      onChanged();
    } catch (err) {
      // 422 = malformed identifier, 409 = duplicate; the client surfaces the backend message.
      setError(errMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const byId = new Map(parties.data.map((p) => [p.id, p]));

  return (
    <div className="space-y-5">
      <Section
        title="Parties"
        flush
        aside={
          !adding ? (
            <Permit allow={allowed} why={WHO_CAN.work}>
              <Button size="sm" variant="secondary" onClick={() => setAdding(true)}>
                <Plus className="h-3.5 w-3.5" /> Add party
              </Button>
            </Permit>
          ) : null
        }
      >
        {deal.parties.length === 0 ? (
          <EmptyState
            compact
            title="No parties on this deal yet"
            description="Attach the issuer, investors, lenders and advisors with their CIN or PAN."
            action={!adding && allowed ? <Button size="sm" variant="secondary" onClick={() => setAdding(true)}>Add the first party</Button> : undefined}
          />
        ) : (
          <ul>
            {deal.parties.map((p, i) => {
              const full = byId.get(p.party_id);
              return (
                <li key={`${p.party_id}-${p.role}-${i}`} className="flex h-12 items-center gap-3 border-b border-line-subtle px-4 last:border-0">
                  <Avatar name={p.display_name} size={24} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[13px] font-medium text-fg">{p.display_name}</div>
                    {full ? <div className="text-[11px] text-muted">{full.party_type === "llp" ? "LLP" : titleCase(full.party_type)}</div> : null}
                  </div>
                  <div className="hidden items-center gap-1.5 md:flex">
                    {(full?.identifiers ?? []).slice(0, 2).map((idn) => (
                      <span key={idn.scheme + idn.value} className="inline-flex h-5 items-center gap-1.5 rounded-xs border border-line bg-well px-1.5 text-[11px]">
                        <span className="text-muted">{idn.scheme}</span>
                        <span className="font-mono text-fg-2">{idn.value}</span>
                      </span>
                    ))}
                  </div>
                  <Badge className="w-20 justify-center capitalize">{p.role}</Badge>
                  <Permit allow={allowed} why={WHO_CAN.work} side="left">
                    <Tip label="Draft an email with the outreach agent">
                      <IconButton label={`Draft an email to ${p.display_name}`} onClick={() => setEmailTo(p)}>
                        <Mail className="h-4 w-4" />
                      </IconButton>
                    </Tip>
                  </Permit>
                </li>
              );
            })}
          </ul>
        )}
      </Section>

      {adding ? (
        <Section
          title="Add a party"
          aside={
            <div className="flex items-center gap-2">
              <Segmented
                label="Party source"
                value={mode}
                onChange={setMode}
                options={[
                  { value: "existing", label: "Existing" },
                  { value: "new", label: "New" },
                ]}
              />
              <IconButton size="sm" label="Close" onClick={() => setAdding(false)}>
                <X className="h-3.5 w-3.5" />
              </IconButton>
            </div>
          }
        >
          <form onSubmit={submit} className="space-y-4">
            {mode === "existing" ? (
              <div className="grid grid-cols-1 gap-3 md:grid-cols-[1fr_200px]">
                <div>
                  <label htmlFor="pt-party" className={labelCls}>Party</label>
                  {parties.unavailable ? (
                    <Unavailable what="The parties API" />
                  ) : (
                    <select id="pt-party" required value={partyId} onChange={(e) => setPartyId(e.target.value)} className={selectCls}>
                      <option value="">Select a party…</option>
                      {parties.data.map((p) => (
                        <option key={p.id} value={p.id}>{p.display_name}</option>
                      ))}
                    </select>
                  )}
                </div>
                <div>
                  <label htmlFor="pt-role" className={labelCls}>Role on this deal</label>
                  <select id="pt-role" value={role} onChange={(e) => setRole(e.target.value)} className={selectCls}>
                    {ROLES.map((r) => (
                      <option key={r} value={r}>{titleCase(r)}</option>
                    ))}
                  </select>
                </div>
              </div>
            ) : (
              <>
                <div className="grid grid-cols-1 gap-3 md:grid-cols-[1fr_160px_160px]">
                  <div>
                    <label htmlFor="pt-name" className={labelCls}>Legal name</label>
                    <input id="pt-name" required value={name} onChange={(e) => setName(e.target.value)} className={inputCls} placeholder="Kaveri Textiles Ltd." />
                  </div>
                  <div>
                    <label htmlFor="pt-type" className={labelCls}>Party type</label>
                    <select id="pt-type" value={partyType} onChange={(e) => setPartyType(e.target.value)} className={selectCls}>
                      {PARTY_TYPES.map((t) => (
                        <option key={t} value={t}>{t === "llp" || t === "huf" ? t.toUpperCase() : titleCase(t)}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label htmlFor="pt-role2" className={labelCls}>Role on this deal</label>
                    <select id="pt-role2" value={role} onChange={(e) => setRole(e.target.value)} className={selectCls}>
                      {ROLES.map((r) => (
                        <option key={r} value={r}>{titleCase(r)}</option>
                      ))}
                    </select>
                  </div>
                </div>
                <div>
                  <span className={labelCls}>Identifiers</span>
                  <div className="space-y-2">
                    {ids.map((idn, i) => (
                      <div key={i} className="flex gap-2">
                        <select
                          aria-label="Identifier scheme"
                          value={idn.scheme}
                          onChange={(e) => setIds(ids.map((x, j) => (j === i ? { ...x, scheme: e.target.value } : x)))}
                          className={cx(selectCls, "w-28! shrink-0")}
                        >
                          {SCHEMES.map((s) => (
                            <option key={s}>{s}</option>
                          ))}
                        </select>
                        <input
                          aria-label="Identifier value"
                          value={idn.value}
                          onChange={(e) => setIds(ids.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))}
                          className={cx(inputCls, "font-mono uppercase")}
                          placeholder={idn.scheme === "PAN" ? "AAACK1234F" : idn.scheme === "CIN" ? "U17110TZ1998PLC008123" : "Identifier"}
                        />
                        {ids.length > 1 ? (
                          <IconButton type="button" label="Remove identifier" onClick={() => setIds(ids.filter((_, j) => j !== i))}>
                            <X className="h-3.5 w-3.5" />
                          </IconButton>
                        ) : null}
                      </div>
                    ))}
                    <Button type="button" size="sm" variant="ghost" onClick={() => setIds([...ids, { scheme: SCHEMES[0], value: "" }])}>
                      <Plus className="h-3.5 w-3.5" /> Add identifier
                    </Button>
                  </div>
                </div>
              </>
            )}
            {error ? <Notice tone="error">{error}</Notice> : null}
            <div className="flex justify-end gap-2 border-t border-line-subtle pt-4">
              <Button type="button" variant="ghost" onClick={() => setAdding(false)}>Cancel</Button>
              <Button type="submit" loading={busy}>{mode === "new" ? "Create and attach" : "Attach party"}</Button>
            </div>
          </form>
        </Section>
      ) : null}
      <DraftEmailSheet dealId={deal.id} party={emailTo} onClose={() => setEmailTo(null)} />
    </div>
  );
}

/* ---------------------------------- Diligence ------------------------------- */

const SEVERITIES = ["blocker", "material", "standard", "informational"];

function DiligenceRow({
  item,
  docs,
  onSaved,
  onRaise,
  findings,
  allowed,
}: {
  item: DiligenceItem;
  docs: DealDocument[];
  onSaved: () => void;
  onRaise: (item: DiligenceItem) => void;
  findings: number;
  allowed: boolean;
}) {
  const toast = useToast();
  const [status, setStatus] = useState(item.status);
  const [evidence, setEvidence] = useState<number[]>(item.evidence_doc_ids ?? []);
  const [just, setJust] = useState(item.waiver_justification ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const dirty = status !== item.status || (status === "satisfied" && evidence.join() !== (item.evidence_doc_ids ?? []).join());
  const invalid = (status === "satisfied" && evidence.length === 0) || (status === "waived" && !just.trim());
  const resolved = item.status === "satisfied" || item.status === "waived";

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await patchDiligence(item.id, {
        status,
        ...(status === "satisfied" ? { evidence_doc_ids: evidence } : {}),
        ...(status === "waived" ? { waiver_justification: just.trim() } : {}),
      });
      toast("Diligence item updated");
      onSaved();
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="border-b border-line-subtle px-4 py-3 last:border-0">
      <div className="flex items-center gap-3">
        <Badge tone={statusTone(item.status)} className="w-[92px] justify-center">{humanize(item.status)}</Badge>
        <p className={cx("flex-1 text-[13px]", resolved ? "text-fg-2" : "text-fg")}>{item.prompt}</p>
        {findings ? (
          <Tip label={`${findings} finding${findings === 1 ? "" : "s"} raised on this item`}>
            <span tabIndex={0} className="inline-flex shrink-0 items-center gap-1 text-[11px] text-warning outline-none">
              <Flag className="h-3 w-3" /> {findings}
            </span>
          </Tip>
        ) : null}
        <Permit allow={allowed} why={WHO_CAN.work} side="left">
          <Tip label="Raise a finding on this item">
            <IconButton size="sm" label={`Raise a finding on ${item.prompt}`} onClick={() => onRaise(item)} className="shrink-0">
              <Flag className="h-3.5 w-3.5" />
            </IconButton>
          </Tip>
        </Permit>
        <select aria-label="Status" disabled={!allowed} title={allowed ? undefined : WHO_CAN.work} value={status} onChange={(e) => setStatus(e.target.value)} className={cx(selectCls, "h-7 w-36! shrink-0 text-[12px] disabled:opacity-60")}>
          {DILIGENCE_STATUSES.map((s) => (
            <option key={s} value={s}>{humanize(s)}</option>
          ))}
        </select>
      </div>
      {status === "satisfied" && dirty ? (
        <div className="ml-[104px] mt-3">
          <div className={labelCls}>Evidence documents · required</div>
          {docs.length === 0 ? (
            <p className="text-[12px] text-muted">Upload a document first.</p>
          ) : (
            <div className="flex flex-wrap gap-x-4 gap-y-1.5">
              {docs.map((d) => (
                <label key={d.id} className="flex items-center gap-1.5 text-[12px] text-fg">
                  <input
                    type="checkbox"
                    checked={evidence.includes(d.id)}
                    onChange={(e) => setEvidence(e.target.checked ? [...evidence, d.id] : evidence.filter((x) => x !== d.id))}
                  />
                  {d.filename ?? `Document ${d.id}`}
                </label>
              ))}
            </div>
          )}
        </div>
      ) : null}
      {status === "waived" && dirty ? (
        <div className="ml-[104px] mt-3">
          <label className={labelCls}>Waiver justification · required</label>
          <textarea value={just} onChange={(e) => setJust(e.target.value)} rows={2} className={textareaCls} />
        </div>
      ) : null}
      {error ? <div className="ml-[104px] mt-2"><Notice tone="error">{error}</Notice></div> : null}
      {dirty ? (
        <div className="ml-[104px] mt-3 flex gap-2">
          <Button size="sm" onClick={save} loading={busy} disabled={invalid}>Save</Button>
          <Button size="sm" variant="ghost" onClick={() => setStatus(item.status)}>Cancel</Button>
        </div>
      ) : null}
    </li>
  );
}

export function DiligenceTab({ dealId }: { dealId: number }) {
  const allowed = useCan()("work");
  const live = dealEvents(dealId, ["diligence", "document", "finding"]);
  const items = useApi<DiligenceItem[]>(() => listDiligence(dealId), [], [dealId], { live });
  const docs = useApi<DealDocument[]>(() => listDocuments(dealId), [], [dealId], { live });
  const findings = useApi<Finding[]>(() => listFindings(dealId), [], [dealId], { live });
  const [raise, setRaise] = useState<{ item: DiligenceItem | null } | null>(null);
  const perItem = new Map<number, number>();
  for (const f of findings.data) if (f.diligence_item_id) perItem.set(f.diligence_item_id, (perItem.get(f.diligence_item_id) ?? 0) + 1);
  const findingsBlock = (
    <>
      <FindingsSection findings={findings} items={items.data} onRaise={() => setRaise({ item: null })} />
      <RaiseFindingSheet
        dealId={dealId}
        open={raise !== null}
        item={raise?.item ?? null}
        items={items.data}
        onClose={() => setRaise(null)}
        onRaised={findings.refresh}
      />
    </>
  );

  if (items.unavailable) return <Unavailable what="The diligence API" />;
  if (items.loading) return <Loading />;
  if (items.error) return <InlineError message={items.error} onRetry={items.refresh} />;
  if (items.data.length === 0)
    return (
      <div className="space-y-5">
        <div className="rounded-md border border-line bg-surface">
          <EmptyState compact title="No diligence items yet" description="The checklist is created from the class template when the deal enters Diligence." />
        </div>
        {findingsBlock}
      </div>
    );

  const openBlockers = items.data.filter((i) => i.severity === "blocker" && i.status !== "satisfied" && i.status !== "waived").length;
  const done = items.data.filter((i) => i.status === "satisfied" || i.status === "waived").length;

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-4">
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-control-active">
          <div className="h-full rounded-full bg-success" style={{ width: `${(done / items.data.length) * 100}%` }} />
        </div>
        <span className="num text-[12px] text-muted">{done} of {items.data.length} resolved</span>
      </div>
      {openBlockers > 0 ? (
        <Notice tone="error" title={`${openBlockers} open blocker${openBlockers === 1 ? "" : "s"}`}>
          The deal can’t move to Documentation until every blocker is satisfied or waived.
        </Notice>
      ) : null}
      {SEVERITIES.map((sev) => {
        const group = items.data.filter((i) => i.severity === sev);
        if (group.length === 0) return null;
        return (
          <Section
            key={sev}
            flush
            title={
              <span className="flex items-center gap-2">
                {titleCase(sev)} <span className="num font-mono text-[11px] font-normal text-muted">{group.length}</span>
              </span>
            }
          >
            <ul>
              {group.map((item) => (
                <DiligenceRow
                  key={`${item.id}-${item.status}`}
                  item={item}
                  docs={docs.data}
                  onSaved={items.refresh}
                  onRaise={(it) => setRaise({ item: it })}
                  findings={perItem.get(item.id) ?? 0}
                  allowed={allowed}
                />
              ))}
            </ul>
          </Section>
        );
      })}
      {findingsBlock}
    </div>
  );
}

/* ---------------------------------- Conditions ------------------------------ */

export function ConditionsTab({ dealId }: { dealId: number }) {
  const allowed = useCan()("work");
  const conds = useApi(() => listConditions(dealId), [], [dealId], { live: dealEvents(dealId, ["condition"]) });
  const [text, setText] = useState("");
  const [cpType, setCpType] = useState<string>(CP_TYPES[0]);
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [waiving, setWaiving] = useState<{ id: number; text: string } | null>(null);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await createCondition(dealId, { description: text.trim(), cp_type: cpType });
      toast("Condition added");
      setText("");
      conds.refresh();
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function setStatus(id: number, status: string, waiver_justification?: string) {
    setError(null);
    try {
      await patchCondition(id, { status, ...(waiver_justification ? { waiver_justification } : {}) });
      setWaiving(null);
      conds.refresh();
    } catch (err) {
      setError(errMessage(err));
    }
  }

  return (
    <div className="space-y-5">
      <Section title="Conditions precedent" flush>
        {conds.unavailable ? (
          <div className="p-4"><Unavailable what="The conditions API" /></div>
        ) : conds.loading ? (
          <SkeletonRows rows={3} />
        ) : conds.error ? (
          <div className="p-4"><InlineError message={conds.error} onRetry={conds.refresh} /></div>
        ) : conds.data.length === 0 ? (
          <EmptyState compact title="No conditions recorded" description="Add the regulatory approvals, consents and corporate actions that must land before close." />
        ) : (
          <ul>
            {conds.data.map((c) => (
              <li key={c.id} className="border-b border-line-subtle px-4 py-3 last:border-0">
                <div className="flex items-center gap-3">
                  <Badge tone={statusTone(c.status)} className="w-[92px] justify-center">{humanize(c.status)}</Badge>
                  <span className="min-w-0 flex-1 text-[13px] text-fg">{c.description}</span>
                  {c.cp_type ? <span className="hidden text-[12px] text-muted md:inline">{humanize(c.cp_type)}</span> : null}
                  <select
                    aria-label="Status"
                    disabled={!allowed}
                    title={allowed ? undefined : WHO_CAN.work}
                    value={c.status}
                    onChange={(e) => (e.target.value === "waived" ? setWaiving({ id: c.id, text: "" }) : setStatus(c.id, e.target.value))}
                    className={cx(selectCls, "h-7 w-36! shrink-0 text-[12px] disabled:opacity-60")}
                  >
                    {CONDITION_STATUSES.map((s) => (
                      <option key={s} value={s}>{humanize(s)}</option>
                    ))}
                  </select>
                </div>
                {c.waiver_justification ? <p className="ml-[104px] mt-1 text-[12px] text-muted">Waived — {c.waiver_justification}</p> : null}
                {waiving?.id === c.id ? (
                  <div className="ml-[104px] mt-3 space-y-2">
                    <label className={labelCls}>Waiver justification · required</label>
                    <textarea rows={2} value={waiving.text} onChange={(e) => setWaiving({ id: c.id, text: e.target.value })} className={textareaCls} />
                    <div className="flex gap-2">
                      <Button size="sm" disabled={!waiving.text.trim()} onClick={() => setStatus(c.id, "waived", waiving.text.trim())}>Waive condition</Button>
                      <Button size="sm" variant="ghost" onClick={() => setWaiving(null)}>Cancel</Button>
                    </div>
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        )}
        {error ? <div className="p-4 pt-0"><Notice tone="error">{error}</Notice></div> : null}
      </Section>

      {!conds.unavailable && !allowed ? <RoleNote>{WHO_CAN.work} You can read the conditions.</RoleNote> : null}
      {!conds.unavailable && allowed ? (
        <form onSubmit={add} className="flex gap-2">
          <input required aria-label="Condition description" value={text} onChange={(e) => setText(e.target.value)} className={inputCls} placeholder="Add a condition, e.g. CCI approval received" />
          <select aria-label="Condition type" value={cpType} onChange={(e) => setCpType(e.target.value)} className={cx(selectCls, "w-56! shrink-0")}>
            {CP_TYPES.map((t) => (
              <option key={t} value={t}>{humanize(t)}</option>
            ))}
          </select>
          <Button type="submit" variant="secondary" loading={busy} disabled={!text.trim()}>Add</Button>
        </form>
      ) : null}
    </div>
  );
}

/* ----------------------------------- History -------------------------------- */

export function HistoryTab({ deal }: { deal: DealDetail }) {
  if (deal.history.length === 0)
    return (
      <div className="rounded-md border border-line bg-surface">
        <EmptyState compact title="No stage changes yet" description="Each move along the spine is recorded here with who made it and why." />
      </div>
    );
  const rows = [...deal.history].sort((a, b) => (a.entered_at < b.entered_at ? 1 : -1));
  return (
    <Section title="Stage history" flush>
      <ol>
        {rows.map((h, i) => (
          <li key={i} className="grid grid-cols-[150px_1fr_auto] items-center gap-4 border-b border-line-subtle px-4 py-2.5 last:border-0">
            <span className="num font-mono text-[12px] text-muted">{formatDateTime(h.entered_at)}</span>
            <span className="flex min-w-0 items-center gap-2 text-[13px]">
              {h.from_stage ? <span className="text-muted">{stageLabel(h.from_stage)}</span> : null}
              {h.from_stage ? <span className="text-faint">→</span> : null}
              <span className="font-medium text-fg">{stageLabel(h.to_stage)}</span>
              {h.is_regression ? (
                <Badge tone="warning"><CornerUpLeft className="h-3 w-3" /> Regression</Badge>
              ) : null}
              {h.reason_code ? <span className="font-mono text-[11px] text-muted">{h.reason_code}</span> : null}
            </span>
            <span className="flex items-center gap-1.5 text-[12px] text-fg-2">
              {h.actor ? (
                <>
                  <Avatar name={h.actor} size={18} /> {titleCase(h.actor)}
                </>
              ) : (
                <span className="text-muted">System</span>
              )}
            </span>
          </li>
        ))}
      </ol>
    </Section>
  );
}

"use client";

import { ArrowUpRight, Copy, Layers, Plus, Rows3, Rows4, Search } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { cx, stageLabel, titleCase, shortDate, formatDateTime } from "@/shared/lib/format";
import { errMessage } from "@/shared/lib/useApi";
import { FilterChip } from "@/shared/ui/FilterChip";
import { PageHeader } from "@/shared/ui/PageHeader";
import { Avatar, Button, IconButton, Kbd, Segmented, Tip, inputCls, labelCls, selectCls } from "@/shared/ui/primitives";
import { Sheet } from "@/shared/ui/Sheet";
import { EmptyState, InlineError, Notice, SkeletonRows, Unavailable } from "@/shared/ui/States";
import { useToast } from "@/shared/ui/toast";
import { IntakeDraftsList, openIntake } from "@/features/intake";
import { isTyping } from "@/shared/ui/shell/PortalShell";
import { createDeal } from "../api";
import { useDeals } from "../hooks";
import { CLASSES, STAGES, TERMINAL_STAGES, type Deal } from "../types";
import { CLASS_LABEL, ClassChip, StageChip } from "./ui";
import { DealListExportMenu } from "./ExportMenu";

/* -------------------------------- New deal -------------------------------- */

function NewDealSheet({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (id?: number) => void }) {
  const toast = useToast();
  const [externalId, setExternalId] = useState("");
  const [name, setName] = useState("");
  const [cls, setCls] = useState<string>(CLASSES[0]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const d = await createDeal({ external_id: externalId.trim(), name: name.trim(), transaction_class: cls });
      toast(`Deal “${name.trim()}” created`);
      setExternalId("");
      setName("");
      onCreated(d?.id);
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
      title="New deal"
      description="The deal starts at Originated. Every later move is guarded and audited."
      footer={
        <div className="flex items-center justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" form="new-deal" loading={busy} disabled={!externalId.trim() || !name.trim()}>
            Create deal
          </Button>
        </div>
      }
    >
      <form id="new-deal" onSubmit={submit} className="space-y-4">
        <div>
          <label htmlFor="nd-name" className={labelCls}>Deal name</label>
          <input id="nd-name" autoFocus required value={name} onChange={(e) => setName(e.target.value)} className={inputCls} placeholder="e.g. Sunrise Infra — senior secured debt" />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label htmlFor="nd-ext" className={labelCls}>Reference ID</label>
            <input id="nd-ext" required value={externalId} onChange={(e) => setExternalId(e.target.value)} className={cx(inputCls, "font-mono")} placeholder="OBS-2026-014" />
          </div>
          <div>
            <label htmlFor="nd-cls" className={labelCls}>Transaction class</label>
            <select id="nd-cls" value={cls} onChange={(e) => setCls(e.target.value)} className={selectCls}>
              {CLASSES.map((c) => (
                <option key={c} value={c}>{CLASS_LABEL[c] ?? c}</option>
              ))}
            </select>
          </div>
        </div>
        {error ? <Notice tone="error">{error}</Notice> : null}
      </form>
    </Sheet>
  );
}

/* ---------------------------------- Table --------------------------------- */

type Density = "compact" | "default";
const ALL_STAGES = [...STAGES, ...TERMINAL_STAGES] as readonly string[];

function usePref<T extends string>(key: string, initial: T): [T, (v: T) => void] {
  const [v, setV] = useState<T>(initial);
  useEffect(() => {
    try {
      const s = localStorage.getItem(key);
      if (s) setV(s as T);
    } catch {
      /* ignore */
    }
  }, [key]);
  const set = useCallback(
    (next: T) => {
      setV(next);
      try {
        localStorage.setItem(key, next);
      } catch {
        /* ignore */
      }
    },
    [key],
  );
  return [v, set];
}

const COLS = "grid-cols-[minmax(260px,1fr)_120px_96px_180px_150px_96px_64px]";

export function DealsTable() {
  const router = useRouter();
  const toast = useToast();
  const { deals, loading, unavailable, error, refresh } = useDeals();
  const [query, setQuery] = useState("");
  const [fClass, setFClass] = useState<string[]>([]);
  const [fStage, setFStage] = useState<string[]>([]);
  const [fOutcome, setFOutcome] = useState<string[]>([]);
  const [density, setDensity] = usePref<Density>("aura_density", "default");
  const [grouping, setGrouping] = usePref<"none" | "stage">("aura_group", "none");
  const [showNew, setShowNew] = useState(false);
  const [cursor, setCursor] = useState(0);
  const searchRef = useRef<HTMLInputElement>(null);

  // The command palette links here with ?new=1 (or fires an event if we're already here).
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("new") === "1") setShowNew(true);
    const on = () => setShowNew(true);
    window.addEventListener("aura:new-deal", on);
    return () => window.removeEventListener("aura:new-deal", on);
  }, []);

  const outcomeOf = (d: Deal) => (d.outcome ? d.outcome.toUpperCase() : "OPEN");

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = deals.filter(
      (d) =>
        (!q || `${d.name} ${d.external_id} ${d.owner ?? ""} ${d.stage} ${d.transaction_class}`.toLowerCase().includes(q)) &&
        (fClass.length === 0 || fClass.includes(d.transaction_class)) &&
        (fStage.length === 0 || fStage.includes(d.stage)) &&
        (fOutcome.length === 0 || fOutcome.includes(outcomeOf(d))),
    );
    return grouping === "stage"
      ? [...list].sort((a, b) => ALL_STAGES.indexOf(a.stage) - ALL_STAGES.indexOf(b.stage))
      : list;
  }, [deals, query, fClass, fStage, fOutcome, grouping]);

  useEffect(() => setCursor((c) => Math.min(c, Math.max(0, rows.length - 1))), [rows.length]);

  // j/k + Enter, / to search. (c → new deal is global, in the portal shell.)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e.target) || e.metaKey || e.ctrlKey || e.altKey || document.querySelector("[role=dialog]")) return;
      if (e.key === "j" || e.key === "ArrowDown") {
        e.preventDefault();
        setCursor((c) => Math.min(rows.length - 1, c + 1));
      } else if (e.key === "k" || e.key === "ArrowUp") {
        e.preventDefault();
        setCursor((c) => Math.max(0, c - 1));
      } else if (e.key === "Enter" && rows[cursor]) {
        router.push(`/deals/${rows[cursor].id}`);
      } else if (e.key === "/") {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [rows, cursor, router]);

  useEffect(() => {
    document.querySelector(`[data-row="${cursor}"]`)?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  const count = (pred: (d: Deal) => boolean) => deals.filter(pred).length;
  const classOpts = CLASSES.map((c) => ({ value: c, label: CLASS_LABEL[c] ?? c, count: count((d) => d.transaction_class === c) })).filter((o) => o.count > 0);
  const stageOpts = ALL_STAGES.map((s) => ({ value: s, label: stageLabel(s), count: count((d) => d.stage === s) })).filter((o) => o.count > 0);
  const outcomeVals = Array.from(new Set(deals.map(outcomeOf)));
  const outcomeOpts = outcomeVals.map((o) => ({ value: o, label: titleCase(o.toLowerCase()), count: count((d) => outcomeOf(d) === o) }));
  const filtered = query || fClass.length || fStage.length || fOutcome.length;
  const rowH = density === "compact" ? 36 : 40;

  const newButton = (
    <Tip label="New deal" keys="c">
      <Button onClick={() => openIntake(router)}>
        <Plus className="h-4 w-4" strokeWidth={2.2} /> New deal
      </Button>
    </Tip>
  );

  let lastStage = "";
  return (
    <div className="flex flex-1 flex-col pb-10">
      <PageHeader
        title="Deals"
        meta={deals.length === 0 ? null : <span className="num">{rows.length} of {deals.length}</span>}
        description="Every mandate on the desk, where it sits on the 12-stage spine, and who owns it."
        actions={newButton}
      />

      <IntakeDraftsList className="mx-8 mb-4" />

      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2 px-8 pb-3">
        <div className="relative w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted" />
          <input
            ref={searchRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Escape" && (e.currentTarget.blur(), setQuery(""))}
            aria-label="Filter deals"
            placeholder="Filter by name, ID, owner…"
            className={cx(inputCls, "h-7 pl-8 pr-8 text-[12px]")}
          />
          <Kbd className="absolute right-2 top-1/2 -translate-y-1/2">/</Kbd>
        </div>
        <FilterChip label="Class" options={classOpts} value={fClass} onChange={setFClass} />
        <FilterChip label="Stage" options={stageOpts} value={fStage} onChange={setFStage} />
        <FilterChip label="Outcome" options={outcomeOpts} value={fOutcome} onChange={setFOutcome} />
        {filtered ? (
          <button
            onClick={() => {
              setQuery("");
              setFClass([]);
              setFStage([]);
              setFOutcome([]);
            }}
            className="h-7 px-1.5 text-[12px] text-muted hover:text-fg"
          >
            Clear
          </button>
        ) : null}
        <div className="ml-auto flex items-center gap-2">
          <DealListExportMenu
            filters={{ q: query, classes: fClass, stages: fStage, outcomes: fOutcome }}
            count={rows.length}
            filtered={Boolean(filtered)}
          />
          <Tip label={grouping === "stage" ? "Ungroup" : "Group by stage"}>
            <button
              onClick={() => setGrouping(grouping === "stage" ? "none" : "stage")}
              aria-pressed={grouping === "stage"}
              className={cx(
                "inline-flex h-7 items-center gap-1.5 rounded-sm border px-2 text-[12px] transition-colors",
                grouping === "stage" ? "border-accent-border bg-accent-soft text-fg" : "border-line text-fg-2 hover:bg-control-hover",
              )}
            >
              <Layers className="h-3.5 w-3.5" /> Group by stage
            </button>
          </Tip>
          <Segmented
            label="Row density"
            value={density}
            onChange={setDensity}
            options={[
              { value: "compact", label: <Rows4 className="h-3.5 w-3.5" />, title: "Compact rows (36px)" },
              { value: "default", label: <Rows3 className="h-3.5 w-3.5" />, title: "Comfortable rows (40px)" },
            ]}
          />
        </div>
      </div>

      <div className="px-8">
        {unavailable ? (
          <Unavailable what="The deals API" />
        ) : error ? (
          <InlineError message={error} onRetry={refresh} />
        ) : (
          <div className="rounded-md border border-line bg-surface shadow-card" role="grid" aria-label="Deals" aria-rowcount={rows.length}>
            {/* sticky header */}
            <div
              role="row"
              className={cx(
                "sticky top-12 z-10 grid h-9 items-center gap-4 rounded-t-md border-b border-line bg-surface/95 px-4 text-[12px] font-medium text-muted backdrop-blur",
                COLS,
              )}
            >
              <span role="columnheader">Deal</span>
              <span role="columnheader">Reference</span>
              <span role="columnheader">Class</span>
              <span role="columnheader">Stage</span>
              <span role="columnheader">Owner</span>
              <span role="columnheader" className="text-right">Opened</span>
              <span role="columnheader" className="sr-only">Actions</span>
            </div>

            {loading && deals.length === 0 ? (
              <SkeletonRows rows={8} height={rowH} />
            ) : rows.length === 0 ? (
              filtered ? (
                <EmptyState
                  compact
                  title="No deals match these filters"
                  description="Loosen a filter or clear the search to see the full book."
                  action={
                    <Button variant="secondary" size="sm" onClick={() => { setQuery(""); setFClass([]); setFStage([]); setFOutcome([]); }}>
                      Clear filters
                    </Button>
                  }
                />
              ) : (
                <EmptyState
                  compact
                  title="No deals on the desk yet"
                  description="Create a deal to start it on the stage spine, from Originated to Closed."
                  action={newButton}
                />
              )
            ) : (
              rows.map((d, i) => {
                const header = grouping === "stage" && d.stage !== lastStage;
                lastStage = d.stage;
                const groupCount = header ? rows.filter((r) => r.stage === d.stage).length : 0;
                const sel = i === cursor;
                return (
                  <Fragment key={d.id}>
                    {header ? (
                      <div className="flex h-8 items-center gap-2 border-b border-line-subtle bg-canvas px-4 text-[12px]">
                        <StageChip stage={d.stage} outcome={d.outcome} showStep />
                        <span className="num font-mono text-[11px] text-muted">{groupCount}</span>
                      </div>
                    ) : null}
                    <div
                      role="row"
                      data-row={i}
                      aria-selected={sel}
                      onMouseEnter={() => setCursor(i)}
                      onClick={() => router.push(`/deals/${d.id}`)}
                      style={{ height: rowH }}
                      className={cx(
                        "group relative grid cursor-default items-center gap-4 border-b border-line-subtle px-4 last:border-0 last:rounded-b-md",
                        COLS,
                        sel ? "bg-well" : "",
                      )}
                    >
                      {sel ? <span aria-hidden className="absolute inset-y-0 left-0 w-[2px] bg-accent" /> : null}
                      <span role="gridcell" className="flex min-w-0 items-center gap-2.5">
                        <Link
                          href={`/deals/${d.id}`}
                          onClick={(e) => e.stopPropagation()}
                          className="truncate text-[13px] font-medium text-fg hover:underline hover:decoration-line-strong hover:underline-offset-2"
                        >
                          {d.name}
                        </Link>
                      </span>
                      <span role="gridcell" className="truncate font-mono text-[12px] text-fg-2">{d.external_id}</span>
                      <span role="gridcell"><ClassChip cls={d.transaction_class} /></span>
                      <span role="gridcell"><StageChip stage={d.stage} outcome={d.outcome} showStep /></span>
                      <span role="gridcell" className="flex min-w-0 items-center gap-2 text-[12px] text-fg-2">
                        {d.owner ? (
                          <>
                            <Avatar name={d.owner} size={18} />
                            <span className="truncate">{titleCase(d.owner)}</span>
                          </>
                        ) : (
                          <span className="text-muted">Unassigned</span>
                        )}
                      </span>
                      <span role="gridcell" className="num text-right text-[12px] text-muted" title={formatDateTime(d.opened_at)}>
                        {shortDate(d.opened_at)}
                      </span>
                      <span role="gridcell" className={cx("flex justify-end gap-0.5 transition-opacity duration-[var(--dur-1)]", sel ? "opacity-100" : "opacity-0 group-hover:opacity-100")}>
                        <Tip label="Copy reference">
                          <IconButton
                            size="sm"
                            label={`Copy ${d.external_id}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              navigator.clipboard?.writeText(d.external_id).then(() => toast(`Copied ${d.external_id}`, "info"));
                            }}
                          >
                            <Copy className="h-3.5 w-3.5" />
                          </IconButton>
                        </Tip>
                        <Tip label="Open" keys="↵">
                          <IconButton size="sm" label={`Open ${d.name}`} onClick={(e) => { e.stopPropagation(); router.push(`/deals/${d.id}`); }}>
                            <ArrowUpRight className="h-3.5 w-3.5" />
                          </IconButton>
                        </Tip>
                      </span>
                    </div>
                  </Fragment>
                );
              })
            )}
          </div>
        )}
        {rows.length > 0 ? (
          <div className="mt-3 flex items-center gap-4 text-[12px] text-muted">
            <span className="flex items-center gap-1.5"><Kbd>j</Kbd><Kbd>k</Kbd> move</span>
            <span className="flex items-center gap-1.5"><Kbd>↵</Kbd> open</span>
            <span className="flex items-center gap-1.5"><Kbd>c</Kbd> new deal</span>
            <span className="num ml-auto">{rows.length} shown</span>
          </div>
        ) : null}
      </div>

      <NewDealSheet
        open={showNew}
        onClose={() => setShowNew(false)}
        onCreated={(id) => {
          setShowNew(false);
          refresh();
          if (id) router.push(`/deals/${id}`);
        }}
      />
    </div>
  );
}

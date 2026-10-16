"use client";

import * as Tabs from "@radix-ui/react-tabs";
import { ArrowRight, Calendar, Copy, Users } from "lucide-react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { WHO_CAN } from "@/features/auth/roles";
import { useCan } from "@/features/auth/useCan";
import { dealEvents } from "@/shared/api/events";
import { formatDateTime, stageLabel, timeAgo, titleCase } from "@/shared/lib/format";
import { useApi } from "@/shared/lib/useApi";
import { Avatar, Button, Card, IconButton, IdChip, Tip } from "@/shared/ui/primitives";
import { Permit } from "@/shared/ui/Permit";
import { useCrumbs } from "@/shared/ui/shell/crumbs";
import { isTyping } from "@/shared/ui/shell/PortalShell";
import { EmptyState, InlineError, Skel } from "@/shared/ui/States";
import { useToast } from "@/shared/ui/toast";
import { getDeal } from "../api";
import { isTerminal, type DealDetail } from "../types";
import { AdvanceSheet } from "./AdvanceSheet";
import { StageRail } from "./StageRail";
import { ComplianceCard, NotesCard, TeamCard } from "./DealRail";
import { DocumentsTab } from "./DocumentsTab";
import { DealExportMenu } from "./ExportMenu";
import { ExtractionsTab } from "./ExtractionsTab";
import { MandateTab } from "./MandateTab";
import { RunsTab } from "./RunsTab";
import { ConditionsTab, DiligenceTab, HistoryTab, PartiesTab } from "./tabs";
import { ClassChip, StageChip } from "./ui";

const TABS = ["Parties", "Mandate", "Documents", "Diligence", "Conditions", "Extractions", "History", "Agent runs"] as const;
/** `?tab=` slug for a tab: "Agent runs" → "agent-runs". Activity links use these. */
const tabSlug = (t: string) => t.toLowerCase().replace(/\s+/g, "-");
const tabFromSlug = (slug: string | null) => TABS.find((t) => tabSlug(t) === slug);

function DetailSkeleton() {
  return (
    <div className="px-8 pt-7" aria-busy="true" aria-label="Loading deal">
      <Skel className="h-3 w-24" />
      <Skel className="mt-3 h-8 w-[420px]" />
      <div className="mt-3 flex gap-2">
        <Skel className="h-5 w-24" />
        <Skel className="h-5 w-14" />
        <Skel className="h-5 w-20" />
      </div>
      <div className="mt-8 grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_300px]">
        <div>
          <Skel className="h-[92px] w-full rounded-md" />
          <div className="mt-8 flex gap-6">
            {TABS.map((t) => (
              <Skel key={t} className="h-3 w-14" />
            ))}
          </div>
          <Skel className="mt-5 h-48 w-full rounded-md" />
        </div>
        <div className="space-y-3">
          <Skel className="h-40 w-full rounded-md" />
          <Skel className="h-48 w-full rounded-md" />
        </div>
      </div>
    </div>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] text-muted">{label}</dt>
      <dd className="mt-1 flex min-w-0 items-center gap-1.5 truncate text-[13px] text-fg">{children}</dd>
    </div>
  );
}

export function DealDetailView() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const toast = useToast();
  const allowed = useCan();
  const canMove = allowed("transition");
  // Compliance opens the sheet only to override compliance-owned guards.
  const canOverrideMove = allowed("overrideTransition");
  const canOpenSheet = canMove || canOverrideMove;
  const searchParams = useSearchParams();
  const tabParam = tabFromSlug(searchParams.get("tab"));
  const { data: deal, loading, error, unavailable, refresh } = useApi<DealDetail | null>(
    Number.isFinite(id) ? () => getDeal(id) : null,
    null,
    [id],
    { live: dealEvents(id, ["deal"]) },
  );
  const [tab, setTab] = useState<string>(tabParam ?? "Parties");
  useEffect(() => {
    if (tabParam) setTab(tabParam);
  }, [tabParam]);
  const [sheet, setSheet] = useState(false);

  useCrumbs([{ label: "Deals", href: "/deals" }, { label: deal?.name ?? (unavailable ? "Not found" : "…") }]);

  // "a" opens the advance sheet.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e.target) || e.metaKey || e.ctrlKey || document.querySelector("[role=dialog]")) return;
      if (e.key === "a" && deal && deal.allowed_next.length && canOpenSheet) {
        e.preventDefault();
        setSheet(true);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [deal, canOpenSheet]);

  if (unavailable || (!loading && !error && !deal)) {
    return (
      <EmptyState
        title="Deal not found, or you don’t have access"
        description="Deals are visible to their team only. Ask the deal owner to add you, or check the link."
        action={
          <Link href="/deals">
            <Button variant="secondary">Back to deals</Button>
          </Link>
        }
      />
    );
  }
  if (error) {
    return (
      <div className="px-8 pt-8">
        <InlineError message={error} onRetry={refresh} />
      </div>
    );
  }
  if (!deal) return <DetailSkeleton />;

  const terminal = isTerminal(deal.stage);
  const firstEntry = [...deal.history].sort((a, b) => (a.entered_at < b.entered_at ? -1 : 1))[0];

  return (
    <div className="a-fade flex flex-1 flex-col pb-12">
      {/* Header */}
      <div className="px-8 pt-7">
        <div className="flex flex-wrap items-start gap-x-6 gap-y-4">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <IdChip>{deal.external_id}</IdChip>
              <Tip label="Copy reference">
                <IconButton
                  size="sm"
                  label="Copy reference"
                  onClick={() => navigator.clipboard?.writeText(deal.external_id).then(() => toast(`Copied ${deal.external_id}`, "info"))}
                >
                  <Copy className="h-3 w-3" />
                </IconButton>
              </Tip>
              <ClassChip cls={deal.transaction_class} />
              <StageChip stage={deal.stage} outcome={deal.outcome} />
            </div>
            <h1 className="mt-2.5 font-serif text-[36px] leading-[1.1] text-fg">{deal.name}</h1>
          </div>
          <div className="flex items-center gap-2 pt-6">
            <DealExportMenu dealId={deal.id} dealName={deal.name} externalId={deal.external_id} />
            {canMove ? (
              <Tip label={deal.allowed_next.length ? "Advance stage" : terminal ? "This deal has ended" : "No further moves"} keys={deal.allowed_next.length ? "a" : undefined}>
                <span>
                  <Button size="lg" onClick={() => setSheet(true)} disabled={deal.allowed_next.length === 0}>
                    Advance stage <ArrowRight className="h-3.5 w-3.5" />
                  </Button>
                </span>
              </Tip>
            ) : canOverrideMove ? (
              <Tip label={deal.allowed_next.length ? WHO_CAN.overrideTransition : terminal ? "This deal has ended" : "No further moves"} keys={deal.allowed_next.length ? "a" : undefined}>
                <span>
                  <Button size="lg" variant="secondary" onClick={() => setSheet(true)} disabled={deal.allowed_next.length === 0}>
                    Advance stage <ArrowRight className="h-3.5 w-3.5" />
                  </Button>
                </span>
              </Tip>
            ) : (
              <Permit allow={false} why={WHO_CAN.transition} side="bottom">
                <Button size="lg">
                  Advance stage <ArrowRight className="h-3.5 w-3.5" />
                </Button>
              </Permit>
            )}
          </div>
        </div>

        <dl className="mt-5 grid grid-cols-2 gap-x-8 gap-y-3 border-t border-line pt-4 sm:grid-cols-[repeat(4,minmax(0,180px))]">
          <Fact label="Owner">
            {deal.owner ? (
              <>
                <Avatar name={deal.owner} size={18} /> {titleCase(deal.owner)}
              </>
            ) : (
              <span className="text-muted">Unassigned</span>
            )}
          </Fact>
          <Fact label="Opened">
            <Calendar className="h-3.5 w-3.5 text-muted" />
            <span className="num" title={formatDateTime(deal.opened_at)}>{formatDateTime(deal.opened_at).split(",")[0]}</span>
          </Fact>
          <Fact label="Parties">
            <Users className="h-3.5 w-3.5 text-muted" />
            <span className="num">{deal.parties.length}</span>
          </Fact>
          <Fact label={terminal || deal.closed_at ? "Closed" : "Last move"}>
            <span className="num">
              {deal.closed_at
                ? formatDateTime(deal.closed_at).split(",")[0]
                : deal.history.length
                  ? timeAgo([...deal.history].sort((a, b) => (a.entered_at < b.entered_at ? 1 : -1))[0].entered_at)
                  : firstEntry
                    ? timeAgo(firstEntry.entered_at)
                    : "—"}
            </span>
          </Fact>
        </dl>
      </div>

      <div className="grid grid-cols-1 items-start gap-6 px-8 pt-6 xl:grid-cols-[minmax(0,1fr)_300px]">
        <div className="min-w-0">
          {/* Stage rail */}
          <Card className="px-5 pb-4 pt-4">
            <StageRail deal={deal} />
            {terminal ? (
              <p className="mt-3 text-[12px] text-danger">
                Ended as {stageLabel(deal.stage)}
                {deal.outcome ? ` · outcome ${titleCase(deal.outcome.toLowerCase())}` : ""}
                {deal.closed_at ? ` · ${formatDateTime(deal.closed_at)}` : ""}
              </p>
            ) : null}
          </Card>

          {/* Tabs */}
          <Tabs.Root value={tab} onValueChange={setTab} className="mt-6">
            <Tabs.List aria-label="Deal sections" className="scroll flex gap-5 overflow-x-auto border-b border-line">
              {TABS.map((t) => (
                <Tabs.Trigger
                  key={t}
                  value={t}
                  className="relative -mb-px flex h-10 shrink-0 items-center gap-1.5 border-b-2 border-transparent text-[13px] text-muted outline-none transition-colors hover:text-fg focus-visible:border-accent data-[state=active]:border-fg data-[state=active]:font-medium data-[state=active]:text-fg focus-visible:text-fg"
                >
                  {t}
                  {t === "Parties" && deal.parties.length ? <span className="num font-mono text-[11px] text-muted">{deal.parties.length}</span> : null}
                  {t === "History" && deal.history.length ? <span className="num font-mono text-[11px] text-muted">{deal.history.length}</span> : null}
                </Tabs.Trigger>
              ))}
            </Tabs.List>
            <div className="pt-5">
              <Tabs.Content value="Parties" className="outline-none"><PartiesTab deal={deal} onChanged={refresh} /></Tabs.Content>
              <Tabs.Content value="Mandate" className="outline-none"><MandateTab dealId={deal.id} /></Tabs.Content>
              <Tabs.Content value="Documents" className="outline-none"><DocumentsTab dealId={deal.id} /></Tabs.Content>
              <Tabs.Content value="Diligence" className="outline-none"><DiligenceTab dealId={deal.id} /></Tabs.Content>
              <Tabs.Content value="Conditions" className="outline-none"><ConditionsTab dealId={deal.id} /></Tabs.Content>
              <Tabs.Content value="Extractions" className="outline-none"><ExtractionsTab dealId={deal.id} /></Tabs.Content>
              <Tabs.Content value="History" className="outline-none"><HistoryTab deal={deal} /></Tabs.Content>
              <Tabs.Content value="Agent runs" className="outline-none"><RunsTab dealId={deal.id} /></Tabs.Content>
            </div>
          </Tabs.Root>
        </div>

        {/* Right rail */}
        <aside aria-label="Deal team and compliance" className="space-y-3 xl:sticky xl:top-[60px]">
          <TeamCard deal={deal} />
          <ComplianceCard deal={deal} onChanged={refresh} />
          <NotesCard deal={deal} />
        </aside>
      </div>

      <AdvanceSheet deal={deal} open={sheet} onClose={() => setSheet(false)} onDone={refresh} />
    </div>
  );
}

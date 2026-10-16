"use client";

import { FileText, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { cx, timeAgo } from "@/shared/lib/format";
import { errMessage, useApi } from "@/shared/lib/useApi";
import { Badge, Button, IconButton, Spinner, Tip } from "@/shared/ui/primitives";
import { InlineError } from "@/shared/ui/States";
import { useToast } from "@/shared/ui/toast";
import { discardIntake, listIntakes } from "../api";
import { intakeEvents } from "../hooks";
import { CLASS_LABEL, type IntakeSummary } from "../types";
import { ProgressBar } from "./bits";

function statusOf(d: IntakeSummary): { label: string; tone: "neutral" | "info" | "warning" | "danger" | "success" } {
  if (d.progress.stage === "failed") return { label: "Extraction failed", tone: "danger" };
  if (d.status === "review") return { label: "Ready to review", tone: "success" };
  if (d.status === "processing" || d.progress.stage === "indexing" || d.progress.stage === "extracting") return { label: "Processing", tone: "info" };
  return { label: "Draft", tone: "neutral" };
}

function DraftRow({ d, onGone }: { d: IntakeSummary; onGone: () => void }) {
  const router = useRouter();
  const toast = useToast();
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const st = statusOf(d);
  const working = st.label === "Processing";

  async function discard() {
    setBusy(true);
    setError(null);
    try {
      await discardIntake(d.id);
      toast(`Draft “${d.title}” discarded`);
      onGone();
    } catch (err) {
      setError(errMessage(err));
      setBusy(false);
    }
  }

  return (
    <li className="px-4 py-2.5">
      <div className="flex items-center gap-3">
        <FileText className="h-4 w-4 shrink-0 text-muted" aria-hidden />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-[13px] font-medium text-fg">{d.title}</span>
            <Badge tone={st.tone}>{working ? <Spinner className="h-2.5 w-2.5" /> : null}{st.label}</Badge>
            {d.transaction_class ? <Badge>{CLASS_LABEL[d.transaction_class] ?? d.transaction_class}</Badge> : null}
          </div>
          <div className="mt-0.5 flex items-center gap-2 text-[12px] text-muted">
            <span className="num">{d.files} document{d.files === 1 ? "" : "s"}</span>
            <span aria-hidden>·</span>
            <span>updated {timeAgo(d.updated_at)}</span>
            {working && d.progress.message ? (
              <>
                <span aria-hidden>·</span>
                <span className="truncate">{d.progress.message}</span>
              </>
            ) : null}
          </div>
          {working ? <ProgressBar className="mt-1.5 max-w-xs" pct={d.progress.percent} label={`${d.title} progress`} /> : null}
        </div>
        {asking ? (
          <div className="flex shrink-0 items-center gap-2" role="group" aria-label={`Discard ${d.title}?`}>
            <span className="text-[12px] text-fg-2">Discard this draft and its files?</span>
            <Button size="sm" variant="ghost" onClick={() => setAsking(false)} disabled={busy} autoFocus>Keep</Button>
            <Button size="sm" variant="danger" onClick={discard} loading={busy}>Discard</Button>
          </div>
        ) : (
          <div className="flex shrink-0 items-center gap-1">
            <Button size="sm" variant="secondary" onClick={() => router.push(`/deals/new?intake=${d.id}`)}>
              {d.status === "review" ? "Review" : "Resume"}
            </Button>
            <Tip label="Discard draft">
              <IconButton size="sm" label={`Discard draft ${d.title}`} onClick={() => setAsking(true)}>
                <Trash2 className="h-3.5 w-3.5" />
              </IconButton>
            </Tip>
          </div>
        )}
      </div>
      {error ? <p className="mt-1.5 pl-7 text-[12px] text-danger">{error}</p> : null}
    </li>
  );
}

/** The current user's unfinished intakes. Renders nothing when there are none. */
export function IntakeDraftsList({ className }: { className?: string }) {
  const drafts = useApi<IntakeSummary[]>(listIntakes, [], [], { live: intakeEvents(), pollMs: 15000 });
  if (drafts.loading || drafts.unavailable || drafts.forbidden) return null;
  if (drafts.error) {
    return (
      <div className={className}>
        <InlineError message={`Drafts: ${drafts.error}`} onRetry={drafts.refresh} />
      </div>
    );
  }
  if (drafts.data.length === 0) return null;
  return (
    <section aria-labelledby="drafts-h" className={cx("rounded-md border border-line bg-surface shadow-card", className)}>
      <div className="flex h-10 items-center gap-2 border-b border-line-subtle px-4">
        <h2 id="drafts-h" className="text-[13px] font-medium text-fg">Drafts</h2>
        <span className="num text-[12px] text-muted">{drafts.data.length}</span>
        <span className="ml-auto text-[12px] text-muted">Deals you started from documents — only you can see these.</span>
      </div>
      <ul className="divide-y divide-line-subtle">
        {drafts.data.map((d) => (
          <DraftRow key={d.id} d={d} onGone={drafts.refresh} />
        ))}
      </ul>
    </section>
  );
}

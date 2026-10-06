"use client";

import { Mail, Sparkles } from "lucide-react";
import { useCallback, useState } from "react";
import { useCan } from "@/features/auth/useCan";
import { WHO_CAN } from "@/features/auth/roles";
import { CAPABILITY_LABEL, runCapability } from "@/features/jobs/api";
import type { Capability } from "@/features/jobs/types";
import { errMessage } from "@/shared/lib/useApi";
import { Button, labelCls, textareaCls } from "@/shared/ui/primitives";
import { Permit } from "@/shared/ui/Permit";
import { Sheet } from "@/shared/ui/Sheet";
import { Notice } from "@/shared/ui/States";
import { useToast } from "@/shared/ui/toast";

const AFTER: Record<Capability, string> = {
  classify_document: "the proposed class will arrive in Decisions for confirmation",
  extract_financials: "extracted figures will appear under Extractions for verification",
  draft_email: "the draft will arrive in Decisions — nothing is sent without approval",
};

/** Launch an agent capability against a deal object, with a toast that says what happens next. */
export function useRunAgent(dealId: number) {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const run = useCallback(
    async (capability: Capability, target: { document_id?: number; party_id?: number; brief?: string }, key: string = capability) => {
      setBusy(key);
      try {
        const job = await runCapability(dealId, capability, target);
        toast(`${CAPABILITY_LABEL[capability]} queued${job?.id ? ` as JOB-${job.id}` : ""} — ${AFTER[capability]}.`);
        return true;
      } catch (err) {
        toast(errMessage(err), "error");
        return false;
      } finally {
        setBusy(null);
      }
    },
    [dealId, toast],
  );
  return { run, busy };
}

const BRIEF_PRESETS = [
  "Introduce the opportunity and ask for a first call next week.",
  "Request the latest audited financials and the cap table.",
  "Follow up on the term sheet comments shared last week.",
];

/** Brief → draft_email job for one party. The draft always comes back as a handoff. */
export function DraftEmailSheet({
  dealId,
  party,
  onClose,
}: {
  dealId: number;
  party: { party_id: number; display_name: string; role: string } | null;
  onClose: () => void;
}) {
  const allowed = useCan()("work");
  const { run, busy } = useRunAgent(dealId);
  const [brief, setBrief] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!party) return;
    setError(null);
    const ok = await run("draft_email", { party_id: party.party_id, brief: brief.trim() }, `email-${party.party_id}`);
    if (ok) {
      setBrief("");
      onClose();
    } else setError("The draft couldn’t be queued. Check the message above and try again.");
  }

  return (
    <Sheet
      open={party !== null}
      onClose={onClose}
      eyebrow={
        <span className="inline-flex items-center gap-1.5">
          <Sparkles className="h-3.5 w-3.5 text-accent" /> Agent action
        </span>
      }
      title={party ? `Draft an email to ${party.display_name}` : "Draft an email"}
      description="The outreach agent writes a draft from your brief. It is never sent: the draft lands in Decisions for a dealmaker to approve or reject."
      footer={
        <div className="flex items-center justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Permit allow={allowed} why={WHO_CAN.work}>
            <Button type="submit" form="draft-email" loading={busy !== null} disabled={!brief.trim()}>
              <Mail className="h-3.5 w-3.5" /> Queue draft
            </Button>
          </Permit>
        </div>
      }
    >
      <form id="draft-email" onSubmit={submit} className="space-y-4">
        <div>
          <label htmlFor="de-brief" className={labelCls}>Brief for the agent</label>
          <textarea
            id="de-brief"
            autoFocus
            rows={5}
            value={brief}
            onChange={(e) => setBrief(e.target.value)}
            className={textareaCls}
            placeholder="What should the email achieve? Mention anything it must or must not say."
          />
          <div className="mt-2 flex flex-wrap gap-1">
            {BRIEF_PRESETS.map((b) => (
              <button
                key={b}
                type="button"
                onClick={() => setBrief(b)}
                className="inline-flex h-6 items-center rounded-full border border-line bg-well px-2 text-[11px] text-fg-2 hover:border-line-strong hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50"
              >
                {b}
              </button>
            ))}
          </div>
        </div>
        <Notice tone="info">Outbound drafts are always gated. Approving one in Decisions records the approval — v1 still sends nothing.</Notice>
        {error ? <Notice tone="error">{error}</Notice> : null}
      </form>
    </Sheet>
  );
}

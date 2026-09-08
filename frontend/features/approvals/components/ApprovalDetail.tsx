"use client";

import { cx, formatDateTime, titleCase } from "@/shared/lib/format";
import { Button } from "@/shared/ui/Button";
import { AlertIcon, CheckIcon, CrossIcon } from "@/shared/ui/icons";
import { CategoryTag, StatusPill, categoryStyle } from "@/shared/ui/Tag";
import { ArgumentTable } from "./ArgumentTable";
import type { Approval } from "../types";

const riskCopy: Record<string, string> = {
  money: "This action moves funds. Confirm the beneficiary, amount and mandate reference before approving.",
  legal: "This action executes or files a legal document in the firm's name. Check the counterparty and terms.",
  outbound: "This action sends a message outside the firm. Check the recipients and wording — it cannot be recalled.",
  internal_write: "This action writes to an internal system of record.",
  internal_read: "This action only reads internal data.",
  unknown: "This action could not be classified. Review it carefully before approving.",
};

export function ApprovalDetail({
  approval,
  onDecide,
  busy,
  error,
  readOnly,
}: {
  approval: Approval;
  onDecide: (decision: "approve" | "reject") => void;
  busy: boolean;
  error: string | null;
  readOnly?: boolean;
}) {
  const style = categoryStyle(approval.category);
  const pending = approval.status === "pending";

  return (
    <div className="yuki-fade flex min-h-full flex-col">
      <div className="border-b border-line px-7 pb-5 pt-6">
        <div className="flex flex-wrap items-center gap-2">
          <CategoryTag category={approval.category} />
          <StatusPill status={approval.status} />
          <span className="text-[11px] text-muted">Approval #{approval.id}</span>
        </div>

        <h1 className="mt-3 text-[19px] font-semibold leading-snug text-ink">
          {approval.proposed_action.summary}
        </h1>

        <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 text-[12px] text-muted">
          <span>
            Tool{" "}
            <code className="rounded bg-line-soft px-1.5 py-0.5 font-mono text-[11px] text-[#5c6675]">
              {approval.proposed_action.tool}
            </code>
          </span>
          <span>Segment {approval.segment_id}</span>
          {approval.job_id ? <span>Job #{approval.job_id}</span> : null}
          {approval.requested_by ? <span>Raised by {approval.requested_by}</span> : null}
          {approval.created_at ? <span>{formatDateTime(approval.created_at)}</span> : null}
        </div>
      </div>

      <div className="flex-1 px-7 py-6">
        <div
          className={cx(
            "mb-6 flex items-start gap-2.5 rounded-lg px-3.5 py-3 text-[12.5px] leading-relaxed",
            style.tag,
          )}
        >
          <AlertIcon className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{riskCopy[String(approval.category)] ?? riskCopy.unknown}</span>
        </div>

        <h2 className="mb-1 text-[11px] font-semibold uppercase tracking-[0.1em] text-muted">
          Proposed action
        </h2>
        <p className="mb-4 text-[13px] text-muted">
          Exactly what the agent will execute if you approve. Nothing has run yet.
        </p>

        <div className="rounded-xl border border-line bg-white px-4 py-1.5">
          <ArgumentTable args={approval.proposed_action.arguments} />
        </div>
      </div>

      <div className="sticky bottom-0 border-t border-line bg-surface/95 px-7 py-4 backdrop-blur">
        {error ? (
          <p className="mb-3 text-[12px] text-cat-outbound-fg">{error}</p>
        ) : null}

        {pending ? (
          <div className="flex items-center gap-3">
            <Button variant="approve" loading={busy} onClick={() => onDecide("approve")}>
              <CheckIcon className="h-4 w-4" /> Approve
            </Button>
            <Button variant="reject" disabled={busy} onClick={() => onDecide("reject")}>
              <CrossIcon className="h-4 w-4" /> Reject
            </Button>
            <p className="ml-auto text-[11.5px] text-muted">
              {readOnly
                ? "Offline preview — decisions are local only."
                : "Your decision is recorded against your username in the audit log."}
            </p>
          </div>
        ) : (
          <p className="text-[12.5px] text-muted">
            This request was <strong className="text-ink">{titleCase(String(approval.status))}</strong>. No
            further action is needed.
          </p>
        )}
      </div>
    </div>
  );
}

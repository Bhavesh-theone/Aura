"use client";

import { AlertTriangle, ArrowRight, CheckCircle2, CircleSlash, CornerUpLeft, Lock, ShieldAlert, TriangleAlert, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { ApiError } from "@/shared/api/client";
import { cx, humanize, stageLabel } from "@/shared/lib/format";
import { useAuth } from "@/features/auth/hooks";
import { can, roleLabel } from "@/features/auth/roles";
import { errMessage } from "@/shared/lib/useApi";
import { Badge, Button, inputCls, labelCls, textareaCls, type Tone } from "@/shared/ui/primitives";
import { Sheet } from "@/shared/ui/Sheet";
import { Notice, Skel } from "@/shared/ui/States";
import { useToast } from "@/shared/ui/toast";
import { getGuards, transition } from "../api";
import { isRegression, isTerminal, overridableBy, type DealDetail, type GuardResult } from "../types";

const guardFailed = (g: GuardResult) => g.result !== true && !g.overridden_by;
/** X11: only a failing *blocking* guard stops the move; warnings are advisory. */
const isBlocking = (g: GuardResult) => guardFailed(g) && g.severity === "blocking";
const isWarning = (g: GuardResult) => guardFailed(g) && g.severity === "warning";
const isForward = (from: string, to: string) => !isTerminal(to) && !isRegression(from, to);

/** Why compliance may (null) or may not (reason) make this move — it acts only as an override. */
function complianceBar(from: string, to: string, preview: GuardResult[] | undefined): string | null {
  if (!isForward(from, to)) return "Only dealmakers can move a deal back or end it.";
  if (!preview) return "Checking…";
  const blocking = preview.filter(isBlocking);
  if (blocking.length === 0) return "Every blocking check passes — a dealmaker makes this move.";
  const foreign = blocking.filter((g) => g.override_role !== "compliance");
  if (foreign.length)
    return `${foreign.length === 1 ? "A failing check" : `${foreign.length} failing checks`} can’t be overridden by compliance.`;
  return null;
}

const sevTone = (s: string): Tone => (s === "blocking" ? "danger" : s === "warning" ? "warning" : "neutral");

/** "T2_engagement_letter" → "Engagement letter" when the guard has an empty description. */
function guardTitle(g: GuardResult) {
  if (g.description) return g.description;
  return humanize(g.guard_name.replace(/^T\d+[_-]?/i, ""));
}

function GuardRow({ g, myRole }: { g: GuardResult; myRole?: string }) {
  const bad = isBlocking(g);
  const warn = isWarning(g);
  const overridden = g.result !== true && !!g.overridden_by;
  return (
    <li className="flex gap-3 px-3.5 py-3">
      <span className="mt-px shrink-0" aria-label={bad ? "Failed" : warn ? "Warning" : overridden ? "Overridden" : "Passed"}>
        {bad ? (
          <XCircle className="h-4 w-4 text-danger" />
        ) : warn ? (
          <TriangleAlert className="h-4 w-4 text-warning" />
        ) : overridden ? (
          <ShieldAlert className="h-4 w-4 text-warning" />
        ) : (
          <CheckCircle2 className="h-4 w-4 text-success" />
        )}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-start gap-2">
          <span className={cx("flex-1 text-[13px] leading-snug", bad ? "font-medium text-fg" : "text-fg")}>{guardTitle(g)}</span>
          <Badge tone={bad || warn ? sevTone(g.severity) : "neutral"} className="capitalize">
            {g.severity === "warning" ? "Advisory" : g.severity}
          </Badge>
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-x-2 text-[11px] text-muted">
          <span className="font-mono">{g.guard_name}</span>
          {overridden ? <span className="text-warning">· overridden by {g.overridden_by}</span> : null}
          {bad ? <span>· not met</span> : null}
          {warn ? <span>· not met, won’t block</span> : null}
          {bad && g.override_role ? (
            <span className={cx(g.override_role === myRole ? "text-fg-2" : "")}>
              · override: {roleLabel(g.override_role).toLowerCase()}
              {g.override_role === myRole ? " (you)" : ""}
            </span>
          ) : null}
          {bad && !g.override_role ? <span>· no override</span> : null}
        </div>
      </div>
    </li>
  );
}

function ChecklistSkeleton() {
  return (
    <div className="divide-y divide-line-subtle rounded-md border border-line" aria-busy="true" aria-label="Running checks">
      {[0, 1, 2].map((i) => (
        <div key={i} className="flex gap-3 px-3.5 py-3">
          <Skel className="h-4 w-4 rounded-full" />
          <div className="flex-1 space-y-2">
            <Skel className="h-3" style={{ width: `${70 - i * 12}%` }} />
            <Skel className="h-2.5 w-28" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function AdvanceSheet({
  deal,
  open,
  onClose,
  onDone,
}: {
  deal: DealDetail;
  open: boolean;
  onClose: () => void;
  onDone: () => void;
}) {
  const toast = useToast();
  const { user } = useAuth();
  const myRole = user?.role;
  // Compliance may only make a move as an override of compliance-owned guards.
  const overrideOnly = !can(user, "transition") && can(user, "overrideTransition");
  const [previews, setPreviews] = useState<Record<string, GuardResult[]>>({});
  const [target, setTarget] = useState("");
  const [guards, setGuards] = useState<GuardResult[] | null>(null);
  const [guardNote, setGuardNote] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [overriding, setOverriding] = useState(false);
  const [override, setOverride] = useState("");
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<GuardResult[] | null>(null);

  const terminal = target !== "" && isTerminal(target);
  const regression = target !== "" && isRegression(deal.stage, target);
  const needsReason = terminal || regression;
  const shown = conflict && conflict.length ? conflict : guards;
  const blockingFails = (shown ?? []).filter(isBlocking);
  const warnings = (shown ?? []).filter(isWarning);
  const failing = blockingFails.length > 0;
  const passing = (shown ?? []).filter((g) => !guardFailed(g)).length;
  // Override is offered only when *every* blocking failure names this user's role.
  const canOverride = failing && blockingFails.every((g) => overridableBy(g, myRole));
  const overrideRoles = [...new Set(blockingFails.map((g) => g.override_role).filter(Boolean) as string[])];

  // Compliance: preview every forward move to know which ones it may override.
  useEffect(() => {
    if (!open || !overrideOnly) {
      setPreviews({});
      return;
    }
    let cancelled = false;
    const forward = deal.allowed_next.filter((s) => isForward(deal.stage, s));
    Promise.all(
      forward.map((s) =>
        getGuards(deal.id, s)
          .then((g) => [s, g] as const)
          .catch(() => [s, [] as GuardResult[]] as const),
      ),
    ).then((pairs) => {
      if (!cancelled) setPreviews(Object.fromEntries(pairs));
    });
    return () => {
      cancelled = true;
    };
  }, [open, overrideOnly, deal.id, deal.stage, deal.allowed_next]);

  // Pre-select the natural forward move when the sheet opens (compliance: the first it may override).
  useEffect(() => {
    if (!open) {
      setTarget("");
      return;
    }
    if (overrideOnly) {
      setTarget(deal.allowed_next.find((s) => complianceBar(deal.stage, s, previews[s]) === null) ?? "");
      return;
    }
    const forward = deal.allowed_next.find((s) => isForward(deal.stage, s));
    setTarget(forward ?? "");
  }, [open, overrideOnly, previews, deal.allowed_next, deal.stage]);

  useEffect(() => {
    setGuards(null);
    setGuardNote(null);
    setConflict(null);
    setError(null);
    setOverriding(overrideOnly);
    setOverride("");
    setAck(false);
    if (!target) return;
    let cancelled = false;
    getGuards(deal.id, target)
      .then((g) => !cancelled && setGuards(g))
      .catch((err) => {
        if (cancelled) return;
        setGuardNote(errMessage(err));
      });
    return () => {
      cancelled = true;
    };
  }, [target, deal.id, overrideOnly]);

  // Why the primary action is disabled — shown as plain text beside the button.
  let blocker: string | null = null;
  if (!target)
    blocker = overrideOnly
      ? Object.keys(previews).length || !deal.allowed_next.some((s) => isForward(deal.stage, s))
        ? "No move here has a failing compliance guard to override."
        : "Checking which moves you can override…"
      : "Choose where the deal goes next.";
  else if (!shown && !guardNote) blocker = "Running checks…";
  else if (overrideOnly && !failing) blocker = "Nothing to override — a dealmaker makes this move.";
  else if (needsReason && !reason.trim()) blocker = regression ? "Add a reason code to move backwards." : "Add a reason code to end the deal.";
  else if (failing && !canOverride) blocker = `Blocked: ${blockingFails.length} check${blockingFails.length === 1 ? "" : "s"} not met.`;
  else if (failing && !overriding) blocker = `${blockingFails.length} blocking check${blockingFails.length === 1 ? "" : "s"} not met.`;
  else if (failing && !override.trim()) blocker = "Write a justification for the override.";
  else if (terminal && !ack) blocker = "Confirm that ending the deal is final.";

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await transition(deal.id, {
        to_stage: target,
        ...(needsReason ? { reason_code: reason.trim() } : {}),
        ...(failing && canOverride && overriding ? { override_justification: override.trim() } : {}),
      });
      toast(`${deal.name} moved to ${stageLabel(target)}${failing && overriding ? " by override" : ""}`);
      setReason("");
      onClose();
      onDone();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        const body = err.detail as { evaluations?: GuardResult[] } | null;
        setConflict(body?.evaluations ?? []);
      }
      // 403 bodies read "The <role> role cannot …" — shown verbatim.
      setError(errMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const label = overrideOnly
    ? `Override and move${target ? ` to ${stageLabel(target)}` : ""}`
    : failing && overriding ? "Override and advance" : terminal ? `End deal as ${stageLabel(target)}` : target ? `Move to ${stageLabel(target)}` : "Advance";

  return (
    <Sheet
      open={open}
      onClose={onClose}
      eyebrow={<span className="font-mono">{deal.external_id}</span>}
      title={overrideOnly ? "Compliance override" : "Advance stage"}
      description={
        overrideOnly ? (
          <>
            Currently at <span className="font-medium text-fg-2">{stageLabel(deal.stage)}</span>. Compliance can move a deal only by
            overriding failing checks that name compliance as their override role. The justification is kept with the audit chain.
          </>
        ) : (
          <>
            Currently at <span className="font-medium text-fg-2">{stageLabel(deal.stage)}</span>. Every move is checked against the
            stage guards and written to the audit chain.
          </>
        )
      }
      footer={
        <div className="flex items-center gap-3">
          <p className={cx("min-w-0 flex-1 text-[12px]", blocker ? "text-muted" : "text-success")}>
            {blocker ??
              (shown && shown.length
                ? warnings.length
                  ? `Blocking checks pass · ${warnings.length} advisory warning${warnings.length === 1 ? "" : "s"}.`
                  : `All ${shown.length} checks pass.`
                : "Ready.")}
          </p>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant={terminal ? "danger" : "primary"} onClick={submit} loading={busy} disabled={blocker !== null}>
            {label}
            {!terminal && !busy ? <ArrowRight className="h-3.5 w-3.5" /> : null}
          </Button>
        </div>
      }
    >
      {deal.allowed_next.length === 0 ? (
        <div className="py-10 text-center">
          <p className="font-serif text-[16px] text-fg">No further moves</p>
          <p className="mt-1 text-[13px] text-muted">This stage has no allowed next stages.</p>
        </div>
      ) : (
        <div className="space-y-6">
          <fieldset>
            <legend className={labelCls}>Move to</legend>
            <div role="radiogroup" className="space-y-1.5">
              {deal.allowed_next.map((s) => {
                const sel = target === s;
                const kind = isTerminal(s) ? "end" : isRegression(deal.stage, s) ? "back" : "forward";
                const barred = overrideOnly ? complianceBar(deal.stage, s, previews[s]) : null;
                return (
                  <label
                    key={s}
                    title={barred ?? undefined}
                    className={cx(
                      "flex h-10 items-center gap-3 rounded-sm border px-3 transition-colors duration-[var(--dur-1)] focus-within:ring-2 focus-within:ring-accent/40",
                      barred ? "cursor-not-allowed border-line opacity-60" : "cursor-pointer",
                      sel ? (kind === "end" ? "border-danger-border bg-danger-soft" : "border-accent bg-accent-soft") : !barred && "border-line hover:bg-control-hover",
                    )}
                  >
                    <input type="radio" name="adv-target" className="sr-only" checked={sel} disabled={!!barred} onChange={() => setTarget(s)} />
                    <span
                      className={cx(
                        "flex h-3.5 w-3.5 items-center justify-center rounded-full border",
                        sel ? (kind === "end" ? "border-danger" : "border-accent") : "border-line-strong",
                      )}
                    >
                      {sel ? <span className={cx("h-1.5 w-1.5 rounded-full", kind === "end" ? "bg-danger" : "bg-accent")} /> : null}
                    </span>
                    <span className="flex-1 text-[13px] font-medium text-fg">{stageLabel(s)}</span>
                    {barred ? (
                      <span className="inline-flex min-w-0 items-center gap-1 truncate text-[12px] text-muted">
                        <Lock className="h-3 w-3 shrink-0" /> {barred}
                      </span>
                    ) : overrideOnly ? (
                      <span className="inline-flex items-center gap-1 text-[12px] text-warning">
                        <ShieldAlert className="h-3 w-3" /> Override available
                      </span>
                    ) : kind === "back" ? (
                      <span className="inline-flex items-center gap-1 text-[12px] text-warning">
                        <CornerUpLeft className="h-3 w-3" /> Moves back
                      </span>
                    ) : kind === "end" ? (
                      <span className="inline-flex items-center gap-1 text-[12px] text-danger">
                        <CircleSlash className="h-3 w-3" /> Ends the deal
                      </span>
                    ) : (
                      <span className="text-[12px] text-muted">Next stage</span>
                    )}
                  </label>
                );
              })}
            </div>
          </fieldset>

          {target ? (
            <section>
              <div className="mb-2 flex items-baseline justify-between">
                <span className={labelCls + " mb-0"}>Guard checklist</span>
                {shown && shown.length ? (
                  <span className={cx("num text-[12px]", failing ? "text-danger" : warnings.length ? "text-warning" : "text-success")}>
                    {passing} of {shown.length} met
                  </span>
                ) : null}
              </div>
              {guardNote ? (
                <Notice tone="info">{guardNote}</Notice>
              ) : shown ? (
                shown.length === 0 ? (
                  <div className="rounded-md border border-dashed border-line px-4 py-5 text-center text-[13px] text-muted">
                    No guards apply to this move.
                  </div>
                ) : (
                  <ul className="divide-y divide-line-subtle overflow-hidden rounded-md border border-line bg-surface">
                    {shown.map((g, i) => (
                      <GuardRow key={`${g.guard_name}-${i}`} g={g} myRole={myRole} />
                    ))}
                  </ul>
                )
              ) : (
                <ChecklistSkeleton />
              )}
            </section>
          ) : null}

          {needsReason ? (
            <div>
              <label htmlFor="adv-reason" className={labelCls}>Reason code</label>
              <input id="adv-reason" value={reason} onChange={(e) => setReason(e.target.value)} className={cx(inputCls, "font-mono")} placeholder="client_request" />
              <p className="mt-1.5 text-[12px] text-muted">
                {regression ? "Moving backwards is recorded in the deal history as a regression." : "Ending a deal is final and recorded in the audit chain."}
              </p>
            </div>
          ) : null}

          {terminal ? (
            <label className="flex items-start gap-2.5 text-[13px] text-fg-2">
              <input type="checkbox" className="mt-[3px]" checked={ack} onChange={(e) => setAck(e.target.checked)} />
              I understand this ends the deal and can’t be undone.
            </label>
          ) : null}

          {failing && canOverride ? (
            <div className="rounded-md border border-warning-border bg-warning-soft p-3.5">
              <div className="flex items-center gap-2 text-[13px] font-medium text-warning">
                <AlertTriangle className="h-3.5 w-3.5" /> Exceptional override
              </div>
              <p className="mt-1 text-[12px] leading-relaxed text-fg-2">
                Each failing blocking check names {roleLabel(myRole).toLowerCase()} as its override role. Your justification is stored with the guard evaluation permanently{overrideOnly ? "." : " and shown to compliance."}
              </p>
              {overrideOnly ? (
                <p className="mt-3 text-[13px] text-fg">
                  Override {blockingFails.length === 1 ? "the failing check" : `all ${blockingFails.length} failing checks`}
                </p>
              ) : (
                <label className="mt-3 flex items-center gap-2 text-[13px] text-fg">
                  <input type="checkbox" checked={overriding} onChange={(e) => setOverriding(e.target.checked)} />
                  Override {blockingFails.length === 1 ? "the failing check" : `all ${blockingFails.length} failing checks`}
                </label>
              )}
              {overriding ? (
                <textarea
                  aria-label="Override justification"
                  value={override}
                  onChange={(e) => setOverride(e.target.value)}
                  rows={3}
                  className={cx(textareaCls, "mt-2.5")}
                  placeholder="Why is it safe to proceed despite the failing checks?"
                />
              ) : null}
            </div>
          ) : null}

          {failing && !canOverride ? (
            <div className="rounded-md border border-line bg-well p-3.5">
              <div className="flex items-center gap-2 text-[13px] font-medium text-fg">
                <Lock className="h-3.5 w-3.5 text-muted" /> Blocked until the checks pass
              </div>
              <p className="mt-1 text-[12px] leading-relaxed text-fg-2">
                {overrideRoles.length
                  ? <>Only {overrideRoles.map((r) => roleLabel(r).toLowerCase()).join(" or ")} can override {blockingFails.length === 1 ? "this guard" : "these guards"}. Fix the underlying items, or ask them to make the move.</>
                  : "These guards have no override. Fix the underlying items to move the deal."}
              </p>
            </div>
          ) : null}

          {error ? <Notice tone="error" title={conflict ? "The server blocked this move" : "Couldn’t move the deal"}>{error}</Notice> : null}
        </div>
      )}
    </Sheet>
  );
}

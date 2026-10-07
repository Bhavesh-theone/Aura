"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { ArrowUp, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { useAuth } from "@/features/auth/hooks";
import { cx, timeAgo } from "@/shared/lib/format";
import { errMessage } from "@/shared/lib/useApi";
import { Button, Card } from "@/shared/ui/primitives";
import { EmptyState, InlineError, SkeletonRows } from "@/shared/ui/States";
import { useToast } from "@/shared/ui/toast";
import { promote } from "../api";
import { useAutonomy } from "../hooks";
import type { Autonomy } from "../types";
import { capLabel } from "./shared";

const LEVELS = [
  { name: "Off", text: "Switched off. New jobs for this capability are refused." },
  { name: "Supervised", text: "Every result goes to a person for a decision." },
  {
    name: "Autonomous",
    text: "A confident result may complete without a person (today: an extraction at 0.95 or above). Classifications and drafts still go to a person.",
  },
] as const;

/** Three steps; level 0 lights none, 1 lights one, 2 lights two... shown as a 3-step track. */
function Meter({ level }: { level: number }) {
  return (
    <div className="flex items-center gap-1" role="img" aria-label={`Level ${level} of 2: ${LEVELS[level]?.name}`}>
      {[0, 1, 2].map((i) => (
        <span key={i} className={cx("h-1.5 w-7 rounded-full", i === level ? (level === 0 ? "bg-muted" : "bg-accent") : i < level ? "bg-accent/45" : "bg-well")} />
      ))}
    </div>
  );
}

function PromoteButton({ a, onDone }: { a: Autonomy; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const toast = useToast();
  const next = Math.min(2, a.level + 1);
  const run = async () => {
    setBusy(true);
    setErr(null);
    try {
      await promote(a.capability);
      toast(`${capLabel(a.capability)} promoted to ${LEVELS[next].name}.`, "success");
      setOpen(false);
      onDone();
    } catch (e) {
      setErr(errMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog.Root
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (!o) setErr(null);
      }}
    >
      <Dialog.Trigger asChild>
        <Button size="sm" variant="secondary" disabled={a.level >= 2} title={a.level >= 2 ? "Already at the highest level" : undefined}>
          <ArrowUp className="h-3.5 w-3.5" /> Promote
        </Button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="a-scrim fixed inset-0 z-50 bg-[var(--scrim)]" />
        <Dialog.Content className="a-pop fixed left-1/2 top-[22vh] z-50 w-[min(440px,calc(100vw-32px))] -translate-x-1/2 rounded-lg bg-raised p-5 shadow-overlay outline-none">
          <Dialog.Title className="font-serif text-[18px] text-fg">Promote {capLabel(a.capability)}?</Dialog.Title>
          <Dialog.Description className="mt-1.5 text-[13px] leading-relaxed text-muted">
            Moves it from <b className="text-fg-2">{LEVELS[a.level].name}</b> to <b className="text-fg-2">{LEVELS[next].name}</b>. {LEVELS[next].text} Promotion needs a
            passing eval run on the real model from the last 7 days.
          </Dialog.Description>
          {err ? (
            <div role="alert" className="mt-3 rounded-sm border border-danger-border bg-danger-soft px-3 py-2 text-[12.5px] text-danger">
              {err}
            </div>
          ) : null}
          <div className="mt-5 flex justify-end gap-2">
            <Dialog.Close asChild>
              <Button variant="ghost" size="sm">Cancel</Button>
            </Dialog.Close>
            <Button size="sm" loading={busy} onClick={run}>Promote</Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function AutonomySection() {
  const { data, loading, error, refresh } = useAutonomy();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  return (
    <section aria-labelledby="q-autonomy">
      <h2 id="q-autonomy" className="font-serif text-[18px] text-fg">Autonomy per capability</h2>
      <p className="mb-3 mt-0.5 text-[13px] text-muted">
        How much each agent capability may do without a person. A capability is demoted automatically when people keep overriding it.
      </p>
      {error ? (
        <InlineError message={error} onRetry={refresh} />
      ) : loading ? (
        <Card><SkeletonRows rows={3} height={64} /></Card>
      ) : data.length === 0 ? (
        <EmptyState compact title="No capabilities configured" />
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {data.map((a) => (
            <Card key={a.capability} className="flex flex-col gap-3 p-4">
              <div className="flex items-start gap-2">
                <div className="min-w-0">
                  <p className="text-[14px] font-medium text-fg">{capLabel(a.capability)}</p>
                  <p className="font-mono text-[11px] text-muted">{a.capability}</p>
                </div>
                {isAdmin ? <div className="ml-auto"><PromoteButton a={a} onDone={refresh} /></div> : null}
              </div>
              <div className="flex items-center gap-3">
                <Meter level={a.level} />
                <span className="text-[13px] font-medium text-fg">{LEVELS[a.level]?.name}</span>
                <span className="num ml-auto text-[11px] text-muted">level {a.level}</span>
              </div>
              <p className="text-[12.5px] leading-relaxed text-muted">{LEVELS[a.level]?.text}</p>
              {a.demoted_at || a.reason ? (
                <div className="flex gap-2 rounded-sm border border-warning-border bg-warning-soft px-2.5 py-2 text-[12px] text-warning">
                  <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  <div>
                    {a.reason ? <p>{a.reason}</p> : null}
                    {a.demoted_at ? <p className="opacity-80">Demoted {timeAgo(a.demoted_at)}</p> : null}
                  </div>
                </div>
              ) : null}
              <dl className="mt-auto space-y-1 border-t border-line-subtle pt-2.5 text-[12px]">
                {a.pinned_model ? (
                  <div className="flex gap-2">
                    <dt className="text-muted">Pinned model</dt>
                    <dd className="ml-auto truncate text-right text-fg-2">
                      <span className="font-mono">{a.pinned_model}</span> <span className="text-muted">(stored, not yet used)</span>
                    </dd>
                  </div>
                ) : null}
                <div className="flex gap-2">
                  <dt className="text-muted">Updated</dt>
                  <dd className="ml-auto text-fg-2">
                    {a.updated_by ?? "system"}
                    {a.updated_at ? ` · ${timeAgo(a.updated_at)}` : ""}
                  </dd>
                </div>
              </dl>
            </Card>
          ))}
        </div>
      )}
    </section>
  );
}

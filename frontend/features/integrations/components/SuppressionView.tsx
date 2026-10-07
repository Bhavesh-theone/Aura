"use client";

import { Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { useAuth } from "@/features/auth/hooks";
import { WHO_CAN, can, roleLabel } from "@/features/auth/roles";
import { anyEvent } from "@/shared/api/events";
import { formatDateTime, titleCase } from "@/shared/lib/format";
import { errMessage, useApi } from "@/shared/lib/useApi";
import { PageHeader } from "@/shared/ui/PageHeader";
import { Badge, Button, Card, IconButton, inputCls, labelCls, selectCls } from "@/shared/ui/primitives";
import { EmptyState, InlineError, Notice, SkeletonRows, Unavailable } from "@/shared/ui/States";
import { useToast } from "@/shared/ui/toast";
import { addSuppression, listSuppression, removeSuppression, type Suppression, type SuppressionKind } from "../api";

export function SuppressionView() {
  const { user } = useAuth();
  const toast = useToast();
  const allowed = can(user, "manageSuppression");
  const list = useApi<Suppression[]>(allowed ? listSuppression : null, [], [allowed], { live: anyEvent, pollMs: 60000 });
  const [kind, setKind] = useState<SuppressionKind>("email");
  const [value, setValue] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [removing, setRemoving] = useState<number | null>(null);

  if (!allowed) {
    return (
      <EmptyState
        title="Dealmakers and compliance only"
        description={`${WHO_CAN.manageSuppression} You’re signed in as ${roleLabel(user?.role).toLowerCase() || "a member"}.`}
        action={<Link href="/"><Button variant="secondary">Back to the dashboard</Button></Link>}
      />
    );
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await addSuppression({ kind, value: value.trim(), reason: reason.trim() });
      toast(`${value.trim()} suppressed`);
      setValue("");
      setReason("");
      list.refresh();
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove(s: Suppression) {
    setRemoving(s.id);
    try {
      await removeSuppression(s.id);
      toast(`${s.value} removed from the suppression list`);
      list.refresh();
    } catch (err) {
      toast(errMessage(err), "error");
    } finally {
      setRemoving(null);
    }
  }

  return (
    <div className="flex-1 pb-14">
      <PageHeader
        title="Suppression list"
        description="Emails and whole domains Aura must never write to. Checked again at send time, so adding one blocks even an already-approved draft."
        meta={list.data.length ? `${list.data.length} entr${list.data.length === 1 ? "y" : "ies"}` : undefined}
      />
      <div className="space-y-5 px-8">
        <form onSubmit={submit} className="rounded-md border border-line bg-surface p-4 shadow-card">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-[120px_1fr_1.4fr_auto] md:items-end">
            <div>
              <label htmlFor="sp-kind" className={labelCls}>Kind</label>
              <select id="sp-kind" value={kind} onChange={(e) => setKind(e.target.value as SuppressionKind)} className={selectCls}>
                <option value="email">Email</option>
                <option value="domain">Domain</option>
              </select>
            </div>
            <div>
              <label htmlFor="sp-value" className={labelCls}>{kind === "email" ? "Email address" : "Domain"}</label>
              <input id="sp-value" required value={value} onChange={(e) => setValue(e.target.value)} className={inputCls} placeholder={kind === "email" ? "someone@example.com" : "example.com"} />
            </div>
            <div>
              <label htmlFor="sp-reason" className={labelCls}>Reason</label>
              <input id="sp-reason" required value={reason} onChange={(e) => setReason(e.target.value)} className={inputCls} placeholder="Asked not to be contacted" />
            </div>
            <Button type="submit" loading={busy} disabled={!value.trim() || !reason.trim()}><Plus className="h-3.5 w-3.5" /> Add</Button>
          </div>
          {error ? <Notice tone="error" className="mt-3">{error}</Notice> : null}
        </form>

        {list.unavailable ? (
          <Unavailable what="The suppression list" />
        ) : list.error ? (
          <InlineError message={list.error} onRetry={list.refresh} />
        ) : (
          <Card className="overflow-hidden">
            {list.loading ? (
              <SkeletonRows rows={4} height={44} />
            ) : list.data.length === 0 ? (
              <EmptyState compact title="Nothing suppressed" description="Add an email or domain above to stop any outbound message to it." />
            ) : (
              <table className="w-full border-collapse text-left">
                <thead>
                  <tr className="h-9 border-b border-line text-[12px] text-muted">
                    <th className="w-24 px-4 font-medium">Kind</th>
                    <th className="px-2 font-medium">Value</th>
                    <th className="px-2 font-medium">Reason</th>
                    <th className="w-32 px-2 font-medium">Added by</th>
                    <th className="w-44 px-2 font-medium">When</th>
                    <th className="w-12 px-4"><span className="sr-only">Remove</span></th>
                  </tr>
                </thead>
                <tbody>
                  {list.data.map((s) => (
                    <tr key={s.id} className="h-11 border-b border-line-subtle text-[13px] last:border-0">
                      <td className="px-4"><Badge tone={s.kind === "domain" ? "info" : "neutral"}>{s.kind === "domain" ? "Domain" : "Email"}</Badge></td>
                      <td className="px-2 font-mono text-[12px] text-fg">{s.value}</td>
                      <td className="px-2 text-fg-2">{s.reason}</td>
                      <td className="px-2 text-fg-2">{titleCase(s.created_by)}</td>
                      <td className="num px-2 font-mono text-[12px] text-muted">{formatDateTime(s.created_at)}</td>
                      <td className="px-4 text-right">
                        <IconButton label={`Remove ${s.value}`} disabled={removing === s.id} onClick={() => remove(s)}>
                          <Trash2 className="h-4 w-4" />
                        </IconButton>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        )}
      </div>
    </div>
  );
}

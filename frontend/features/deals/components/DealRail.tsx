"use client";

import { BadgeCheck, Plus, StickyNote, ShieldCheck, ShieldQuestion, UserMinus, Users, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { useAuth } from "@/features/auth/hooks";
import { WHO_CAN } from "@/features/auth/roles";
import { useCan } from "@/features/auth/useCan";
import { dealEvents } from "@/shared/api/events";
import { cx, formatDateTime, shortAgo, shortDate, titleCase } from "@/shared/lib/format";
import { errMessage, useApi } from "@/shared/lib/useApi";
import { Avatar, Badge, Button, Card, IconButton, Tip, inputCls, textareaCls } from "@/shared/ui/primitives";
import { Permit } from "@/shared/ui/Permit";
import { InlineError, Notice, Skel } from "@/shared/ui/States";
import { useToast } from "@/shared/ui/toast";
import { addMember, listMembers, listNotes, listSignoffs, patchDeal, removeMember, signOff } from "../api";
import type { DealDetail, DealNote, Member, Signoff } from "../types";

function RailCard({ title, icon, aside, children }: { title: string; icon: React.ReactNode; aside?: React.ReactNode; children: React.ReactNode }) {
  return (
    <Card>
      <div className="flex h-10 items-center gap-2 border-b border-line-subtle px-4">
        <span className="text-muted">{icon}</span>
        <h3 className="text-[13px] font-medium text-fg">{title}</h3>
        {aside ? <div className="ml-auto flex items-center gap-1.5">{aside}</div> : null}
      </div>
      {children}
    </Card>
  );
}

function RailSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-3 p-4" aria-busy="true">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-2.5">
          <Skel className="h-6 w-6 rounded-full" />
          <Skel className="h-3" style={{ width: `${55 - i * 10}%` }} />
        </div>
      ))}
    </div>
  );
}

/* ---------------------------------- Team ----------------------------------- */

export function TeamCard({ deal }: { deal: DealDetail }) {
  const toast = useToast();
  const allowed = useCan()("manageMembers");
  const { user } = useAuth();
  const members = useApi<Member[]>(() => listMembers(deal.id), [], [deal.id], { live: dealEvents(deal.id, ["deal"]) });
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    const u = name.trim().toLowerCase();
    if (!u) return;
    setBusy("+");
    setError(null);
    try {
      await addMember(deal.id, u);
      toast(`${titleCase(u)} added to the deal wall`);
      setName("");
      setAdding(false);
      members.refresh();
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setBusy(null);
    }
  }

  async function remove(u: string) {
    setBusy(u);
    setError(null);
    try {
      await removeMember(deal.id, u);
      toast(`${titleCase(u)} removed from the deal wall`);
      members.refresh();
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <RailCard
      title="Deal team"
      icon={<Users className="h-3.5 w-3.5" />}
      aside={
        <>
          {members.data.length ? <span className="num font-mono text-[11px] text-muted">{members.data.length}</span> : null}
          {!adding ? (
            <Permit allow={allowed} why={WHO_CAN.manageMembers}>
              <IconButton size="sm" label="Add someone to the wall" onClick={() => setAdding(true)}>
                <Plus className="h-3.5 w-3.5" />
              </IconButton>
            </Permit>
          ) : null}
        </>
      }
    >
      {members.loading ? (
        <RailSkeleton />
      ) : members.error && !members.data.length ? (
        <div className="p-3"><InlineError message={members.error} onRetry={members.refresh} /></div>
      ) : (
        <ul className="py-1">
          {members.data.map((m) => (
            <li key={m.username} className="group flex h-10 items-center gap-2.5 px-4">
              <Avatar name={m.username} size={22} />
              <div className="min-w-0 flex-1 leading-tight">
                <div className="truncate text-[13px] text-fg">
                  {titleCase(m.username)}
                  {m.username === deal.owner ? <span className="ml-1.5 text-[11px] text-muted">owner</span> : null}
                  {m.username === user?.username ? <span className="ml-1.5 text-[11px] text-muted">you</span> : null}
                </div>
                <div className="text-[11px] text-muted" title={formatDateTime(m.added_at)}>added {shortDate(m.added_at)}</div>
              </div>
              {allowed ? (
                <Tip label={`Remove ${titleCase(m.username)} from the wall`}>
                  <IconButton
                    size="sm"
                    label={`Remove ${m.username}`}
                    disabled={busy !== null}
                    onClick={() => remove(m.username)}
                    className="opacity-0 transition-opacity focus-visible:opacity-100 group-hover:opacity-100"
                  >
                    <UserMinus className="h-3.5 w-3.5" />
                  </IconButton>
                </Tip>
              ) : null}
            </li>
          ))}
          {members.data.length === 0 ? <li className="px-4 py-3 text-[12px] text-muted">Nobody is on this wall yet.</li> : null}
        </ul>
      )}
      {adding ? (
        <form onSubmit={add} className="flex gap-2 border-t border-line-subtle p-3">
          <input
            autoFocus
            aria-label="Username to add"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === "Escape" && setAdding(false)}
            className={cx(inputCls, "h-7 text-[12px]")}
            placeholder="username"
          />
          <Button size="sm" type="submit" loading={busy === "+"} disabled={!name.trim()}>Add</Button>
          <IconButton size="sm" type="button" label="Cancel" onClick={() => setAdding(false)}>
            <X className="h-3.5 w-3.5" />
          </IconButton>
        </form>
      ) : null}
      {error ? <div className="px-3 pb-3"><Notice tone="error">{error}</Notice></div> : null}
      <p className="border-t border-line-subtle px-4 py-2.5 text-[11px] leading-relaxed text-muted">
        Only people on the wall can see this deal, its documents and its agent runs.
      </p>
    </RailCard>
  );
}

/* -------------------------------- Compliance -------------------------------- */

const FLAG_SUGGESTIONS = ["CCI_COMBINATION", "SEBI_SAST", "SEBI_ICDR", "FEMA_FDI", "RBI_ECB", "NCLT_SCHEME", "IRDAI", "SECTORAL_CAP"];

export function ComplianceCard({ deal, onChanged }: { deal: DealDetail; onChanged: () => void }) {
  const toast = useToast();
  const allowed = useCan();
  const canFlags = allowed("editFlags");
  const canSign = allowed("signoff");
  const flags = deal.regulatory_flags;
  const signoffs = useApi<Signoff[]>(() => listSignoffs(deal.id), [], [deal.id], { live: dealEvents(deal.id, ["signoff", "deal"]) });
  const [flagText, setFlagText] = useState("");
  const [editing, setEditing] = useState(false);
  const [note, setNote] = useState("");
  const [signing, setSigning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const signed = signoffs.data.length > 0;

  async function saveFlags(next: string[]) {
    setBusy(true);
    setError(null);
    try {
      await patchDeal(deal.id, { regulatory_flags: next });
      onChanged();
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setBusy(false);
    }
  }

  function addFlag(raw: string) {
    const f = raw.trim().toUpperCase().replace(/\s+/g, "_");
    if (!f || flags.includes(f)) return setFlagText("");
    setFlagText("");
    void saveFlags([...flags, f]);
  }

  async function sign(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signOff(deal.id, note.trim());
      toast("Compliance sign-off recorded");
      setNote("");
      setSigning(false);
      signoffs.refresh();
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const status = flags.length === 0
    ? { tone: "neutral" as const, text: "Not required" }
    : signed
      ? { tone: "success" as const, text: "Signed off" }
      : { tone: "warning" as const, text: "Sign-off pending" };

  return (
    <RailCard
      title="Compliance"
      icon={<ShieldCheck className="h-3.5 w-3.5" />}
      aside={<Badge tone={status.tone}>{status.text}</Badge>}
    >
      <div className="px-4 pb-3 pt-3">
        <div className="mb-2 flex items-center">
          <span className="text-[11px] font-medium uppercase tracking-[0.06em] text-muted">Regulatory flags</span>
          {!editing ? (
            <span className="ml-auto">
            <Permit allow={canFlags} why={WHO_CAN.editFlags}>
              <button onClick={() => setEditing(true)} className="rounded-xs px-1 text-[12px] text-fg-2 outline-none hover:text-fg focus-visible:ring-2 focus-visible:ring-accent/50 disabled:pointer-events-none disabled:opacity-45">
                Edit
              </button>
            </Permit>
            </span>
          ) : null}
          {editing ? (
            <button onClick={() => setEditing(false)} className="ml-auto rounded-xs px-1 text-[12px] font-medium text-accent outline-none hover:text-accent-hover focus-visible:ring-2 focus-visible:ring-accent/50">
              Done
            </button>
          ) : null}
        </div>
        {(
          <>
            <div className="flex flex-wrap gap-1.5">
              {flags.map((f) => (
                <span key={f} className="inline-flex h-6 items-center gap-1 rounded-xs border border-warning-border bg-warning-soft pl-2 pr-1 font-mono text-[11px] text-warning">
                  {f}
                  {editing ? (
                    <button
                      aria-label={`Remove flag ${f}`}
                      disabled={busy}
                      onClick={() => void saveFlags(flags.filter((x) => x !== f))}
                      className="flex h-4 w-4 items-center justify-center rounded-xs hover:bg-warning/15 disabled:opacity-50"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  ) : null}
                </span>
              ))}
              {flags.length === 0 && !editing ? <span className="text-[12px] text-muted">None — no sign-off needed.</span> : null}
            </div>
            {editing ? (
              <div className="mt-2.5">
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    addFlag(flagText);
                  }}
                  className="flex gap-2"
                >
                  <input
                    autoFocus
                    aria-label="Add a regulatory flag"
                    value={flagText}
                    onChange={(e) => setFlagText(e.target.value)}
                    onKeyDown={(e) => e.key === "Escape" && setEditing(false)}
                    className={cx(inputCls, "h-7 font-mono text-[12px] uppercase")}
                    placeholder="FEMA_FDI"
                  />
                  <Button size="sm" type="submit" variant="secondary" loading={busy} disabled={!flagText.trim()}>Add</Button>
                </form>
                <div className="mt-2 flex flex-wrap gap-1">
                  {FLAG_SUGGESTIONS.filter((f) => !flags.includes(f)).slice(0, 6).map((f) => (
                    <button
                      key={f}
                      onClick={() => addFlag(f)}
                      disabled={busy}
                      className="inline-flex h-6 items-center gap-1 rounded-full border border-dashed border-line-strong px-2 font-mono text-[11px] text-fg-2 hover:border-accent hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50 disabled:opacity-50"
                    >
                      <Plus className="h-3 w-3" /> {f}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
          </>
        )}
      </div>

      <div className="border-t border-line-subtle px-4 pb-3 pt-3">
        <div className="mb-2 flex items-center">
          <span className="text-[11px] font-medium uppercase tracking-[0.06em] text-muted">Sign-offs</span>
          {!signing ? (
            <span className="ml-auto">
            <Permit allow={canSign} why={WHO_CAN.signoff}>
              <button onClick={() => setSigning(true)} className="rounded-xs px-1 text-[12px] text-fg-2 outline-none hover:text-fg focus-visible:ring-2 focus-visible:ring-accent/50 disabled:pointer-events-none disabled:opacity-45">
                Sign off
              </button>
            </Permit>
            </span>
          ) : null}
        </div>
        {signoffs.loading ? (
          <Skel className="h-8 w-full" />
        ) : signoffs.error ? (
          <InlineError message={signoffs.error} onRetry={signoffs.refresh} />
        ) : signoffs.data.length === 0 ? (
          <p className="flex items-start gap-1.5 text-[12px] text-muted">
            <ShieldQuestion className="mt-px h-3.5 w-3.5 shrink-0" />
            {flags.length ? "Flagged deals need a compliance sign-off before the deal can leave Diligence." : "Nothing signed yet."}
          </p>
        ) : (
          <ul className="space-y-2.5">
            {signoffs.data.map((s) => (
              <li key={s.id} className="flex gap-2">
                <BadgeCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" />
                <div className="min-w-0 text-[12px]">
                  <div className="text-fg">
                    {titleCase(s.signed_by)} <span className="num font-mono text-[11px] text-muted">· {formatDateTime(s.signed_at)}</span>
                  </div>
                  {s.note ? <p className="mt-0.5 leading-relaxed text-fg-2">{s.note}</p> : null}
                </div>
              </li>
            ))}
          </ul>
        )}
        {signing ? (
          <form onSubmit={sign} className="mt-3 space-y-2">
            <textarea
              autoFocus
              aria-label="Sign-off note"
              rows={3}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              className={cx(textareaCls, "text-[12px]")}
              placeholder={flags.length ? `What you checked for ${flags.join(", ")}` : "What you checked"}
            />
            <div className="flex justify-end gap-2">
              <Button size="sm" type="button" variant="ghost" onClick={() => setSigning(false)}>Cancel</Button>
              <Button size="sm" type="submit" variant="success" loading={busy} disabled={note.trim().length < 5}>Record sign-off</Button>
            </div>
          </form>
        ) : null}
      </div>
      {error ? <div className="px-3 pb-3"><Notice tone="error">{error}</Notice></div> : null}
    </RailCard>
  );
}

/* ---------------------------------- Notes ---------------------------------- */

export function NotesCard({ deal }: { deal: DealDetail }) {
  const notes = useApi<DealNote[]>(() => listNotes(deal.id), [], [deal.id], { live: dealEvents(deal.id, ["job", "deal"]) });
  return (
    <RailCard
      title="Notes"
      icon={<StickyNote className="h-3.5 w-3.5" />}
      aside={notes.data.length ? <span className="num font-mono text-[11px] text-muted">{notes.data.length}</span> : null}
    >
      {notes.loading ? (
        <RailSkeleton rows={2} />
      ) : notes.error && !notes.data.length ? (
        <div className="p-3"><InlineError message={notes.error} onRetry={notes.refresh} /></div>
      ) : notes.data.length === 0 ? (
        <p className="px-4 py-3 text-[12px] text-muted">No internal notes. Agents add notes with add_internal_note.</p>
      ) : (
        <ul className="divide-y divide-line-subtle">
          {notes.data.map((n) => (
            <li key={n.id} className="px-4 py-2.5">
              <p className="whitespace-pre-wrap break-words text-[12px] leading-relaxed text-fg">{n.body}</p>
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px] text-muted">
                <span>{titleCase(n.author)}</span>
                <Badge tone={n.source === "agent" ? "accent" : "neutral"}>{n.source}</Badge>
                {n.job_id ? <Link href="/jobs" className="font-mono hover:text-fg">JOB-{n.job_id}</Link> : null}
                <span className="ml-auto" title={formatDateTime(n.created_at)}>{shortAgo(n.created_at)}</span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </RailCard>
  );
}

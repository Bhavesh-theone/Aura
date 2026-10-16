"use client";

import { Eye, EyeOff, Search, ShieldCheck, UserPlus } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useAuth } from "@/features/auth/hooks";
import { ROLE_OPTIONS, WHO_CAN, can, roleLabel } from "@/features/auth/roles";
import { anyEvent } from "@/shared/api/events";
import { cx, titleCase } from "@/shared/lib/format";
import { errMessage, useApi } from "@/shared/lib/useApi";
import { PageHeader } from "@/shared/ui/PageHeader";
import { Avatar, Badge, Button, Segmented, Tip, inputCls, labelCls, selectCls } from "@/shared/ui/primitives";
import { Sheet } from "@/shared/ui/Sheet";
import { EmptyState, InlineError, Notice, SkeletonRows, Unavailable } from "@/shared/ui/States";
import { useToast } from "@/shared/ui/toast";
import { createUser, listUsers, updateUser, type AdminUser } from "../api";

const ROLE_HINT: Record<string, string> = {
  dealmaker: "Owns deals, moves stages, approves agent proposals.",
  analyst: "Uploads documents, works diligence, runs agent jobs.",
  compliance: "Manages deal walls and signs off flagged deals.",
  admin: "Manages users. Has no deal powers.",
};

function NewUserSheet({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: () => void }) {
  const toast = useToast();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [role, setRole] = useState("analyst");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setUsername("");
    setPassword("");
    setRole("analyst");
    setError(null);
  }, [open]);

  const uname = username.trim().toLowerCase();
  let blocker: string | null = null;
  if (!/^[a-z][a-z0-9._-]{1,31}$/.test(uname)) blocker = "Usernames are 2–32 characters: letters, digits, dot, dash, underscore.";
  else if (password.length < 8) blocker = `${8 - password.length} more character${8 - password.length === 1 ? "" : "s"} of password.`;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (blocker) return;
    setBusy(true);
    setError(null);
    try {
      await createUser({ username: uname, password, role });
      toast(`${titleCase(uname)} added as ${roleLabel(role).toLowerCase()}`);
      onCreated();
      onClose();
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
      title="New user"
      description="Share the password through a separate channel. They can’t see any deal until compliance adds them to its wall."
      footer={
        <div className="flex items-center gap-3">
          <p className={cx("min-w-0 flex-1 text-[12px]", blocker && (username || password) ? "text-muted" : "text-success")}>
            {blocker && (username || password) ? blocker : !blocker ? "Ready to create." : ""}
          </p>
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" form="new-user" loading={busy} disabled={blocker !== null}>Create user</Button>
        </div>
      }
    >
      <form id="new-user" onSubmit={submit} className="space-y-5">
        <div>
          <label htmlFor="nu-name" className={labelCls}>Username</label>
          <input id="nu-name" autoFocus autoComplete="off" value={username} onChange={(e) => setUsername(e.target.value)} className={cx(inputCls, "font-mono")} placeholder="priya" />
        </div>
        <div>
          <label htmlFor="nu-pass" className={labelCls}>Temporary password</label>
          <div className="relative">
            <input
              id="nu-pass"
              type={show ? "text" : "password"}
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={cx(inputCls, "pr-9")}
              placeholder="At least 8 characters"
            />
            <button
              type="button"
              onClick={() => setShow(!show)}
              aria-label={show ? "Hide password" : "Show password"}
              className="absolute right-1 top-1/2 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-xs text-muted hover:bg-control-hover hover:text-fg"
            >
              {show ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
            </button>
          </div>
        </div>
        <fieldset>
          <legend className={labelCls}>Role</legend>
          <div role="radiogroup" className="space-y-1.5">
            {ROLE_OPTIONS.map((r) => {
              const sel = role === r;
              return (
                <label
                  key={r}
                  className={cx(
                    "flex cursor-pointer items-start gap-3 rounded-sm border px-3 py-2.5 transition-colors focus-within:ring-2 focus-within:ring-accent/40",
                    sel ? "border-accent bg-accent-soft" : "border-line hover:bg-control-hover",
                  )}
                >
                  <input type="radio" name="nu-role" className="sr-only" checked={sel} onChange={() => setRole(r)} />
                  <span className={cx("mt-0.5 flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full border", sel ? "border-accent" : "border-line-strong")}>
                    {sel ? <span className="h-1.5 w-1.5 rounded-full bg-accent" /> : null}
                  </span>
                  <span>
                    <span className="block text-[13px] font-medium text-fg">{roleLabel(r)}</span>
                    <span className="block text-[12px] text-muted">{ROLE_HINT[r]}</span>
                  </span>
                </label>
              );
            })}
          </div>
        </fieldset>
        {error ? <Notice tone="error">{error}</Notice> : null}
      </form>
    </Sheet>
  );
}

function UserRow({ u, me, onChanged }: { u: AdminUser; me: boolean; onChanged: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!confirming) return;
    const t = setTimeout(() => setConfirming(false), 4000);
    return () => clearTimeout(t);
  }, [confirming]);

  async function patch(b: { role?: string; active?: boolean }, msg: string) {
    setBusy(true);
    setError(null);
    try {
      await updateUser(u.id, b);
      toast(msg);
      onChanged();
    } catch (err) {
      setError(errMessage(err));
      toast(errMessage(err), "error");
    } finally {
      setBusy(false);
      setConfirming(false);
    }
  }

  return (
    <tr className={cx("h-12 border-b border-line-subtle text-[13px] last:border-0", !u.active && "bg-well")}>
      <td className="px-4">
        <div className="flex items-center gap-2.5">
          <Avatar name={u.username} size={24} className={cx(!u.active && "opacity-50")} />
          <div className="min-w-0 leading-tight">
            <div className={cx("truncate font-medium", u.active ? "text-fg" : "text-muted")}>
              {titleCase(u.username)} {me ? <span className="ml-1 text-[11px] font-normal text-muted">you</span> : null}
            </div>
            <div className="font-mono text-[11px] text-muted">{u.username}</div>
          </div>
        </div>
        {error ? <p className="mt-1 text-[11px] text-danger">{error}</p> : null}
      </td>
      <td className="px-2">
        {me ? (
          <Tip label="You can’t change your own role — ask another admin.">
            <span tabIndex={0} className="outline-none"><Badge tone="accent"><ShieldCheck className="h-3 w-3" /> {roleLabel(u.role)}</Badge></span>
          </Tip>
        ) : (
          <select
            aria-label={`Role for ${u.username}`}
            value={u.role}
            disabled={busy || !u.active}
            onChange={(e) => patch({ role: e.target.value }, `${titleCase(u.username)} is now ${roleLabel(e.target.value).toLowerCase()}`)}
            className={cx(selectCls, "h-7 w-40 text-[12px] disabled:opacity-60")}
          >
            {ROLE_OPTIONS.map((r) => (
              <option key={r} value={r}>{roleLabel(r)}</option>
            ))}
            {!ROLE_OPTIONS.includes(u.role as never) ? <option value={u.role}>{roleLabel(u.role)}</option> : null}
          </select>
        )}
      </td>
      <td className="px-2">
        {u.active ? <Badge tone="success">Active</Badge> : <Badge tone="neutral">Deactivated</Badge>}
      </td>
      <td className="px-4 text-right">
        {me ? (
          <span className="text-[12px] text-muted">—</span>
        ) : u.active ? (
          confirming ? (
            <Button size="sm" variant="danger" loading={busy} onClick={() => patch({ active: false }, `${titleCase(u.username)} deactivated — they can no longer sign in`)}>
              Confirm deactivate
            </Button>
          ) : (
            <Button size="sm" variant="ghost" onClick={() => setConfirming(true)}>Deactivate</Button>
          )
        ) : (
          <Button size="sm" variant="secondary" loading={busy} onClick={() => patch({ active: true }, `${titleCase(u.username)} reactivated`)}>
            Reactivate
          </Button>
        )}
      </td>
    </tr>
  );
}

export function UsersAdmin() {
  const { user } = useAuth();
  const isAdmin = can(user, "manageUsers");
  const users = useApi<AdminUser[]>(isAdmin ? listUsers : null, [], [isAdmin], { live: anyEvent });
  const [creating, setCreating] = useState(false);
  const [q, setQ] = useState("");
  const [show, setShow] = useState<"all" | "active" | "inactive">("all");

  const rows = useMemo(() => {
    const s = q.trim().toLowerCase();
    return [...users.data]
      .filter((u) => (show === "all" ? true : show === "active" ? u.active : !u.active))
      .filter((u) => !s || `${u.username} ${u.role}`.toLowerCase().includes(s))
      .sort((a, b) => Number(b.active) - Number(a.active) || a.username.localeCompare(b.username));
  }, [users.data, q, show]);

  if (!isAdmin) {
    return (
      <EmptyState
        title="Admins only"
        description={`${WHO_CAN.manageUsers} You’re signed in as ${roleLabel(user?.role).toLowerCase() || "a member"}.`}
        action={<Link href="/"><Button variant="secondary">Back to the dashboard</Button></Link>}
      />
    );
  }

  const counts = ROLE_OPTIONS.map((r) => [r, users.data.filter((u) => u.role === r && u.active).length] as const);

  return (
    <div className="flex-1 pb-14">
      <PageHeader
        title="Users"
        description="Who can sign in, and what their role lets them do. Deal access is separate: compliance manages each deal’s wall."
        meta={users.data.length ? `${users.data.filter((u) => u.active).length} active` : undefined}
        actions={
          <Button onClick={() => setCreating(true)}>
            <UserPlus className="h-3.5 w-3.5" /> New user
          </Button>
        }
      />
      <div className="px-8">
        {users.data.length ? (
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <div className="relative w-64">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted" />
              <input value={q} onChange={(e) => setQ(e.target.value)} aria-label="Filter users" placeholder="Filter by name or role…" className={cx(inputCls, "h-7 pl-8 text-[12px]")} />
            </div>
            <Segmented
              label="Status"
              value={show}
              onChange={setShow}
              options={[
                { value: "all", label: "All" },
                { value: "active", label: "Active" },
                { value: "inactive", label: "Deactivated" },
              ]}
            />
            <span className="ml-auto flex flex-wrap gap-3 text-[12px] text-muted">
              {counts.map(([r, n]) => (
                <span key={r}>{roleLabel(r)} <span className="num font-mono text-fg-2">{n}</span></span>
              ))}
            </span>
          </div>
        ) : null}

        {users.unavailable ? (
          <Unavailable what="User management" />
        ) : users.error ? (
          <InlineError message={users.error} onRetry={users.refresh} />
        ) : (
          <div className="overflow-hidden rounded-md border border-line bg-surface shadow-card">
            {users.loading ? (
              <SkeletonRows rows={5} height={48} />
            ) : rows.length === 0 ? (
              <EmptyState compact title={users.data.length ? "No users match" : "No users yet"} description={users.data.length ? "Clear the filter to see everyone." : "Create the first dealmaker, analyst or compliance account."} />
            ) : (
              <table className="w-full border-collapse text-left">
                <thead>
                  <tr className="h-9 border-b border-line text-[12px] text-muted">
                    <th className="px-4 font-medium">User</th>
                    <th className="w-48 px-2 font-medium">Role</th>
                    <th className="w-32 px-2 font-medium">Status</th>
                    <th className="w-44 px-4 text-right font-medium"><span className="sr-only">Actions</span></th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((u) => (
                    <UserRow key={u.id} u={u} me={u.username === user?.username} onChanged={users.refresh} />
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
        <p className="mt-3 text-[12px] text-muted">Role changes take effect on the user’s next request. Deactivated users keep their history in the audit chain.</p>
      </div>
      <NewUserSheet open={creating} onClose={() => setCreating(false)} onCreated={users.refresh} />
    </div>
  );
}

"use client";

import { BadgeCheck, Mail, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useCan } from "@/features/auth/useCan";
import { WHO_CAN } from "@/features/auth/roles";
import { anyEvent } from "@/shared/api/events";
import { formatDateTime } from "@/shared/lib/format";
import { errMessage, useApi } from "@/shared/lib/useApi";
import { Badge, Button, inputCls, labelCls } from "@/shared/ui/primitives";
import { Permit } from "@/shared/ui/Permit";
import { Notice } from "@/shared/ui/States";
import { useToast } from "@/shared/ui/toast";
import { addContact, listContacts, removeContact, verifyContact, type Contact } from "../api";

function ContactRow({ c, partyId, onChanged }: { c: Contact; partyId: number; onChanged: () => void }) {
  const can = useCan();
  const toast = useToast();
  const [busy, setBusy] = useState<"verify" | "remove" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(kind: "verify" | "remove") {
    setBusy(kind);
    setError(null);
    try {
      if (kind === "verify") await verifyContact(c.id);
      else await removeContact(partyId, c.id);
      toast(kind === "verify" ? `${c.email} verified` : `${c.email} removed`);
      onChanged();
    } catch (err) {
      setError(errMessage(err));
      toast(errMessage(err), "error");
    } finally {
      setBusy(null);
    }
  }

  return (
    <li className="py-1.5">
      <div className="flex min-h-7 items-center gap-2">
        <Mail className="h-3.5 w-3.5 shrink-0 text-muted" />
        <span className="min-w-0 truncate text-[13px] text-fg">{c.name}</span>
        <span className="min-w-0 truncate font-mono text-[12px] text-fg-2">{c.email}</span>
        {c.is_primary ? <Badge tone="accent">Primary</Badge> : null}
        {c.verified_at ? (
          <Badge tone="success" title={`Verified${c.verified_by ? ` by ${c.verified_by}` : ""} ${formatDateTime(c.verified_at)}`}>
            <BadgeCheck className="h-3 w-3" /> Verified
          </Badge>
        ) : (
          <Badge tone="warning">Unverified</Badge>
        )}
        <span className="ml-auto flex items-center gap-1.5">
          {!c.verified_at ? (
            <Permit allow={can("verifyContact")} why={WHO_CAN.verifyContact} hide>
              <Button size="sm" variant="secondary" loading={busy === "verify"} onClick={() => run("verify")}>Verify</Button>
            </Permit>
          ) : null}
          <Permit allow={can("manageContacts")} why={WHO_CAN.manageContacts} hide>
            <Button size="sm" variant="ghost" aria-label={`Remove ${c.email}`} loading={busy === "remove"} onClick={() => run("remove")}>
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </Permit>
        </span>
      </div>
      {error ? <p className="mt-1 text-[11px] text-danger">{error}</p> : null}
    </li>
  );
}

/** Email contacts for one party: list, add, verify, remove. Outbound email only goes to a verified one. */
export function PartyContacts({ partyId }: { partyId: number }) {
  const allowed = useCan()("manageContacts");
  const toast = useToast();
  const contacts = useApi<Contact[]>(() => listContacts(partyId), [], [partyId], { live: anyEvent, pollMs: 60000 });
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [primary, setPrimary] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await addContact(partyId, { name: name.trim(), email: email.trim(), is_primary: primary });
      toast("Contact added — verify the email before any message can go to it");
      setName("");
      setEmail("");
      setPrimary(false);
      setAdding(false);
      contacts.refresh();
    } catch (err) {
      // 409 = already on this party, 422 = not a valid email.
      setError(errMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (contacts.forbidden || contacts.unavailable) return null;

  return (
    <div className="border-t border-line-subtle bg-canvas px-4 py-2.5 pl-[52px]">
      <div className="flex items-center gap-2">
        <span className="text-[11px] font-medium text-muted">Email contacts</span>
        {!adding ? (
          <span className="ml-auto">
            <Permit allow={allowed} why={WHO_CAN.manageContacts}>
              <Button size="sm" variant="ghost" onClick={() => setAdding(true)}><Plus className="h-3.5 w-3.5" /> Add email</Button>
            </Permit>
          </span>
        ) : null}
      </div>
      {contacts.error ? <p className="mt-1 text-[12px] text-danger">{contacts.error}</p> : null}
      {!contacts.loading && !contacts.error && contacts.data.length === 0 && !adding ? (
        <p className="py-1 text-[12px] text-muted">No email on file. Add one to let the outreach agent draft to this party.</p>
      ) : null}
      {contacts.data.length ? (
        <ul className="divide-y divide-line-subtle">
          {contacts.data.map((c) => <ContactRow key={c.id} c={c} partyId={partyId} onChanged={contacts.refresh} />)}
        </ul>
      ) : null}
      {adding ? (
        <form onSubmit={submit} className="mt-2 space-y-3 rounded-sm border border-line bg-surface p-3">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <div>
              <label htmlFor={`ct-name-${partyId}`} className={labelCls}>Name</label>
              <input id={`ct-name-${partyId}`} required autoFocus value={name} onChange={(e) => setName(e.target.value)} className={inputCls} placeholder="Priya Nair" />
            </div>
            <div>
              <label htmlFor={`ct-email-${partyId}`} className={labelCls}>Email</label>
              <input id={`ct-email-${partyId}`} required type="email" value={email} onChange={(e) => setEmail(e.target.value)} className={inputCls} placeholder="priya@example.com" />
            </div>
          </div>
          <label className="flex items-center gap-2 text-[13px] text-fg-2">
            <input type="checkbox" checked={primary} onChange={(e) => setPrimary(e.target.checked)} /> Primary contact for this party
          </label>
          {error ? <Notice tone="error">{error}</Notice> : null}
          <div className="flex justify-end gap-2">
            <Button type="button" size="sm" variant="ghost" onClick={() => { setAdding(false); setError(null); }}>Cancel</Button>
            <Button type="submit" size="sm" loading={busy} disabled={!name.trim() || !email.trim()}>Add email</Button>
          </div>
        </form>
      ) : null}
    </div>
  );
}

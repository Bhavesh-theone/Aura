import { apiFetch } from "@/shared/api/client";

export type Contact = {
  id: number;
  party_id: number;
  name: string;
  email: string;
  is_primary: boolean;
  verified_at: string | null;
  verified_by: string | null;
  created_by: string;
  created_at: string;
};

export const listContacts = (partyId: number) => apiFetch<Contact[]>(`/api/parties/${partyId}/contacts`);
export const addContact = (partyId: number, b: { name: string; email: string; is_primary: boolean }) =>
  apiFetch<Contact>(`/api/parties/${partyId}/contacts`, { method: "POST", body: b });
export const removeContact = (partyId: number, contactId: number) =>
  apiFetch<void>(`/api/parties/${partyId}/contacts/${contactId}`, { method: "DELETE" });
export const verifyContact = (contactId: number) => apiFetch<Contact>(`/api/parties/contacts/${contactId}/verify`, { method: "POST" });

export type SuppressionKind = "email" | "domain";
export type Suppression = { id: number; kind: SuppressionKind; value: string; reason: string; created_by: string; created_at: string };

export const listSuppression = () => apiFetch<Suppression[]>("/api/suppression");
export const addSuppression = (b: { kind: SuppressionKind; value: string; reason: string }) =>
  apiFetch<Suppression>("/api/suppression", { method: "POST", body: b });
export const removeSuppression = (id: number) => apiFetch<void>(`/api/suppression/${id}`, { method: "DELETE" });

export type OutboundMode = "off" | "gmail_draft" | "gmail_send";
export type OutboundStatus = "queued" | "drafted" | "sent" | "blocked" | "failed";
export type Outbound = {
  id: number;
  handoff_id: number | null;
  job_id: number | null;
  deal_id: number | null;
  party_id: number | null;
  to_email: string;
  subject: string;
  mode: OutboundMode;
  status: OutboundStatus;
  gmail_id: string | null;
  gmail_thread_id: string | null;
  error: string | null;
  created_at: string;
  completed_at: string | null;
  trace_id: string | null;
};

export const listOutbound = (handoffId: number) => apiFetch<Outbound[]>(`/api/outbound?handoff_id=${handoffId}`);

export type GmailStatus = {
  mode: OutboundMode;
  connected: boolean;
  account_email: string | null;
  scopes: string[];
  expires_at: string | null;
  needs_reconnect: boolean;
  storage: "keyring" | "encrypted_file" | null;
  daily_limit: number;
  sent_today: number;
  connect_command: string;
  detail: string | null;
};

export const getGmailStatus = () => apiFetch<GmailStatus>("/api/integrations/gmail");

export const MODE_LABEL: Record<OutboundMode, string> = { off: "Off", gmail_draft: "Drafts only", gmail_send: "Send" };

export const BLOCK_REASON: Record<string, string> = {
  outbound_off: "outbound email is switched off",
  gmail_not_connected: "Gmail is not connected",
  gmail_reconnect_needed: "Gmail needs to be reconnected",
  no_verified_email: "the recipient has no verified email",
  recipient_changed: "the recipient changed after approval",
  suppressed: "the recipient is on the suppression list",
  approver_not_on_wall: "the approver is not on the deal wall",
  daily_limit_reached: "the daily send limit was reached",
  no_explicit_approval: "there was no explicit approval",
  refused_by_server: "the server refused it",
};
export const blockReason = (r: string) => BLOCK_REASON[r] ?? r.replace(/_/g, " ");

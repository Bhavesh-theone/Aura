"use client";

import Link from "next/link";
import { useAuth } from "@/features/auth/hooks";
import { WHO_CAN, can, roleLabel } from "@/features/auth/roles";
import { anyEvent } from "@/shared/api/events";
import { formatDateTime } from "@/shared/lib/format";
import { useApi } from "@/shared/lib/useApi";
import { PageHeader } from "@/shared/ui/PageHeader";
import { Badge, Button, Card, CardHeader } from "@/shared/ui/primitives";
import { EmptyState, InlineError, Notice, SkeletonRows, Unavailable } from "@/shared/ui/States";
import { MODE_LABEL, getGmailStatus, type GmailStatus } from "../api";
import { CopyBlock } from "./CopyBlock";

function Fact({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[150px_1fr] gap-4 px-4 py-2.5 text-[13px]">
      <dt className="text-muted">{k}</dt>
      <dd className="min-w-0 break-words text-fg-2">{children}</dd>
    </div>
  );
}

const codeCls = "rounded-xs border border-line bg-well px-1 font-mono text-[12px] text-fg";

function GmailCard({ g }: { g: GmailStatus }) {
  const state = g.needs_reconnect ? "reconnect" : g.connected ? "connected" : "none";
  return (
    <Card>
      <CardHeader
        title="Gmail"
        aside={
          state === "connected" ? <Badge tone="success">Connected</Badge> : state === "reconnect" ? <Badge tone="warning">Reconnect needed</Badge> : <Badge tone="neutral">Not connected</Badge>
        }
      />
      <dl className="divide-y divide-line-subtle">
        <Fact k="Account">
          {state === "reconnect" ? (
            <span className="text-warning">Reconnect needed{g.account_email ? ` (${g.account_email})` : ""}</span>
          ) : g.connected ? (
            <>Connected as <span className="font-mono text-fg">{g.account_email}</span></>
          ) : (
            "Not connected"
          )}
        </Fact>
        <Fact k="Mode">
          <span className="flex flex-wrap items-center gap-2">
            <Badge tone={g.mode === "off" ? "neutral" : g.mode === "gmail_send" ? "danger" : "accent"}>{MODE_LABEL[g.mode]}</Badge>
            <span className="font-mono text-[11px] text-muted">{g.mode}</span>
          </span>
        </Fact>
        <Fact k="Daily limit">
          <span className="num font-mono text-fg">{g.sent_today}</span> sent today of <span className="num font-mono text-fg">{g.daily_limit}</span>
        </Fact>
        <Fact k="Scopes">
          {g.scopes.length ? (
            <span className="flex flex-wrap gap-1">{g.scopes.map((s) => <Badge key={s} mono>{s.replace("https://www.googleapis.com/auth/", "")}</Badge>)}</span>
          ) : (
            <span className="text-muted">None</span>
          )}
        </Fact>
        <Fact k="Token expires">{g.expires_at ? <span className="num font-mono">{formatDateTime(g.expires_at)}</span> : <span className="text-muted">—</span>}</Fact>
        <Fact k="Token storage">{g.storage ? <span className="font-mono">{g.storage === "keyring" ? "OS keyring" : "Encrypted file"}</span> : <span className="text-muted">—</span>}</Fact>
      </dl>
      {g.detail ? <p className="border-t border-line-subtle px-4 py-2.5 text-[12px] text-muted">{g.detail}</p> : null}
    </Card>
  );
}

export function IntegrationsView() {
  const { user } = useAuth();
  const allowed = can(user, "viewIntegrations");
  const g = useApi<GmailStatus | null>(allowed ? getGmailStatus : null, null, [allowed], { live: anyEvent, pollMs: 60000 });

  if (!allowed) {
    return (
      <EmptyState
        title="Admins and dealmakers only"
        description={`${WHO_CAN.viewIntegrations} You’re signed in as ${roleLabel(user?.role).toLowerCase() || "a member"}.`}
        action={<Link href="/"><Button variant="secondary">Back to the dashboard</Button></Link>}
      />
    );
  }

  return (
    <div className="flex-1 pb-14">
      <PageHeader
        title="Integrations"
        description="Outbound email goes through Gmail, only after a person approves it in Decisions. Connecting and the on/off mode are done on the server, on purpose."
      />
      <div className="max-w-[820px] space-y-6 px-8">
        {g.forbidden ? (
          <Notice tone="warn">The server says your role can’t read integrations.</Notice>
        ) : g.unavailable ? (
          <Unavailable what="Integrations" />
        ) : g.error ? (
          <InlineError message={g.error} onRetry={g.refresh} />
        ) : g.loading || !g.data ? (
          <Card><SkeletonRows rows={5} height={40} /></Card>
        ) : (
          <>
            {g.data.needs_reconnect ? (
              <Notice tone="warn" title="Gmail needs to be reconnected">
                Outbound email is blocked until you run the connect command below again.
              </Notice>
            ) : null}
            <GmailCard g={g.data} />
            <Card>
              <CardHeader title="Connect, check or disconnect" />
              <div className="space-y-3 px-4 py-4">
                <p className="text-[13px] text-fg-2">Run these in a terminal on the machine that runs the Aura backend.</p>
                <CopyBlock label="1 · Go to the backend" command="cd backend" />
                <CopyBlock label="2 · Connect (opens a Google consent screen)" command={g.data.connect_command || "uv run python -m aura.mcp.gmail_auth"} />
                <CopyBlock label="Check status" command="uv run python -m aura.mcp.gmail_auth --status" />
                <CopyBlock label="Revoke access and forget the token" command="uv run python -m aura.mcp.gmail_auth --revoke" />
              </div>
            </Card>
            <Card>
              <CardHeader title="Outbound mode" />
              <div className="space-y-3 px-4 py-4 text-[13px] leading-relaxed text-fg-2">
                <p>
                  The mode is set with <code className={codeCls}>AURA_OUTBOUND_MODE</code> in <code className={codeCls}>backend/.env</code>, then restart the backend. It is not changeable from this page on purpose, so nobody can turn sending on from a browser.
                </p>
                <ul className="space-y-1.5">
                  <li><code className="font-mono text-[12px] text-fg">off</code> · approving a draft sends nothing.</li>
                  <li><code className="font-mono text-[12px] text-fg">gmail_draft</code> · approving creates a draft in Gmail for someone to review and send.</li>
                  <li><code className="font-mono text-[12px] text-fg">gmail_send</code> · approving sends the email through Gmail.</li>
                </ul>
              </div>
            </Card>
          </>
        )}
      </div>
    </div>
  );
}

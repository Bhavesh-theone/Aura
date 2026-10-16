"use client";

import { ArrowLeft, ArrowUpRight } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ApiError } from "@/shared/api/client";
import { cx, formatINR, formatINRCompact, titleCase } from "@/shared/lib/format";
import { errMessage } from "@/shared/lib/useApi";
import { Badge, Button, inputCls, labelCls } from "@/shared/ui/primitives";
import { Notice } from "@/shared/ui/States";
import { useToast } from "@/shared/ui/toast";
import type { IntakeWizard } from "../hooks";
import { effectiveField, overlay } from "../machine";
import { CLASS_LABEL, type IntakeField, type PartyValue } from "../types";
import { fieldDomId } from "./FieldRow";

const filled = (v: unknown) => v !== null && v !== undefined && v !== "" && !(Array.isArray(v) && v.length === 0);

function display(f: IntakeField): string {
  const v = f.value;
  if (!filled(v)) return "—";
  // Statement figures keep their two decimals in crore (₹412.38 Cr, not ₹412 Cr).
  if (f.type === "inr" && typeof v === "number")
    return Math.abs(v) >= 1e7 ? `₹${(v / 1e7).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} Cr` : formatINRCompact(v);
  if (f.type === "percent" && typeof v === "number") return `${v}%`;
  if (f.type === "enum" && typeof v === "string") return f.enum_labels?.[v] ?? v;
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (Array.isArray(v)) return `${v.length} item${v.length === 1 ? "" : "s"}`;
  return typeof v === "object" ? JSON.stringify(v) : String(v);
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[160px_minmax(0,1fr)] gap-3 border-b border-line-subtle py-2.5 last:border-0">
      <dt className="text-[12px] text-muted">{label}</dt>
      <dd className="min-w-0 text-[13px] text-fg">{children}</dd>
    </div>
  );
}

/** Jump back to the first field the server rejected. */
function focusField(key: string) {
  // Let the review step render first.
  setTimeout(() => {
    const el = document.getElementById(`${fieldDomId(key)}-row`);
    el?.scrollIntoView({ block: "center", behavior: "smooth" });
    el?.querySelector<HTMLElement>("input,select,textarea,button")?.focus({ preventScroll: true });
  }, 60);
}

export function ConfirmStep({ w }: { w: IntakeWizard }) {
  const router = useRouter();
  const toast = useToast();
  const s = w.state;
  const intake = s.intake;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [already, setAlready] = useState(false);
  if (!intake) return null;

  const p = overlay(s);
  const field = (k: string) => (intake.fields[k] ? effectiveField(intake.fields[k], p) : null);
  const name = String(field("deal_name")?.value ?? field("company_name")?.value ?? intake.title ?? "");
  const cls = p.transaction_class ?? intake.transaction_class ?? "";
  const externalId = (p.external_id !== undefined ? p.external_id : intake.external_id) ?? "";
  const all = Object.values(intake.fields).map((f) => effectiveField(f, p));
  // The company itself is always linked (issuer, or target for M&A), then the included parties.
  const company = String(field("company_name")?.value ?? "");
  const companyRole = cls === "MNA" ? "target" : "issuer";
  const parties = [
    ...(company ? [{ name: company, role: companyRole } as PartyValue] : []),
    ...all
      .filter((f) => f.type === "parties")
      .flatMap((f) => (Array.isArray(f.value) ? (f.value as PartyValue[]) : []))
      .filter((x) => x.include !== false && x.name && x.name.toLowerCase() !== company.toLowerCase()),
  ];
  const money = all.filter((f) => f.type === "inr" && f.group === "financials" && filled(f.value));
  const profile = all.filter((f) => f.group === "profile");
  const profileFilled = profile.filter((f) => filled(f.value)).length;
  const flags = all
    .filter((f) => f.type === "flags")
    .flatMap((f) => (Array.isArray(f.value) ? (f.value as { flag: string; include: boolean }[]) : []))
    .filter((x) => x.include !== false);

  const conflictList = intake.conflicts;

  async function create() {
    setBusy(true);
    setError(null);
    setAlready(false);
    try {
      const res = await w.confirm({ external_id: externalId.trim() || undefined, name: name.trim() || undefined });
      toast(`Deal “${res.name}” created${res.external_id ? ` · ${res.external_id}` : ""}`);
      res.warnings.forEach((m) => toast(m, "info"));
      router.push(`/deals/${res.deal_id}`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setAlready(true);
        setError(err.message || "This intake was already turned into a deal.");
        w.reload();
      } else if (err instanceof ApiError && err.status === 422) {
        const detail = (err.detail ?? {}) as { field_errors?: Record<string, string> };
        const errors = detail.field_errors ?? {};
        const keys = Object.keys(errors);
        if (keys.length) {
          w.dispatch({ type: "fieldErrors", errors });
          w.dispatch({ type: "go", view: "review" });
          const first = keys[0].startsWith("conflict:")
            ? conflictList.find((c) => `conflict:${c.id}` === keys[0])?.field ?? keys[0]
            : keys[0];
          toast(`${keys.length} field${keys.length === 1 ? "" : "s"} need${keys.length === 1 ? "s" : ""} fixing before the deal can be created`, "error");
          focusField(first);
        } else {
          setError(errMessage(err));
        }
      } else {
        setError(errMessage(err));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="min-w-0 rounded-md border border-line bg-surface px-5 py-2 shadow-card">
        <dl>
          <Row label="Deal name">
            <span className="font-serif text-[18px] leading-tight">{name || "—"}</span>
          </Row>
          <Row label="Transaction class">{cls ? <Badge>{CLASS_LABEL[cls] ?? cls}</Badge> : "—"}</Row>
          <Row label="Parties">
            {parties.length ? (
              <ul className="space-y-0.5">
                {parties.map((x, i) => (
                  <li key={i} className="flex items-baseline gap-2">
                    <span className="truncate">{x.name}</span>
                    <span className="text-[12px] text-muted">{titleCase(x.role ?? "")}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <span className="text-muted">None</span>
            )}
          </Row>
          <Row label="Key financials">
            {money.length ? (
              <ul className="space-y-0.5">
                {money.map((f) => (
                  <li key={f.key} className="flex items-baseline gap-2">
                    <span className="text-[12px] text-muted">{f.label}</span>
                    <span className="num ml-auto font-medium" title={typeof f.value === "number" ? formatINR(f.value) : undefined}>{display(f)}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <span className="text-muted">None extracted</span>
            )}
          </Row>
          {flags.length ? (
            <Row label="Regulatory">
              <span className="flex flex-wrap gap-1">
                {flags.map((f) => (
                  <Badge key={f.flag} tone="warning">{f.flag.replace(/_/g, " ")}</Badge>
                ))}
              </span>
            </Row>
          ) : null}
          <Row label="Documents">
            <span className="num">{intake.files.length}</span> <span className="text-muted">— attached to the deal, already indexed</span>
          </Row>
          <Row label="Class profile">
            <span className="num">{profileFilled}</span>
            <span className="text-muted"> of {profile.length} fields filled</span>
          </Row>
        </dl>
      </div>

      <aside className="space-y-4">
        <div>
          <label htmlFor="ik-extid" className={labelCls}>
            Deal ID <span className="font-normal text-muted">(optional)</span>
          </label>
          <input
            id="ik-extid"
            value={externalId}
            onChange={(e) => w.edit({ external_id: e.target.value || null })}
            className={cx(inputCls, "font-mono")}
            placeholder="Auto, e.g. AUR-0007"
            spellCheck={false}
            autoComplete="off"
          />
          <p className="mt-1.5 text-[12px] text-muted">Leave blank and Aura assigns the next one.</p>
        </div>

        {error ? (
          <Notice tone={already ? "warn" : "error"} title={already ? "Already created" : "Couldn’t create the deal"}>
            {error}
            {already && intake.confirmed_deal_id ? (
              <>
                {" "}
                <Link href={`/deals/${intake.confirmed_deal_id}`} className="inline-flex items-center gap-0.5 font-medium underline underline-offset-2">
                  Open the deal <ArrowUpRight className="h-3 w-3" />
                </Link>
              </>
            ) : null}
          </Notice>
        ) : null}

        <div className="space-y-2 border-t border-line-subtle pt-4">
          <Button size="lg" className="w-full" onClick={create} loading={busy} disabled={already}>
            Create deal
          </Button>
          <Button size="sm" variant="ghost" className="w-full" onClick={() => w.dispatch({ type: "go", view: "review" })}>
            <ArrowLeft className="h-3 w-3" /> Back to review
          </Button>
          <p className="text-[12px] leading-relaxed text-muted">The deal starts at Originated. Every later move is guarded and audited.</p>
        </div>
      </aside>
    </div>
  );
}

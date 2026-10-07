"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { ApiError } from "@/shared/api/client";
import { errMessage } from "@/shared/lib/useApi";
import { Button, inputCls, labelCls, selectCls, textareaCls } from "@/shared/ui/primitives";
import { Notice } from "@/shared/ui/States";
import { useToast } from "@/shared/ui/toast";
import { CAPABILITY_LABEL, submitJob } from "../api";
import type { Capability, CreateJobRequest } from "../types";
import { fmtSecs } from "./present";
import { useEffect } from "react";

/** Manual job submission with an Idempotency-Key, a live 429 cooldown, and the backend's own 409 reason. */
export function SubmitJob({ onSubmitted }: { onSubmitted: (jobId: number) => void }) {
  const toast = useToast();
  const [capability, setCapability] = useState<Capability>("classify_document");
  const [dealId, setDealId] = useState("");
  const [documentId, setDocumentId] = useState("");
  const [brief, setBrief] = useState("");
  const [busy, setBusy] = useState(false);
  const [conflict, setConflict] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [cooldownUntil, setCooldownUntil] = useState<number | null>(null);
  const [left, setLeft] = useState(0);
  // One key per submission attempt; reused if the same request is retried after a network failure.
  const keyRef = useRef<{ sig: string; key: string } | null>(null);

  useEffect(() => {
    if (cooldownUntil === null) return;
    const tick = () => {
      const s = Math.max(0, Math.ceil((cooldownUntil - Date.now()) / 1000));
      setLeft(s);
      if (s === 0) setCooldownUntil(null);
    };
    tick();
    const t = setInterval(tick, 500);
    return () => clearInterval(t);
  }, [cooldownUntil]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const inputs: CreateJobRequest["inputs"] = { capability };
    if (documentId.trim()) inputs.document_id = Number(documentId);
    if (brief.trim()) inputs.brief = brief.trim();
    const body: CreateJobRequest = { deal_id: dealId.trim() ? Number(dealId) : null, inputs };
    const sig = JSON.stringify(body);
    if (!keyRef.current || keyRef.current.sig !== sig) keyRef.current = { sig, key: crypto.randomUUID() };
    setBusy(true);
    setConflict(null);
    setFailure(null);
    try {
      const { job, replayed } = await submitJob(body, keyRef.current.key);
      keyRef.current = null;
      if (replayed) toast("Already submitted — showing the original job", "info");
      else toast(`${CAPABILITY_LABEL[capability]} queued as JOB-${job.id}.`);
      onSubmitted(job.id);
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        keyRef.current = null;
        setCooldownUntil(Date.now() + Math.max(1, err.retryAfter ?? 5) * 1000);
      } else if (err instanceof ApiError && err.status === 409) {
        keyRef.current = null;
        setConflict(err.message);
      } else {
        // Network failure: keep the key so a retry of the same body is deduplicated.
        setFailure(errMessage(err));
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-3 border-b border-line bg-well px-4 py-4">
      <div>
        <label className={labelCls} htmlFor="sj-cap">Capability</label>
        <select id="sj-cap" className={selectCls} value={capability} onChange={(e) => setCapability(e.target.value as Capability)}>
          {(Object.keys(CAPABILITY_LABEL) as Capability[]).map((c) => (
            <option key={c} value={c}>{CAPABILITY_LABEL[c]}</option>
          ))}
        </select>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className={labelCls} htmlFor="sj-deal">Deal #</label>
          <input id="sj-deal" className={inputCls} inputMode="numeric" pattern="[0-9]*" value={dealId} onChange={(e) => setDealId(e.target.value)} />
        </div>
        <div>
          <label className={labelCls} htmlFor="sj-doc">Document #</label>
          <input id="sj-doc" className={inputCls} inputMode="numeric" pattern="[0-9]*" value={documentId} onChange={(e) => setDocumentId(e.target.value)} />
        </div>
      </div>
      <div>
        <label className={labelCls} htmlFor="sj-brief">Brief (optional)</label>
        <textarea id="sj-brief" className={textareaCls} value={brief} onChange={(e) => setBrief(e.target.value)} />
      </div>
      {left > 0 ? (
        <Notice tone="warn" title="Slow down a little">
          You’ve submitted a lot of jobs recently. You can submit again in <span className="num font-mono">{fmtSecs(left)}</span>.
        </Notice>
      ) : null}
      {conflict ? (
        <Notice tone="error" title="This job can’t be submitted" action={<Link href="/quality" className="text-[12px] font-medium underline">Agent quality</Link>}>
          {conflict}
        </Notice>
      ) : null}
      {failure ? <Notice tone="error">{failure}</Notice> : null}
      <Button type="submit" size="md" loading={busy} disabled={left > 0} className="w-full">
        {left > 0 ? `Wait ${fmtSecs(left)}` : "Submit job"}
      </Button>
    </form>
  );
}

"use client";

import { ArrowRight, CircleAlert, CircleCheck, CloudUpload, FileText, RotateCw, Trash2, X } from "lucide-react";
import Link from "next/link";
import { useRef, useState } from "react";
import { cx, humanize } from "@/shared/lib/format";
import { errMessage } from "@/shared/lib/useApi";
import { Badge, Button, IconButton, Spinner, Tip, inputCls, labelCls, selectCls } from "@/shared/ui/primitives";
import { Notice } from "@/shared/ui/States";
import { formatBytes, type IntakeWizard } from "../hooks";
import { overlay, type UploadItem } from "../machine";
import { CLASSES, CLASS_LABEL, type DocumentFormats, type IntakeFile } from "../types";
import { ProgressBar } from "./bits";

/* --------------------------------- Dropzone -------------------------------- */

function Dropzone({ formats, onFiles }: { formats: DocumentFormats; onFiles: (f: FileList) => void }) {
  const [drag, setDrag] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  return (
    <div>
      <label
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          if (e.dataTransfer.files?.length) onFiles(e.dataTransfer.files);
        }}
        className={cx(
          "flex cursor-pointer flex-col items-center gap-2 rounded-md border border-dashed px-6 py-10 text-center transition-colors",
          "focus-within:border-accent focus-within:shadow-[0_0_0_3px_var(--accent-soft)]",
          drag ? "border-accent bg-accent-soft" : "border-line-strong bg-canvas hover:bg-control-hover",
        )}
      >
        <span className="flex h-9 w-9 items-center justify-center rounded-full border border-line bg-surface text-muted shadow-card">
          <CloudUpload className="h-4 w-4" />
        </span>
        <span className="text-[14px] font-medium text-fg">Drop the deal documents here, or browse</span>
        <span className="max-w-md text-[12px] leading-relaxed text-muted">
          Information memorandum, financials, term sheet, cap table, MCA filings — as many as you have. Aura reads them and fills the deal in for you to check.
        </span>
        <input
          ref={input}
          type="file"
          multiple
          accept={formats.accept || formats.extensions.join(",")}
          className="sr-only"
          aria-label="Choose documents to upload"
          onChange={(e) => {
            if (e.target.files?.length) onFiles(e.target.files);
            e.target.value = "";
          }}
        />
      </label>
      <p className="mt-2 text-[12px] leading-relaxed text-muted">
        Accepted: <span className="font-mono text-[11px] text-fg-2">{formats.extensions.map((x) => x.replace(/^\./, "").toUpperCase()).join(" · ")}</span>
        {" "}· up to {formats.max_upload_mb} MB each{formats.ocr_enabled ? " · scanned PDFs are read with OCR" : ""}.
      </p>
    </div>
  );
}

/* --------------------------------- File rows ------------------------------- */

const STAGE_BADGE: Record<IntakeFile["stage"], { label: string; tone: "neutral" | "info" | "success" | "danger" }> = {
  uploaded: { label: "Queued for reading", tone: "neutral" },
  parsing: { label: "Reading", tone: "info" },
  indexed: { label: "Indexed", tone: "success" },
  failed: { label: "Couldn’t read", tone: "danger" },
};

function Row({ icon, name, meta, children, aside }: { icon: React.ReactNode; name: string; meta?: React.ReactNode; children?: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <li className="px-4 py-2.5">
      <div className="flex items-center gap-3">
        <span className="shrink-0 text-muted">{icon}</span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-[13px] text-fg" title={name}>{name}</span>
            {meta}
          </div>
        </div>
        {aside ? <div className="flex shrink-0 items-center gap-1">{aside}</div> : null}
      </div>
      {children ? <div className="mt-2 pl-7">{children}</div> : null}
    </li>
  );
}

function UploadRow({ u, onRetry, onRemove }: { u: UploadItem; onRetry: () => void; onRemove: () => void }) {
  const busy = u.status === "queued" || u.status === "uploading";
  return (
    <Row
      icon={u.status === "invalid" || u.status === "failed" ? <CircleAlert className="h-4 w-4 text-danger" /> : u.status === "duplicate" ? <CircleCheck className="h-4 w-4 text-success" /> : <FileText className="h-4 w-4" />}
      name={u.name}
      meta={
        <>
          <span className="num shrink-0 font-mono text-[11px] text-muted">{formatBytes(u.size)}</span>
          {u.status === "duplicate" ? <Badge tone="neutral">Already added</Badge> : null}
          {busy ? <span className="num shrink-0 text-[12px] text-muted">{u.status === "queued" ? "Waiting…" : `${u.pct}%`}</span> : null}
        </>
      }
      aside={
        <>
          {u.status === "failed" && u.retriable ? (
            <Button size="sm" variant="secondary" onClick={onRetry}>
              <RotateCw className="h-3 w-3" /> Retry
            </Button>
          ) : null}
          <Tip label={busy ? "Cancel upload" : "Remove"}>
            <IconButton size="sm" label={`${busy ? "Cancel upload of" : "Remove"} ${u.name}`} onClick={onRemove}>
              <X className="h-3.5 w-3.5" />
            </IconButton>
          </Tip>
        </>
      }
    >
      {busy ? <ProgressBar pct={u.pct} label={`Uploading ${u.name}`} /> : null}
      {u.error ? <p className="text-[12px] text-danger">{u.error}</p> : null}
    </Row>
  );
}

function ServerFileRow({ f, onRemove }: { f: IntakeFile; onRemove: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const b = STAGE_BADGE[f.stage];
  return (
    <Row
      icon={f.stage === "failed" ? <CircleAlert className="h-4 w-4 text-danger" /> : <FileText className="h-4 w-4" />}
      name={f.filename}
      meta={
        <>
          <span className="num shrink-0 font-mono text-[11px] text-muted">{formatBytes(f.byte_size)}</span>
          <Badge tone={b.tone}>{f.stage === "parsing" ? <Spinner className="h-2.5 w-2.5" /> : null}{b.label}</Badge>
          {f.doc_class ? <span className="hidden truncate text-[12px] text-muted md:inline">{humanize(f.doc_class)}</span> : null}
        </>
      }
      aside={
        <Tip label="Remove from this intake">
          <IconButton
            size="sm"
            label={`Remove ${f.filename}`}
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              setError(null);
              try {
                await onRemove();
              } catch (err) {
                setError(errMessage(err));
                setBusy(false);
              }
            }}
          >
            {busy ? <Spinner /> : <Trash2 className="h-3.5 w-3.5" />}
          </IconButton>
        </Tip>
      }
    >
      {f.error || error ? <p className="text-[12px] text-danger">{error ?? f.error}</p> : null}
    </Row>
  );
}

/* ----------------------------------- Step ---------------------------------- */

export function StartStep({ w, formats }: { w: IntakeWizard; formats: DocumentFormats }) {
  const { state } = w;
  const intake = state.intake;
  const p = overlay(state);
  const hint = <K extends "company_name" | "cin" | "transaction_class_hint">(k: K) =>
    (p.hints[k] !== undefined ? p.hints[k] : intake?.hints[k]) ?? "";
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const serverFiles = intake?.files ?? [];
  const uploading = state.uploads.some((u) => u.status === "queued" || u.status === "uploading");
  const hasInput = serverFiles.length > 0 || hint("company_name").trim() !== "" || hint("cin").trim() !== "";

  function addFiles(list: FileList) {
    setError(null);
    w.addFiles(list, formats);
  }

  async function next() {
    setBusy(true);
    setError(null);
    try {
      await w.ensureIntake();
      // No documents: extraction works from the hints (registry lookups) alone.
      if (serverFiles.length === 0 || intake?.extraction.status === "failed") await w.extract();
      w.dispatch({ type: "go", view: "processing" });
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="min-w-0 space-y-4">
        <Dropzone formats={formats} onFiles={addFiles} />

        {state.uploads.length > 0 || serverFiles.length > 0 ? (
          <div className="rounded-md border border-line bg-surface shadow-card">
            <div className="flex h-10 items-center gap-2 border-b border-line-subtle px-4">
              <h3 className="text-[13px] font-medium text-fg">Documents</h3>
              <span className="num text-[12px] text-muted">{serverFiles.length} added</span>
            </div>
            <ul className="divide-y divide-line-subtle" aria-live="polite">
              {serverFiles.map((f) => (
                <ServerFileRow key={f.id} f={f} onRemove={() => w.removeFile(f.id)} />
              ))}
              {state.uploads.map((u) => (
                <UploadRow key={u.localId} u={u} onRetry={() => w.retryUpload(u.localId)} onRemove={() => w.removeUpload(u.localId)} />
              ))}
            </ul>
          </div>
        ) : null}
      </div>

      <aside className="space-y-4">
        <div>
          <h3 className="text-[13px] font-medium text-fg">What do you already know?</h3>
          <p className="mt-1 text-[12px] leading-relaxed text-muted">Optional. A name or CIN helps Aura pick the right company out of the documents.</p>
        </div>
        <div>
          <label htmlFor="ik-company" className={labelCls}>Company name</label>
          <input
            id="ik-company"
            value={hint("company_name")}
            onChange={(e) => w.edit({ hints: { company_name: e.target.value } })}
            className={inputCls}
            placeholder="e.g. Sunrise Infra Projects Ltd"
            autoComplete="off"
          />
        </div>
        <div>
          <label htmlFor="ik-cin" className={labelCls}>CIN</label>
          <input
            id="ik-cin"
            value={hint("cin")}
            onChange={(e) => w.edit({ hints: { cin: e.target.value.toUpperCase() } })}
            className={cx(inputCls, "font-mono")}
            placeholder="U45200MH2009PLC123456"
            spellCheck={false}
            autoComplete="off"
          />
        </div>
        <div>
          <label htmlFor="ik-class" className={labelCls}>Transaction class <span className="font-normal text-muted">(hint)</span></label>
          <select
            id="ik-class"
            value={hint("transaction_class_hint")}
            onChange={(e) => w.edit({ hints: { transaction_class_hint: e.target.value || null } })}
            className={selectCls}
          >
            <option value="">Let Aura work it out</option>
            {CLASSES.map((c) => (
              <option key={c} value={c}>{CLASS_LABEL[c]}</option>
            ))}
          </select>
        </div>

        {error ? <Notice tone="error">{error}</Notice> : null}

        <div className="border-t border-line-subtle pt-4">
          <Button size="lg" className="w-full" onClick={next} loading={busy} disabled={uploading || !hasInput}>
            {uploading ? "Waiting for uploads…" : serverFiles.length ? "Continue to extraction" : "Continue without documents"}
            {!uploading ? <ArrowRight className="h-4 w-4" /> : null}
          </Button>
          <p className="mt-2 text-[12px] leading-relaxed text-muted">
            {hasInput
              ? "Reading starts as soon as each file lands; your draft is saved as you go."
              : "Add a document, or a company name / CIN, to continue."}
          </p>
          <p className="mt-3 text-[12px] text-muted">
            Nothing to upload?{" "}
            <Link href="/deals?new=1" className="text-fg-2 underline decoration-line-strong underline-offset-2 hover:text-fg">
              Quick-create a blank deal
            </Link>
          </p>
        </div>
      </aside>
    </div>
  );
}

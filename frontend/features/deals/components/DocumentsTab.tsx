"use client";

import * as Menu from "@radix-ui/react-dropdown-menu";
import * as Popover from "@radix-ui/react-popover";
import {
  BadgeCheck, CircleDashed, Download, FileSignature, FileText, History, Lock, MoreHorizontal, ScanText, Sparkles, Upload,
} from "lucide-react";
import { useState } from "react";
import { WHO_CAN } from "@/features/auth/roles";
import { useCan } from "@/features/auth/useCan";
import { dealEvents } from "@/shared/api/events";
import { cx, formatDateTime, humanize, shortDate, titleCase } from "@/shared/lib/format";
import { errMessage, useApi } from "@/shared/lib/useApi";
import { Badge, Button, IconButton, Segmented, Tip } from "@/shared/ui/primitives";
import { Permit } from "@/shared/ui/Permit";
import { Sheet } from "@/shared/ui/Sheet";
import { useToast } from "@/shared/ui/toast";
import {
  downloadDocument, getDocument, listDocumentVersions, listDocuments, patchDocument, uploadDocumentWithProgress,
} from "../api";
import { DOC_CLASSES, SENSITIVITY, type DealDocument, type DocumentVersion } from "../types";
import { useRunAgent } from "./AgentActions";
import { EmptyState, InlineError, Notice, Section, SkeletonRows, Unavailable, labelCls, selectCls } from "./ui";

export function formatBytes(n?: number | null) {
  if (n == null) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

const sensTone = (s?: number) => (s === 4 ? "danger" : s === 3 ? "warning" : "neutral");

const menuItem =
  "flex h-8 cursor-default items-center gap-2 rounded-xs px-2 text-[13px] text-fg outline-none data-[disabled]:opacity-45 data-[highlighted]:bg-control-hover";

/* ------------------------------- Confirm class ------------------------------ */

function ConfirmClass({ doc, onDone, allowed }: { doc: DealDocument; onDone: () => void; allowed: boolean }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [cls, setCls] = useState(doc.doc_class);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await patchDocument(doc.id, { doc_class: cls });
      toast(`Class confirmed as ${humanize(cls)}`);
      setOpen(false);
      onDone();
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Popover.Root open={open} onOpenChange={(o) => { setOpen(o); if (o) { setCls(doc.doc_class); setError(null); } }}>
      <Permit allow={allowed} why={WHO_CAN.work}>
        <Popover.Trigger asChild>
          <button className="inline-flex h-5 items-center gap-1 rounded-xs border border-warning-border bg-warning-soft px-1.5 text-[11px] font-medium text-warning outline-none hover:opacity-85 focus-visible:ring-2 focus-visible:ring-accent/50">
            <CircleDashed className="h-3 w-3" /> Proposed · confirm
          </button>
        </Popover.Trigger>
      </Permit>
      <Popover.Portal>
        <Popover.Content align="start" sideOffset={6} className="a-pop z-50 w-72 rounded-md bg-raised p-3 shadow-overlay outline-none">
          <p className="text-[13px] font-medium text-fg">Confirm the document class</p>
          <p className="mt-0.5 text-[12px] text-muted">An agent or the uploader proposed this class. A person must confirm it before guards rely on it.</p>
          <label htmlFor={`cc-${doc.id}`} className={cx(labelCls, "mt-3")}>Class</label>
          <select id={`cc-${doc.id}`} value={cls} onChange={(e) => setCls(e.target.value)} className={selectCls}>
            {DOC_CLASSES.map((c) => (
              <option key={c} value={c}>{humanize(c)}</option>
            ))}
          </select>
          {error ? <Notice tone="error" className="mt-2">{error}</Notice> : null}
          <div className="mt-3 flex justify-end gap-2">
            <Popover.Close asChild>
              <Button size="sm" variant="ghost">Cancel</Button>
            </Popover.Close>
            <Button size="sm" onClick={save} loading={busy}>
              {cls === doc.doc_class ? "Confirm class" : "Change and confirm"}
            </Button>
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

/* --------------------------------- Versions -------------------------------- */

function VersionsSheet({ doc, onClose }: { doc: DealDocument | null; onClose: () => void }) {
  const toast = useToast();
  const id = doc?.id ?? null;
  // Opening the drawer reads the document — the server logs that as a view.
  const meta = useApi<DealDocument | null>(id !== null ? () => getDocument(id) : null, null, [id]);
  const versions = useApi<DocumentVersion[]>(id !== null ? () => listDocumentVersions(id) : null, [], [id]);
  const d = meta.data ?? doc;
  const current = d ? d.current_version : 1;
  const rows = [...versions.data].sort((a, b) => b.version - a.version);

  return (
    <Sheet
      open={doc !== null}
      onClose={onClose}
      width={560}
      eyebrow={<span className="inline-flex items-center gap-1.5"><History className="h-3.5 w-3.5" /> Version history</span>}
      title={d?.filename ?? "Document"}
      description={d ? <>{humanize(d.doc_class)} · v{current} current · opening this panel is logged as a view</> : undefined}
      footer={
        d ? (
          <div className="flex items-center justify-between gap-2">
            <span className="text-[12px] text-muted">Downloads are logged with your name.</span>
            <Button
              variant="secondary"
              onClick={() => downloadDocument(d.id, d.filename).catch((err) => toast(errMessage(err), "error"))}
            >
              <Download className="h-3.5 w-3.5" /> Download v{current}
            </Button>
          </div>
        ) : null
      }
    >
      {meta.error ? <InlineError message={meta.error} onRetry={meta.refresh} className="mb-4" /> : null}
      {d ? (
        <dl className="mb-6 grid grid-cols-2 gap-x-6 gap-y-3 rounded-md border border-line bg-surface p-4 text-[13px]">
          <div>
            <dt className="text-[11px] text-muted">Sensitivity</dt>
            <dd className="mt-0.5 text-fg">{d.sensitivity ? SENSITIVITY[d.sensitivity]?.label ?? `S${d.sensitivity}` : "—"}</dd>
          </div>
          <div>
            <dt className="text-[11px] text-muted">Status</dt>
            <dd className="mt-0.5 text-fg">{d.is_executed ? "Executed" : "Not executed"}{d.class_confirmed === false ? " · class proposed" : ""}</dd>
          </div>
          <div>
            <dt className="text-[11px] text-muted">Uploaded by</dt>
            <dd className="mt-0.5 text-fg">{d.uploaded_by ? titleCase(d.uploaded_by) : "—"}</dd>
          </div>
          <div>
            <dt className="text-[11px] text-muted">Size</dt>
            <dd className="num mt-0.5 font-mono text-fg">{formatBytes(d.byte_size) || "—"}</dd>
          </div>
        </dl>
      ) : null}

      <h3 className="mb-2 text-[12px] font-medium text-fg-2">Versions</h3>
      {versions.unavailable ? (
        <Unavailable what="Version history" />
      ) : versions.loading ? (
        <div className="rounded-md border border-line"><SkeletonRows rows={3} /></div>
      ) : versions.error ? (
        <InlineError message={versions.error} onRetry={versions.refresh} />
      ) : rows.length === 0 ? (
        <EmptyState compact title="Only the original upload" description="Uploading a file with the same name and class adds a new version here." />
      ) : (
        <ol className="relative ml-1 border-l border-line pl-5">
          {rows.map((v) => (
            <li key={v.version} className="relative pb-5 last:pb-0">
              <span className={cx("absolute -left-[25.5px] top-1 h-2.5 w-2.5 rounded-full border-2", v.version === current ? "border-accent bg-accent" : "border-line-strong bg-surface")} />
              <div className="flex items-center gap-2">
                <span className="font-mono text-[13px] font-medium text-fg">v{v.version}</span>
                {v.version === current ? <Badge tone="accent">Current</Badge> : null}
                <span className="num ml-auto font-mono text-[11px] text-muted">{formatDateTime(v.uploaded_at)}</span>
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-muted">
                <span>{titleCase(v.uploaded_by)}</span>
                <span className="num font-mono">{formatBytes(v.byte_size)}</span>
                <Tip label={<span className="font-mono">{v.sha256}</span>}>
                  <span tabIndex={0} className="font-mono outline-none focus-visible:text-fg">sha256 {v.sha256.slice(0, 12)}…</span>
                </Tip>
              </div>
            </li>
          ))}
        </ol>
      )}
    </Sheet>
  );
}

/* ---------------------------------- Upload --------------------------------- */

function UploadSheet({ dealId, open, onClose, onUploaded }: { dealId: number; open: boolean; onClose: () => void; onUploaded: () => void }) {
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [docClass, setDocClass] = useState<string>(DOC_CLASSES[0]);
  const [upsi, setUpsi] = useState(false);
  const [sensitivity, setSensitivity] = useState("2");
  const [drag, setDrag] = useState(false);
  const [pct, setPct] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const effective = upsi ? "4" : sensitivity;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setPct(0);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("doc_class", docClass);
      form.append("contains_upsi", String(upsi));
      form.append("sensitivity", effective);
      await uploadDocumentWithProgress(dealId, form, setPct);
      toast(`${file.name} uploaded`);
      setFile(null);
      setUpsi(false);
      setSensitivity("2");
      onUploaded();
      onClose();
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setPct(null);
    }
  }

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Upload a document"
      description="Files are hashed (SHA-256) on upload. A file with the same name adds a new version."
      footer={
        <div className="flex items-center justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" form="doc-upload" loading={pct !== null} disabled={!file}>
            {pct !== null ? `Uploading ${pct}%` : "Upload document"}
          </Button>
        </div>
      }
    >
      <form id="doc-upload" onSubmit={submit} className="space-y-5">
        <label
          onDragOver={(e) => {
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDrag(false);
            const f = e.dataTransfer.files?.[0];
            if (f) setFile(f);
          }}
          className={cx(
            "flex cursor-pointer flex-col items-center gap-1.5 rounded-md border border-dashed px-4 py-8 text-center transition-colors focus-within:ring-2 focus-within:ring-accent/40",
            drag ? "border-accent bg-accent-soft" : "border-line-strong bg-canvas hover:bg-control-hover",
          )}
        >
          <Upload className="h-4 w-4 text-muted" />
          <span className="max-w-full truncate text-[13px] font-medium text-fg">{file ? file.name : "Drop a file, or browse"}</span>
          <span className="text-[12px] text-muted">{file ? formatBytes(file.size) : "PDF, XLSX, DOCX"}</span>
          <input type="file" className="sr-only" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>

        {pct !== null ? (
          <div role="progressbar" aria-label="Upload progress" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} className="h-1 overflow-hidden rounded-full bg-control-active">
            <div className="h-full bg-accent transition-[width]" style={{ width: `${pct}%` }} />
          </div>
        ) : null}

        <div>
          <label htmlFor="doc-class" className={labelCls}>Document class</label>
          <select id="doc-class" value={docClass} onChange={(e) => setDocClass(e.target.value)} className={selectCls}>
            {DOC_CLASSES.map((c) => (
              <option key={c} value={c}>{humanize(c)}</option>
            ))}
          </select>
          <p className="mt-1.5 text-[12px] text-muted">Recorded as a proposal until someone confirms it — or run the classifier afterwards.</p>
        </div>

        <div>
          <span className={labelCls}>Sensitivity</span>
          <div className={cx(upsi && "pointer-events-none opacity-60")} aria-disabled={upsi}>
            <Segmented
              label="Sensitivity"
              value={effective}
              onChange={setSensitivity}
              options={[1, 2, 3, 4].map((n) => ({ value: String(n), label: `S${n}`, title: SENSITIVITY[n].label }))}
            />
          </div>
          <p className="mt-1.5 text-[12px] text-muted">
            {SENSITIVITY[Number(effective)].label} — {upsi ? "UPSI is always S4." : SENSITIVITY[Number(effective)].hint}
          </p>
        </div>

        <label className="flex items-start gap-2.5 text-[13px] text-fg">
          <input type="checkbox" className="mt-[3px]" checked={upsi} onChange={(e) => setUpsi(e.target.checked)} />
          <span>
            Contains UPSI
            <span className="block text-[12px] text-muted">Unpublished price-sensitive information. Forces sensitivity S4; every view and download is logged.</span>
          </span>
        </label>
        {error ? <Notice tone="error">{error}</Notice> : null}
      </form>
    </Sheet>
  );
}

/* ----------------------------------- Tab ----------------------------------- */

export function DocumentsTab({ dealId }: { dealId: number }) {
  const toast = useToast();
  const allowed = useCan()("work");
  const docs = useApi<DealDocument[]>(() => listDocuments(dealId), [], [dealId], { live: dealEvents(dealId, ["document"]) });
  const { run, busy } = useRunAgent(dealId);
  const [uploading, setUploading] = useState(false);
  const [versionsOf, setVersionsOf] = useState<DealDocument | null>(null);
  const [toggling, setToggling] = useState<number | null>(null);

  async function download(d: DealDocument) {
    try {
      await downloadDocument(d.id, d.filename ?? `document-${d.id}`);
    } catch (err) {
      toast(errMessage(err), "error");
    }
  }

  async function toggleExecuted(d: DealDocument) {
    setToggling(d.id);
    try {
      await patchDocument(d.id, { is_executed: !d.is_executed });
      toast(d.is_executed ? `${d.filename} marked not executed` : `${d.filename} marked executed`);
      docs.refresh();
    } catch (err) {
      toast(errMessage(err), "error");
    } finally {
      setToggling(null);
    }
  }

  const uploadButton = (
    <Permit allow={allowed} why={WHO_CAN.work}>
      <Button size="sm" variant="secondary" onClick={() => setUploading(true)}>
        <Upload className="h-3.5 w-3.5" /> Upload
      </Button>
    </Permit>
  );

  return (
    <>
      <Section
        title={
          <span className="flex items-center gap-2">
            Documents {docs.data.length ? <span className="num font-mono text-[11px] font-normal text-muted">{docs.data.length}</span> : null}
          </span>
        }
        flush
        aside={uploadButton}
      >
        {docs.unavailable ? (
          <div className="p-4"><Unavailable what="Documents" /></div>
        ) : docs.loading ? (
          <SkeletonRows rows={4} height={56} />
        ) : docs.error ? (
          <div className="p-4"><InlineError message={docs.error} onRetry={docs.refresh} /></div>
        ) : docs.data.length === 0 ? (
          <EmptyState
            compact
            title="No documents yet"
            description="Upload the engagement letter, term sheet or audited financials to get started."
            action={allowed ? <Button size="sm" variant="secondary" onClick={() => setUploading(true)}>Upload the first document</Button> : undefined}
          />
        ) : (
          <ul>
            {docs.data.map((d) => {
              const v = d.current_version;
              return (
                <li key={d.id} className="group flex min-h-14 items-center gap-3 border-b border-line-subtle px-4 py-2.5 last:border-0">
                  <FileText className="h-4 w-4 shrink-0 text-muted" />
                  <div className="min-w-0 flex-1">
                    <div className="flex min-w-0 items-center gap-2">
                      <span className="truncate text-[13px] font-medium text-fg">{d.filename ?? `Document ${d.id}`}</span>
                      <button
                        onClick={() => setVersionsOf(d)}
                        className="shrink-0 rounded-xs border border-line px-1 font-mono text-[11px] text-muted outline-none hover:border-line-strong hover:text-fg focus-visible:ring-2 focus-visible:ring-accent/50"
                        aria-label={`Version history for ${d.filename}`}
                      >
                        v{v}
                      </button>
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted">
                      <span className="text-fg-2">{humanize(d.doc_class)}</span>
                      {d.class_confirmed === false ? (
                        <ConfirmClass doc={d} onDone={docs.refresh} allowed={allowed} />
                      ) : d.class_confirmed ? (
                        <Tip label="Class confirmed by a person">
                          <span tabIndex={0} className="inline-flex items-center gap-0.5 text-success outline-none">
                            <BadgeCheck className="h-3 w-3" /> Confirmed
                          </span>
                        </Tip>
                      ) : null}
                      <span aria-hidden>·</span>
                      <span className="num font-mono">{formatBytes(d.byte_size)}</span>
                      <span>· {titleCase(d.uploaded_by)}</span>
                      <span className="num" title={formatDateTime(d.uploaded_at)}>· {shortDate(d.uploaded_at)}</span>
                    </div>
                  </div>

                  <div className="flex shrink-0 items-center gap-1.5">
                    {d.contains_upsi ? (
                      <Tip label="Unpublished price-sensitive information · views and downloads are logged">
                        <span tabIndex={0} className="outline-none">
                          <Badge tone="danger"><Lock className="h-3 w-3" /> UPSI</Badge>
                        </span>
                      </Tip>
                    ) : null}
                    {d.sensitivity ? (
                      <Tip label={SENSITIVITY[d.sensitivity]?.label ?? `Sensitivity ${d.sensitivity}`}>
                        <span tabIndex={0} className="outline-none">
                          <Badge tone={sensTone(d.sensitivity)} mono>S{d.sensitivity}</Badge>
                        </span>
                      </Tip>
                    ) : null}
                    <Permit allow={allowed} why={WHO_CAN.work}>
                      <button
                        onClick={() => toggleExecuted(d)}
                        disabled={toggling === d.id}
                        aria-pressed={!!d.is_executed}
                        className={cx(
                          "inline-flex h-6 items-center gap-1 rounded-full border px-2 text-[11px] font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent/50 disabled:opacity-50",
                          d.is_executed
                            ? "border-success-border bg-success-soft text-success hover:opacity-85"
                            : "border-dashed border-line-strong text-muted hover:border-line-strong hover:bg-control-hover hover:text-fg",
                        )}
                      >
                        <FileSignature className="h-3 w-3" /> {d.is_executed ? "Executed" : "Not executed"}
                      </button>
                    </Permit>
                    <Tip label="Download · logged">
                      <IconButton label={`Download ${d.filename ?? d.id}`} onClick={() => download(d)}>
                        <Download className="h-4 w-4" />
                      </IconButton>
                    </Tip>
                    <Menu.Root>
                      <Menu.Trigger asChild>
                        <IconButton label={`More actions for ${d.filename}`} className="data-[state=open]:bg-control-hover">
                          <MoreHorizontal className="h-4 w-4" />
                        </IconButton>
                      </Menu.Trigger>
                      <Menu.Portal>
                        <Menu.Content align="end" sideOffset={4} className="a-pop z-50 w-60 rounded-md bg-raised p-1 shadow-overlay">
                          <Menu.Item className={menuItem} onSelect={() => setVersionsOf(d)}>
                            <History className="h-4 w-4 text-muted" /> Version history
                          </Menu.Item>
                          <Menu.Separator className="my-1 h-px bg-line-subtle" />
                          <Menu.Label className="px-2 pb-1 pt-1.5 text-[11px] font-medium text-muted">
                            Run an agent {allowed ? null : "· analysts and dealmakers"}
                          </Menu.Label>
                          <Menu.Item
                            className={menuItem}
                            disabled={!allowed || busy !== null}
                            onSelect={() => void run("classify_document", { document_id: d.id }, `cls-${d.id}`)}
                          >
                            <Sparkles className="h-4 w-4 text-accent" /> Classify document
                          </Menu.Item>
                          <Menu.Item
                            className={menuItem}
                            disabled={!allowed || busy !== null}
                            onSelect={() => void run("extract_financials", { document_id: d.id }, `ext-${d.id}`)}
                          >
                            <ScanText className="h-4 w-4 text-accent" /> Extract financials
                          </Menu.Item>
                        </Menu.Content>
                      </Menu.Portal>
                    </Menu.Root>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </Section>
      <p className="mt-2.5 text-[12px] text-muted">Every view and download of a document is written to its access log. Listing documents is not.</p>

      <UploadSheet dealId={dealId} open={uploading} onClose={() => setUploading(false)} onUploaded={docs.refresh} />
      <VersionsSheet doc={versionsOf} onClose={() => setVersionsOf(null)} />
    </>
  );
}

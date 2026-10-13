"use client";

import { ArrowLeft, Check, CircleAlert, Clock, Coffee, RotateCw } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { cx, timeAgo } from "@/shared/lib/format";
import { errMessage } from "@/shared/lib/useApi";
import { Badge, Button, Spinner } from "@/shared/ui/primitives";
import { EmptyState, Notice } from "@/shared/ui/States";
import { useEvents } from "@/shared/api/events";
import type { IntakeWizard } from "../hooks";
import type { Intake, IntakeFile } from "../types";
import { ProgressBar } from "./bits";

type NodeState = "done" | "current" | "pending" | "failed";
const TIMELINE = ["Uploaded", "Reading", "Indexed", "Extracting fields"] as const;

/** Map one file's stage + the intake's overall progress onto the 4-step timeline. */
function fileTimeline(f: IntakeFile, intake: Intake): NodeState[] {
  const ext = intake.extraction.status;
  const extracting: NodeState =
    intake.progress.stage === "ready" || ext === "done" || intake.status === "review"
      ? "done"
      : ext === "failed" || intake.progress.stage === "failed"
        ? "failed"
        : intake.progress.stage === "extracting" || ext === "running"
          ? "current"
          : "pending";
  switch (f.stage) {
    case "uploaded": // waiting its turn in the indexing queue
      return ["done", "pending", "pending", "pending"];
    case "parsing":
      return ["done", "current", "pending", "pending"];
    case "failed":
      return ["done", "failed", "pending", "pending"];
    case "indexed":
      return ["done", "done", "done", extracting];
  }
}

function Node({ state, label, detail }: { state: NodeState; label: string; detail?: string }) {
  return (
    <li className="flex min-w-0 flex-1 items-center gap-2">
      <span
        aria-hidden
        className={cx(
          "inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full border",
          state === "done" && "border-success-border bg-success-soft text-success",
          state === "current" && "border-accent-border bg-accent-soft text-accent",
          state === "failed" && "border-danger-border bg-danger-soft text-danger",
          state === "pending" && "border-line-strong text-faint",
        )}
      >
        {state === "done" ? <Check className="h-2.5 w-2.5" strokeWidth={3} /> : state === "current" ? <Spinner className="h-2.5 w-2.5" /> : state === "failed" ? <CircleAlert className="h-2.5 w-2.5" /> : null}
      </span>
      <span className={cx("truncate text-[12px]", state === "pending" ? "text-muted" : state === "failed" ? "text-danger" : "text-fg-2")}>
        {label}
        {detail ? <span className="text-muted"> · {detail}</span> : null}
        <span className="sr-only"> — {state}</span>
      </span>
    </li>
  );
}

function FileTimeline({ f, intake }: { f: IntakeFile; intake: Intake }) {
  const nodes = fileTimeline(f, intake);
  const pdf = f.filename.toLowerCase().endsWith(".pdf");
  const reading =
    f.stage === "uploaded" ? "queued" : f.stage === "parsing" ? (f.ocr_used ? "OCR" : pdf ? "Docling" : undefined) : f.page_count ? `${f.page_count} pp` : undefined;
  const indexed = f.stage === "indexed" ? `${f.chunk_count} passages` : undefined;
  return (
    <li className="px-4 py-3">
      <div className="flex items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-[13px] text-fg" title={f.filename}>{f.filename}</span>
        {f.ocr_used ? <Badge tone="info">OCR</Badge> : null}
      </div>
      <ol className="mt-2 flex flex-wrap gap-x-3 gap-y-1.5" aria-label={`Progress for ${f.filename}`}>
        {TIMELINE.map((label, i) => (
          <Node key={label} state={nodes[i]} label={label} detail={i === 1 ? reading : i === 2 ? indexed : undefined} />
        ))}
      </ol>
      {f.error ? <p className="mt-1.5 text-[12px] text-danger">{f.error}</p> : null}
      {f.warnings.length ? <p className="mt-1.5 text-[12px] text-warning">{f.warnings.join(" · ")}</p> : null}
    </li>
  );
}

/** Ticks once a second so "running for 3m" stays honest. */
function useNow(on: boolean) {
  const [, set] = useState(0);
  useEffect(() => {
    if (!on) return;
    const t = setInterval(() => set((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [on]);
}

export function ProcessingStep({ w }: { w: IntakeWizard }) {
  const intake = w.state.intake;
  const { connection } = useEvents();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const failed = intake ? intake.extraction.status === "failed" || intake.progress.stage === "failed" : false;
  useNow(Boolean(intake) && !failed);
  if (!intake) return null;

  const p = intake.progress;
  const ext = intake.extraction;
  const allIndexed = intake.files.length > 0 && intake.files.every((f) => f.stage === "indexed" || f.stage === "failed");
  const idle = !failed && ext.status === "idle" && p.stage !== "indexing" && p.stage !== "extracting" && (allIndexed || intake.files.length === 0);
  const since = ext.started_at ?? intake.created_at;

  async function retry() {
    setBusy(true);
    setError(null);
    try {
      await w.extract();
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="min-w-0 space-y-4">
        <div className="rounded-md border border-line bg-surface p-5 shadow-card">
          <div role="status" aria-live="polite" aria-atomic="true">
            <div className="flex items-baseline gap-3">
              <span className="num font-serif text-[28px] leading-none text-fg">{Math.round(p.percent)}%</span>
              <span className="min-w-0 flex-1 truncate text-[13px] text-fg-2">{p.message || (failed ? "Extraction stopped" : "Working…")}</span>
            </div>
            <span className="sr-only">
              {p.files_indexed} of {p.files_total} files indexed, {p.groups_done} of {p.groups_total} field groups extracted.
            </span>
          </div>
          <ProgressBar className="mt-4" pct={p.percent} label="Overall extraction progress" tone={failed ? "danger" : p.stage === "ready" ? "success" : "accent"} />
          <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-[12px] text-muted">
            <div><dt className="inline">Files indexed </dt><dd className="num inline font-medium text-fg-2">{p.files_indexed}/{p.files_total}</dd></div>
            {p.files_failed ? <div><dt className="inline">Unreadable </dt><dd className="num inline font-medium text-danger">{p.files_failed}</dd></div> : null}
            <div><dt className="inline">Field groups </dt><dd className="num inline font-medium text-fg-2">{p.groups_done}/{p.groups_total || "—"}</dd></div>
            {!failed ? <div className="flex items-center gap-1"><Clock className="h-3 w-3" /> <span>started {timeAgo(since)}</span></div> : null}
            {ext.attempts > 1 ? <div>Attempt <span className="num">{ext.attempts}</span></div> : null}
          </dl>
        </div>

        {failed ? (
          <Notice
            tone="error"
            title="Extraction didn’t finish"
            action={
              <Button size="sm" variant="secondary" onClick={retry} loading={busy}>
                <RotateCw className="h-3 w-3" /> Retry
              </Button>
            }
          >
            {ext.error ?? "The extraction run failed. Your documents are safe — try again."}
          </Notice>
        ) : idle ? (
          <Notice
            tone="info"
            title={intake.files.length ? "Documents are ready" : "No documents yet"}
            action={
              <Button size="sm" variant="secondary" onClick={retry} loading={busy}>
                Start extraction
              </Button>
            }
          >
            {intake.files.length
              ? "Extraction normally starts by itself once every file is indexed."
              : "Aura can still look the company up from the name or CIN you gave."}
          </Notice>
        ) : null}
        {error ? <Notice tone="error">{error}</Notice> : null}
        {ext.warnings.length ? <Notice tone="warn">{ext.warnings.join(" · ")}</Notice> : null}

        {intake.files.length ? (
          <div className="rounded-md border border-line bg-surface shadow-card">
            <div className="flex h-10 items-center border-b border-line-subtle px-4">
              <h3 className="text-[13px] font-medium text-fg">Documents</h3>
            </div>
            <ul className="divide-y divide-line-subtle">
              {intake.files.map((f) => (
                <FileTimeline key={f.id} f={f} intake={intake} />
              ))}
            </ul>
          </div>
        ) : (
          <EmptyState compact title="Working from what you told us" description="No documents in this intake — extraction uses the company name and CIN only." />
        )}
      </div>

      <aside className="space-y-4">
        <div className="rounded-md border border-line bg-well p-4">
          <div className="flex items-center gap-2 text-[13px] font-medium text-fg">
            <Coffee className="h-4 w-4 text-muted" /> This can take a few minutes
          </div>
          <p className="mt-1.5 text-[12px] leading-relaxed text-muted">
            Aura reads every page, runs OCR on scans and extracts each field group on this server’s CPU. You don’t need to wait here — the draft keeps going and waits for you under
            {" "}<span className="text-fg-2">Drafts</span> on the Deals page.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Link
              href="/deals"
              className="inline-flex h-7 items-center rounded-sm border border-line bg-control px-2.5 text-[12px] font-medium text-fg shadow-card hover:bg-control-hover"
            >
              Leave and come back
            </Link>
            <Button size="sm" variant="ghost" onClick={() => w.dispatch({ type: "go", view: "start" })}>
              <ArrowLeft className="h-3 w-3" /> Add documents
            </Button>
          </div>
        </div>
        <p className="text-[12px] text-muted">
          {connection === "live" ? "Live — updates arrive as each step finishes." : "Checking for updates every few seconds."} You’ll move to review automatically.
        </p>
      </aside>
    </div>
  );
}

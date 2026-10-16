"use client";

import * as Dialog from "@radix-ui/react-dialog";
import * as Menu from "@radix-ui/react-dropdown-menu";
import { Braces, ChevronDown, Download, FileArchive, FileSpreadsheet, FileText, FileType2, Lock, SlidersHorizontal } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { WHO_CAN } from "@/features/auth/roles";
import { useCan } from "@/features/auth/useCan";
import { ApiError } from "@/shared/api/client";
import { cx } from "@/shared/lib/format";
import { errMessage } from "@/shared/lib/useApi";
import { Button, Spinner } from "@/shared/ui/primitives";
import { Permit } from "@/shared/ui/Permit";
import { useToast } from "@/shared/ui/toast";
import {
  ALL_SECTIONS,
  DEAL_FORMATS,
  EXPORT_SECTIONS,
  exportDeal,
  exportDealList,
  fileSize,
  rememberSections,
  rememberedSections,
  type DealExportFormat,
  type DealListFilters,
  type ExportSectionId,
} from "../export";

const menuItem =
  "flex min-h-8 cursor-default items-center gap-2.5 rounded-xs px-2 py-1.5 text-[13px] text-fg outline-none data-[disabled]:opacity-45 data-[highlighted]:bg-control-hover";

const FORMAT_ICON: Record<DealExportFormat, React.ReactNode> = {
  pdf: <FileText className="h-4 w-4 text-muted" />,
  docx: <FileType2 className="h-4 w-4 text-muted" />,
  xlsx: <FileSpreadsheet className="h-4 w-4 text-muted" />,
  json: <Braces className="h-4 w-4 text-muted" />,
  zip: <FileArchive className="h-4 w-4 text-muted" />,
};
const FORMAT_SHORT: Record<DealExportFormat, string> = { pdf: "PDF", docx: "Word", xlsx: "Excel", json: "JSON", zip: "ZIP" };

/** A failed export, said the way the person can act on it. */
function describe(err: unknown): { message: string; retryAfter: number | null } {
  if (err instanceof ApiError) {
    if (err.status === 403) return { message: `${err.message} ${WHO_CAN.export}`.trim(), retryAfter: null };
    if (err.status === 404) return { message: "This deal isn’t available to you any more — you may have been taken off its wall.", retryAfter: null };
    if (err.status === 429) return { message: "Too many exports in the last minute.", retryAfter: err.retryAfter ?? 60 };
  }
  return { message: errMessage(err), retryAfter: null };
}

/** Seconds left until `deadline` (ms epoch), re-rendering every second; 0 once past. */
function useCountdown(deadline: number | null) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!deadline) return;
    setNow(Date.now());
    const t = setInterval(() => {
      setNow(Date.now());
      if (Date.now() >= deadline) clearInterval(t);
    }, 250);
    return () => clearInterval(t);
  }, [deadline]);
  return deadline ? Math.max(0, Math.ceil((deadline - now) / 1000)) : 0;
}

/* ------------------------------- Deal export ------------------------------- */

export function DealExportMenu({ dealId, dealName, externalId }: { dealId: number; dealName: string; externalId: string }) {
  const allowed = useCan()("export");
  const [format, setFormat] = useState<DealExportFormat | null>(null);

  const trigger = (
    <Button size="lg" variant="secondary" className="data-[state=open]:bg-control-hover" aria-label="Export deal">
      <Download className="h-3.5 w-3.5" /> Export <ChevronDown className="h-3.5 w-3.5 text-muted" />
    </Button>
  );
  if (!allowed) {
    return (
      <Permit allow={false} why={WHO_CAN.export} side="bottom">
        {trigger}
      </Permit>
    );
  }
  return (
    <>
      <Menu.Root>
        <Menu.Trigger asChild>{trigger}</Menu.Trigger>
        <Menu.Portal>
          <Menu.Content align="end" sideOffset={6} className="a-pop z-50 w-64 rounded-md bg-raised p-1 shadow-overlay">
            <Menu.Label className="px-2 pb-1 pt-1.5 text-[11px] font-medium text-muted">Export {externalId}</Menu.Label>
            {DEAL_FORMATS.map((f) => (
              <Menu.Item key={f.id} className={menuItem} onSelect={() => setFormat(f.id)}>
                {FORMAT_ICON[f.id]}
                <span className="flex min-w-0 flex-col">
                  <span>{f.label}</span>
                  <span className="text-[11.5px] text-muted">{f.hint}</span>
                </span>
              </Menu.Item>
            ))}
            <Menu.Separator className="my-1 h-px bg-line-subtle" />
            <p className="flex items-start gap-1.5 px-2 pb-1.5 pt-0.5 text-[11.5px] leading-snug text-muted">
              <Lock className="mt-0.5 h-3 w-3 shrink-0" /> Every export is recorded in the audit trail.
            </p>
          </Menu.Content>
        </Menu.Portal>
      </Menu.Root>
      <ExportDialog
        dealId={dealId}
        dealName={dealName}
        format={format}
        onFormat={setFormat}
        onClose={() => setFormat(null)}
      />
    </>
  );
}

function ExportDialog({
  dealId,
  dealName,
  format,
  onFormat,
  onClose,
}: {
  dealId: number;
  dealName: string;
  format: DealExportFormat | null;
  onFormat: (f: DealExportFormat) => void;
  onClose: () => void;
}) {
  const toast = useToast();
  const open = format !== null;
  const [sections, setSections] = useState<ExportSectionId[]>(ALL_SECTIONS);
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<{ message: string; retryAfter: number | null; until: number | null } | null>(null);
  const abort = useRef<AbortController | null>(null);
  const wait = useCountdown(error?.until ?? null);

  useEffect(() => {
    if (open) {
      setSections(rememberedSections());
      setError(null);
    }
  }, [open]);

  useEffect(() => {
    if (!busy) return;
    setElapsed(0);
    const t = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [busy]);

  const toggle = (id: ExportSectionId) =>
    setSections((cur) => (cur.includes(id) ? cur.filter((s) => s !== id) : ALL_SECTIONS.filter((s) => s === id || cur.includes(s))));
  const chosen = sections.filter((s) => s !== "summary").length;

  async function run() {
    if (!format) return;
    setBusy(true);
    setError(null);
    rememberSections(sections);
    abort.current = new AbortController();
    try {
      const file = await exportDeal(dealId, format, sections, abort.current.signal);
      toast(`Downloaded ${file.filename} · ${fileSize(file.size)}`);
      onClose();
    } catch (err) {
      if (!abort.current?.signal.aborted) {
        const d = describe(err);
        setError({ ...d, until: d.retryAfter ? Date.now() + d.retryAfter * 1000 : null });
      }
    } finally {
      setBusy(false);
      abort.current = null;
    }
  }

  function close() {
    abort.current?.abort();
    onClose();
  }

  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && close()}>
      <Dialog.Portal>
        <Dialog.Overlay className="a-scrim fixed inset-0 z-50 bg-[var(--scrim)]" />
        <Dialog.Content
          className="a-pop fixed left-1/2 top-[12vh] z-50 flex max-h-[80vh] w-[min(560px,calc(100vw-32px))] -translate-x-1/2 flex-col overflow-hidden rounded-lg bg-raised shadow-overlay outline-none"
          onOpenAutoFocus={(e) => {
            e.preventDefault();
            (document.getElementById("export-go") as HTMLButtonElement | null)?.focus();
          }}
        >
          <div className="border-b border-line-subtle px-5 pb-4 pt-4">
            <Dialog.Title className="font-serif text-[20px] leading-tight text-fg">Export {dealName}</Dialog.Title>
            <Dialog.Description className="mt-1 text-[13px] text-muted">
              Only what you can see on this deal is included. Contact emails are masked unless you are a dealmaker or compliance.
            </Dialog.Description>
          </div>

          <div className="scroll min-h-0 flex-1 overflow-y-auto px-5 py-4">
            <fieldset>
              <legend className="mb-2 text-[12px] font-medium text-fg-2">Format</legend>
              <div role="radiogroup" aria-label="Format" className="grid grid-cols-5 gap-1.5">
                {DEAL_FORMATS.map((f) => {
                  const on = f.id === format;
                  return (
                    <button
                      key={f.id}
                      type="button"
                      role="radio"
                      aria-checked={on}
                      title={`${f.label} — ${f.hint}`}
                      disabled={busy}
                      onClick={() => onFormat(f.id)}
                      className={cx(
                        "flex h-14 flex-col items-center justify-center gap-1 rounded-sm border text-[12px] font-medium outline-none transition-colors duration-[var(--dur-1)] focus-visible:ring-2 focus-visible:ring-accent/50",
                        on ? "border-accent-border bg-accent-soft text-fg" : "border-line text-fg-2 hover:bg-control-hover",
                      )}
                    >
                      {FORMAT_ICON[f.id]}
                      {FORMAT_SHORT[f.id]}
                    </button>
                  );
                })}
              </div>
            </fieldset>

            <fieldset className="mt-5">
              <div className="mb-2 flex items-center gap-2">
                <legend className="text-[12px] font-medium text-fg-2">Sections</legend>
                <span className="num font-mono text-[11px] text-muted">{chosen + 1} of {ALL_SECTIONS.length}</span>
                <span className="ml-auto flex gap-1">
                  <button type="button" className="h-6 rounded-xs px-1.5 text-[12px] text-muted hover:bg-control-hover hover:text-fg" onClick={() => setSections(ALL_SECTIONS)} disabled={busy}>
                    All
                  </button>
                  <button type="button" className="h-6 rounded-xs px-1.5 text-[12px] text-muted hover:bg-control-hover hover:text-fg" onClick={() => setSections(["summary"])} disabled={busy}>
                    Summary only
                  </button>
                </span>
              </div>
              <ul className="grid grid-cols-1 gap-x-4 gap-y-0.5 sm:grid-cols-2">
                {EXPORT_SECTIONS.map((s) => {
                  const locked = "locked" in s && s.locked;
                  const checked = locked || sections.includes(s.id);
                  return (
                    <li key={s.id}>
                      <label className={cx("flex cursor-pointer items-start gap-2.5 rounded-sm px-1.5 py-1.5 hover:bg-control-hover", locked && "cursor-default opacity-80 hover:bg-transparent")}>
                        <input
                          type="checkbox"
                          className="mt-[3px] h-3.5 w-3.5 shrink-0 accent-[var(--accent)]"
                          checked={checked}
                          disabled={locked || busy}
                          onChange={() => toggle(s.id)}
                        />
                        <span className="min-w-0">
                          <span className="block text-[13px] text-fg">{s.label}</span>
                          <span className="block text-[11.5px] text-muted">{locked ? "Always included" : s.hint}</span>
                        </span>
                      </label>
                    </li>
                  );
                })}
              </ul>
            </fieldset>

            {error ? (
              <div role="alert" className="mt-4 rounded-sm border border-danger-border bg-danger-soft px-3 py-2 text-[12.5px] text-danger">
                {error.message}
                {error.retryAfter ? <span> {wait > 0 ? `Try again in ${wait}s.` : "You can try again now."}</span> : null}
              </div>
            ) : null}
          </div>

          <div className="flex items-center gap-2 border-t border-line-subtle bg-surface px-5 py-3.5 dark:bg-raised">
            <p className="min-w-0 flex-1 truncate text-[12px] text-muted" aria-live="polite">
              {busy ? (
                <span className="inline-flex items-center gap-2 text-fg-2">
                  <Spinner /> Preparing {format ? FORMAT_SHORT[format] : ""}… <span className="num font-mono">{elapsed}s</span>
                </span>
              ) : (
                "Recorded in the audit trail with the file’s SHA-256."
              )}
            </p>
            <Button variant="ghost" size="sm" onClick={close}>
              {busy ? "Cancel" : "Close"}
            </Button>
            <Button id="export-go" size="sm" loading={busy} disabled={wait > 0} onClick={run}>
              <Download className="h-3.5 w-3.5" /> Export {format ? FORMAT_SHORT[format] : ""}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/* ------------------------------ Deals list export ------------------------------ */

export function DealListExportMenu({ filters, count, filtered }: { filters: DealListFilters; count: number; filtered: boolean }) {
  const allowed = useCan()("export");
  const toast = useToast();
  const [busy, setBusy] = useState<"csv" | "xlsx" | null>(null);

  async function run(format: "csv" | "xlsx") {
    setBusy(format);
    try {
      const file = await exportDealList(format, filters);
      toast(`Downloaded ${file.filename} · ${fileSize(file.size)}`);
    } catch (err) {
      const { message, retryAfter } = describe(err);
      toast(retryAfter ? `${message} Try again in ${retryAfter}s.` : message, "error");
    } finally {
      setBusy(null);
    }
  }

  const trigger = (
    <button
      type="button"
      aria-label="Export deals"
      className="inline-flex h-7 items-center gap-1.5 rounded-sm border border-line px-2 text-[12px] text-fg-2 transition-colors hover:bg-control-hover data-[state=open]:bg-control-hover disabled:opacity-45"
      disabled={busy !== null}
    >
      {busy ? <Spinner className="h-3 w-3" /> : <Download className="h-3.5 w-3.5" />} Export
    </button>
  );
  if (!allowed) {
    return (
      <Permit allow={false} why={WHO_CAN.export} side="bottom">
        {trigger}
      </Permit>
    );
  }
  return (
    <Menu.Root>
      <Menu.Trigger asChild>{trigger}</Menu.Trigger>
      <Menu.Portal>
        <Menu.Content align="end" sideOffset={6} className="a-pop z-50 w-60 rounded-md bg-raised p-1 shadow-overlay">
          <Menu.Label className="px-2 pb-1 pt-1.5 text-[11px] font-medium text-muted">
            {filtered ? `The ${count} deals matching your filters` : `All ${count} deals you can see`}
          </Menu.Label>
          <Menu.Item className={menuItem} onSelect={() => run("csv")}>
            <FileText className="h-4 w-4 text-muted" /> CSV
            <span className="ml-auto text-[11.5px] text-muted">raw ₹</span>
          </Menu.Item>
          <Menu.Item className={menuItem} onSelect={() => run("xlsx")}>
            <FileSpreadsheet className="h-4 w-4 text-muted" /> Excel
            <span className="ml-auto text-[11.5px] text-muted">₹ formatted</span>
          </Menu.Item>
          <Menu.Separator className="my-1 h-px bg-line-subtle" />
          <p className="flex items-center gap-1.5 px-2 pb-1.5 pt-0.5 text-[11.5px] text-muted">
            <SlidersHorizontal className="h-3 w-3" /> Uses the search and filters above.
          </p>
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  );
}

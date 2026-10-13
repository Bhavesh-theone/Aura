"use client";

import { ChevronLeft, ChevronRight, FileText, Quote, X } from "lucide-react";
import { useEffect, useMemo, useRef } from "react";
import { cx } from "@/shared/lib/format";
import { useApi } from "@/shared/lib/useApi";
import { IconButton } from "@/shared/ui/primitives";
import { EmptyState, InlineError, Skel, Unavailable } from "@/shared/ui/States";
import { getIntakeChunk } from "../api";
import type { IntakeChunk } from "../types";
import { pageLabel } from "./bits";
import type { CitationTarget } from "./FieldRow";

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Locate the quote in the page text: exact first, then whitespace/case-insensitive. */
function findQuote(text: string, quote: string): [number, number] | null {
  const q = quote.trim();
  if (!q || !text) return null;
  const i = text.indexOf(q);
  if (i >= 0) return [i, i + q.length];
  const words = q.split(/\s+/).filter(Boolean).map(escape);
  if (!words.length) return null;
  const m = new RegExp(words.join("\\s+"), "i").exec(text);
  return m ? [m.index, m.index + m[0].length] : null;
}

function Highlighted({ text, quote }: { text: string; quote: string }) {
  const mark = useRef<HTMLElement>(null);
  const span = useMemo(() => findQuote(text, quote), [text, quote]);
  useEffect(() => {
    mark.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [span, text]);
  if (!span) return <>{text}</>;
  return (
    <>
      {text.slice(0, span[0])}
      <mark ref={mark} className="rounded-xs bg-warning-soft px-0.5 text-fg shadow-[0_0_0_1px_var(--warning-border)]">
        {text.slice(span[0], span[1])}
      </mark>
      {text.slice(span[1])}
    </>
  );
}

export function CitationPane({
  intakeId,
  target,
  onIndex,
  onClose,
}: {
  intakeId: number;
  target: CitationTarget | null;
  onIndex: (i: number) => void;
  onClose: () => void;
}) {
  const cite = target ? target.citations[target.index] : null;
  const chunkId = cite?.chunk_id ?? null;
  const chunk = useApi<IntakeChunk | null>(chunkId !== null ? () => getIntakeChunk(intakeId, chunkId) : null, null, [intakeId, chunkId]);
  const heading = useRef<HTMLHeadingElement>(null);
  const key = target ? `${target.key}:${target.index}` : null;

  // Move focus into the pane when a source is opened (keyboard users land on it).
  useEffect(() => {
    if (key) heading.current?.focus({ preventScroll: true });
  }, [key]);

  if (!target || !cite) {
    return (
      <div className="flex h-full flex-col">
        <EmptyState
          compact
          title="Sources appear here"
          description="Select a field’s source chip to see the passage it was read from, highlighted on the page."
        />
      </div>
    );
  }

  const n = target.citations.length;
  const text = chunk.data ? chunk.data.page_text || chunk.data.text : "";
  const where = pageLabel(chunk.data ?? cite);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-start gap-2 border-b border-line-subtle px-4 py-3">
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-medium uppercase tracking-[0.06em] text-muted">Source</p>
          <h3 ref={heading} tabIndex={-1} className="truncate text-[13px] font-medium text-fg outline-none">
            {target.label}
          </h3>
        </div>
        {n > 1 ? (
          <div className="flex items-center gap-0.5" role="group" aria-label="Citations">
            <IconButton size="sm" label="Previous citation" disabled={target.index === 0} onClick={() => onIndex(target.index - 1)}>
              <ChevronLeft className="h-3.5 w-3.5" />
            </IconButton>
            <span className="num px-1 text-[12px] text-muted" aria-live="polite">
              {target.index + 1} / {n}
            </span>
            <IconButton size="sm" label="Next citation" disabled={target.index >= n - 1} onClick={() => onIndex(target.index + 1)}>
              <ChevronRight className="h-3.5 w-3.5" />
            </IconButton>
          </div>
        ) : null}
        <IconButton size="sm" label="Close source" onClick={onClose}>
          <X className="h-3.5 w-3.5" />
        </IconButton>
      </div>

      <div className="flex items-center gap-2 border-b border-line-subtle bg-well px-4 py-2 text-[12px]">
        <FileText className="h-3.5 w-3.5 shrink-0 text-muted" />
        <span className="min-w-0 flex-1 truncate text-fg-2" title={cite.filename}>{chunk.data?.filename ?? cite.filename}</span>
        {where ? <span className="num shrink-0 font-mono text-[11px] text-muted">{where}</span> : null}
      </div>

      <blockquote className="flex gap-2 border-b border-line-subtle px-4 py-2.5 text-[12px] italic leading-relaxed text-fg-2">
        <Quote className="mt-0.5 h-3 w-3 shrink-0 text-muted" aria-hidden />
        <span>{cite.quote}</span>
      </blockquote>

      <div className="scroll min-h-0 flex-1 overflow-y-auto px-4 py-3">
        {chunk.loading ? (
          <div className="space-y-2" aria-busy="true" aria-label="Loading source">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skel key={i} className="h-3" style={{ width: `${70 + ((i * 13) % 30)}%` }} />
            ))}
          </div>
        ) : chunk.unavailable ? (
          <Unavailable what="This passage" />
        ) : chunk.error ? (
          <InlineError message={chunk.error} onRetry={chunk.refresh} />
        ) : (
          <>
            {chunk.data?.heading ? <p className="mb-2 text-[12px] font-medium text-fg">{chunk.data.heading}</p> : null}
            <p className={cx("whitespace-pre-wrap break-words text-[13px] leading-[1.7] text-fg-2")}>
              <Highlighted text={text} quote={cite.quote} />
            </p>
          </>
        )}
      </div>
    </div>
  );
}

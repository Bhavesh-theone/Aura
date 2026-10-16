"use client";

import { FileText, Search, Table2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useApi } from "@/shared/lib/useApi";
import { Badge, Button, IconButton } from "@/shared/ui/primitives";
import { searchDeal } from "../api";
import type { DealSearch, SearchHit } from "../types";
import { EmptyState, InlineError, Section, SkeletonRows, Unavailable } from "./ui";

const DEBOUNCE_MS = 350;
const MIN_CHARS = 2;

/** "p. 3", "pp. 3–4", or nothing when the passage has no page. */
export function pageRef(from: number | null, to: number | null) {
  if (from == null) return "";
  return to == null || to === from ? `p. ${from}` : `pp. ${from}–${to}`;
}

/**
 * The snippet is plain text with matches wrapped in ⟦ … ⟧. Split on the
 * markers and render matches in <mark> — never as HTML.
 */
export function Highlighted({ snippet }: { snippet: string }) {
  const parts = snippet.split(/(⟦[^⟦⟧]*⟧)/);
  return (
    <>
      {parts.map((p, i) =>
        p.startsWith("⟦") && p.endsWith("⟧") ? (
          <mark key={i} className="rounded-xs bg-accent-soft px-0.5 text-fg">{p.slice(1, -1)}</mark>
        ) : (
          <span key={i}>{p.replace(/[⟦⟧]/g, "")}</span>
        ),
      )}
    </>
  );
}

/**
 * Search input for the Documents header. Debounced as you type; Enter
 * searches at once; Escape clears. Reports the settled query upward.
 */
export function DealSearchBox({ onQuery }: { onQuery: (q: string) => void }) {
  const [text, setText] = useState("");
  const ref = useRef<HTMLInputElement>(null);
  const cb = useRef(onQuery);
  cb.current = onQuery;

  useEffect(() => {
    const q = text.trim();
    const t = setTimeout(() => cb.current(q.length >= MIN_CHARS ? q : ""), DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [text]);

  return (
    <form
      role="search"
      onSubmit={(e) => {
        e.preventDefault();
        cb.current(text.trim());
      }}
      className="relative w-56 max-w-full"
    >
      <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted" />
      <input
        ref={ref}
        type="search"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape" && text) {
            e.preventDefault();
            setText("");
            cb.current("");
          }
        }}
        placeholder="Search this deal…"
        aria-label="Search this deal’s documents"
        className="h-7 w-full rounded-sm border border-line bg-control pl-7 pr-7 text-[12px] text-fg outline-none transition-[border-color,box-shadow] duration-[var(--dur-1)] placeholder:text-muted hover:border-line-strong focus:border-accent focus:shadow-[0_0_0_3px_var(--accent-soft)] [&::-webkit-search-cancel-button]:hidden"
      />
      {text ? (
        <IconButton
          type="button"
          size="sm"
          label="Clear search"
          className="absolute right-0.5 top-1/2 h-6 w-6 -translate-y-1/2"
          onClick={() => {
            setText("");
            cb.current("");
            ref.current?.focus();
          }}
        >
          <X className="h-3.5 w-3.5" />
        </IconButton>
      ) : null}
    </form>
  );
}

function Hit({ hit, onOpen }: { hit: SearchHit; onOpen: (hit: SearchHit) => void }) {
  const pages = pageRef(hit.page_from, hit.page_to);
  return (
    <li className="border-b border-line-subtle px-4 py-3 last:border-0">
      <div className="flex min-w-0 items-center gap-2">
        <span className="num w-5 shrink-0 font-mono text-[11px] text-muted">{hit.rank}</span>
        <FileText className="h-3.5 w-3.5 shrink-0 text-muted" />
        <span className="truncate text-[13px] font-medium text-fg">{hit.filename}</span>
        <span className="shrink-0 font-mono text-[11px] text-muted">v{hit.version}</span>
        {pages ? <span className="num shrink-0 text-[11px] text-muted">· {pages}</span> : null}
        {hit.kind === "table" ? (
          <Badge tone="info"><Table2 className="h-3 w-3" /> Table</Badge>
        ) : null}
        <Button size="sm" variant="ghost" className="ml-auto shrink-0" onClick={() => onOpen(hit)}>
          Open document
        </Button>
      </div>
      <p className="mt-1 whitespace-pre-line pl-7 text-[13px] leading-relaxed text-fg-2 [overflow-wrap:anywhere]">
        <Highlighted snippet={hit.snippet} />
      </p>
    </li>
  );
}

const EMPTY: DealSearch | null = null;

/** Ranked passages for a settled query; renders nothing while the query is blank. */
export function DealSearchResults({
  dealId,
  query,
  onOpen,
  onClear,
}: {
  dealId: number;
  query: string;
  onOpen: (hit: SearchHit) => void;
  onClear: () => void;
}) {
  const res = useApi<DealSearch | null>(query ? () => searchDeal(dealId, query) : null, EMPTY, [dealId, query]);
  if (!query) return null;
  const data = res.data;
  const hits = data?.results ?? [];

  return (
    <div className="mb-4">
      <Section
        flush
        title={
          <span className="flex items-center gap-2">
            Passages matching <span className="max-w-[16rem] truncate font-normal text-fg-2">“{query}”</span>
            {!res.loading && data ? (
              <span className="num font-mono text-[11px] font-normal text-muted">
                {hits.length} · {Math.round(data.took_ms)} ms
              </span>
            ) : null}
          </span>
        }
        aside={
          <Button size="sm" variant="ghost" onClick={onClear}>
            Clear
          </Button>
        }
      >
        {data && !res.loading && (data.mode === "fts_only" || data.warnings.length) ? (
          <div className="border-b border-line-subtle px-4 py-2 text-[12px] text-muted">
            {data.mode === "fts_only" ? <p>Keyword only — embeddings unavailable, so matches are exact words, not meaning.</p> : null}
            {data.warnings.map((w, i) => (
              <p key={i}>{w}</p>
            ))}
          </div>
        ) : null}
        {res.unavailable ? (
          <div className="p-4"><Unavailable what="This deal" /></div>
        ) : res.loading ? (
          <SkeletonRows rows={3} height={64} />
        ) : res.error ? (
          <div className="p-4"><InlineError message={res.error} onRetry={res.refresh} /></div>
        ) : hits.length === 0 ? (
          <EmptyState
            compact
            title="No passages found"
            description="Try other words. Only indexed documents are searched — pending or failed ones are not."
          />
        ) : (
          <ol aria-label="Search results">
            {hits.map((h) => (
              <Hit key={h.chunk_id} hit={h} onOpen={onOpen} />
            ))}
          </ol>
        )}
      </Section>
    </div>
  );
}

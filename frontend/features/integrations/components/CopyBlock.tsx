"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";

/** A command in a monospace block with a copy button. */
export function CopyBlock({ label, command }: { label?: string; command: string }) {
  const [done, setDone] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(command);
      setDone(true);
      setTimeout(() => setDone(false), 1800);
    } catch {
      /* clipboard unavailable — the text is still selectable */
    }
  }
  return (
    <div>
      {label ? <div className="mb-1 text-[12px] text-muted">{label}</div> : null}
      <div className="flex items-center gap-2 rounded-sm border border-line bg-well px-3 py-2">
        <code className="min-w-0 flex-1 select-all overflow-x-auto whitespace-pre font-mono text-[12px] text-fg">{command}</code>
        <button type="button" onClick={copy} aria-label={`Copy ${command}`} className="flex h-6 w-6 shrink-0 items-center justify-center rounded-xs text-muted hover:bg-control-hover hover:text-fg">
          {done ? <Check className="h-3.5 w-3.5 text-success" /> : <Copy className="h-3.5 w-3.5" />}
        </button>
      </div>
    </div>
  );
}

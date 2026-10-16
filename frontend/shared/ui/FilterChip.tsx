"use client";

import * as Popover from "@radix-ui/react-popover";
import { Check, ChevronDown, X } from "lucide-react";
import { cx } from "@/shared/lib/format";

/** Linear-style filter chip: dashed when empty, solid with values when active. */
export function FilterChip({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { value: string; label: React.ReactNode; count?: number }[];
  value: string[];
  onChange: (v: string[]) => void;
}) {
  const active = value.length > 0;
  const summary =
    value.length === 1 ? options.find((o) => o.value === value[0])?.label ?? value[0] : `${value.length} selected`;
  return (
    <Popover.Root>
      <div
        className={cx(
          "inline-flex h-7 items-center rounded-sm border text-[12px] transition-colors",
          active ? "border-accent-border bg-accent-soft text-fg" : "border-dashed border-line-strong text-fg-2 hover:bg-control-hover",
        )}
      >
        <Popover.Trigger className="inline-flex h-full items-center gap-1.5 px-2 outline-none focus-visible:ring-2 focus-visible:ring-accent">
          <span className={active ? "text-muted" : ""}>{label}</span>
          {active ? <span className="font-medium text-fg">{summary}</span> : <ChevronDown className="h-3 w-3 text-muted" />}
        </Popover.Trigger>
        {active ? (
          <button
            aria-label={`Clear ${label} filter`}
            onClick={() => onChange([])}
            className="mr-0.5 inline-flex h-5 w-5 items-center justify-center rounded-xs text-muted hover:bg-accent/10 hover:text-fg"
          >
            <X className="h-3 w-3" />
          </button>
        ) : null}
      </div>
      <Popover.Portal>
        <Popover.Content align="start" sideOffset={6} className="a-pop z-50 w-56 rounded-md bg-raised p-1 shadow-overlay outline-none">
          <div className="px-2 pb-1 pt-1.5 text-[11px] font-medium text-muted">{label}</div>
          <div className="scroll max-h-72 overflow-y-auto">
            {options.map((o) => {
              const on = value.includes(o.value);
              return (
                <button
                  key={o.value}
                  role="menuitemcheckbox"
                  aria-checked={on}
                  onClick={() => onChange(on ? value.filter((v) => v !== o.value) : [...value, o.value])}
                  className="flex h-8 w-full items-center gap-2 rounded-xs px-2 text-left text-[13px] text-fg outline-none hover:bg-control-hover focus-visible:bg-control-hover"
                >
                  <span
                    className={cx(
                      "flex h-3.5 w-3.5 items-center justify-center rounded-[3px] border",
                      on ? "border-accent bg-accent text-on-accent" : "border-line-strong",
                    )}
                  >
                    {on ? <Check className="h-2.5 w-2.5" strokeWidth={3} /> : null}
                  </span>
                  <span className="flex-1 truncate">{o.label}</span>
                  {o.count != null ? <span className="num font-mono text-[11px] text-muted">{o.count}</span> : null}
                </button>
              );
            })}
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

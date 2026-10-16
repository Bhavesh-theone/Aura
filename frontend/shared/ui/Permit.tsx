"use client";

import { Lock } from "lucide-react";
import { cloneElement, isValidElement } from "react";
import { cx } from "@/shared/lib/format";
import { Tip } from "./primitives";

/**
 * Role gate for a single control. When `allow` is false the child is rendered
 * disabled and wrapped so the tooltip still opens on hover and keyboard focus
 * (disabled buttons swallow pointer events), saying who *can* do it.
 */
export function Permit({
  allow,
  why,
  children,
  hide,
  side = "top",
}: {
  allow: boolean;
  why: string;
  children: React.ReactElement<{ disabled?: boolean; "aria-disabled"?: boolean }>;
  /** Render nothing instead of a disabled control. */
  hide?: boolean;
  side?: "top" | "bottom" | "left" | "right";
}) {
  if (allow) return children;
  if (hide) return null;
  const disabled = isValidElement(children) ? cloneElement(children, { disabled: true, "aria-disabled": true }) : children;
  return (
    <Tip
      side={side}
      label={
        <span className="flex items-center gap-1.5">
          <Lock className="h-3 w-3 text-muted" /> {why}
        </span>
      }
    >
      <span tabIndex={0} aria-label={why} className={cx("inline-flex rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-accent/50")}>
        {disabled}
      </span>
    </Tip>
  );
}

/** Inline "who can" line for forms the viewer can read but not submit. */
export function RoleNote({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <p className={cx("flex items-center gap-1.5 text-[12px] text-muted", className)}>
      <Lock className="h-3 w-3 shrink-0" /> {children}
    </p>
  );
}

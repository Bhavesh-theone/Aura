"use client";

import { cx } from "@/shared/lib/format";

type Variant = "primary" | "approve" | "reject" | "ghost" | "outline";

const styles: Record<Variant, string> = {
  primary:
    "bg-navy text-white hover:bg-navy-600 focus-visible:outline-navy disabled:bg-navy/40",
  approve:
    "bg-cat-money text-white hover:bg-cat-money-fg focus-visible:outline-cat-money disabled:bg-cat-money/40",
  reject:
    "bg-white text-cat-outbound-fg border border-cat-outbound/40 hover:bg-cat-outbound-bg focus-visible:outline-cat-outbound disabled:opacity-50",
  ghost:
    "bg-transparent text-muted hover:bg-line-soft hover:text-ink focus-visible:outline-navy",
  outline:
    "bg-white text-ink border border-line hover:bg-line-soft focus-visible:outline-navy",
};

export function Button({
  variant = "primary",
  className,
  loading,
  children,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; loading?: boolean }) {
  return (
    <button
      {...rest}
      disabled={rest.disabled || loading}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-md px-3.5 py-2 text-sm font-medium",
        "transition-colors focus-visible:outline-2 focus-visible:outline-offset-2",
        "disabled:cursor-not-allowed",
        styles[variant],
        className,
      )}
    >
      {loading ? <Spinner /> : null}
      {children}
    </button>
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <svg className={cx("h-3.5 w-3.5 animate-spin", className)} viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

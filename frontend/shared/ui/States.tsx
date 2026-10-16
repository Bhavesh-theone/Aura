"use client";

import { AlertTriangle, Info, RotateCw, WifiOff } from "lucide-react";
import { API_BASE } from "@/shared/api/client";
import { cx } from "@/shared/lib/format";

/** One serif line, one muted sentence, one action. */
export function EmptyState({
  title,
  description,
  action,
  className,
  compact,
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
  compact?: boolean;
}) {
  return (
    <div className={cx("flex flex-col items-center justify-center text-center", compact ? "px-6 py-10" : "px-8 py-20", className)}>
      <p className={cx("font-serif text-fg", compact ? "text-[16px]" : "text-[20px]")}>{title}</p>
      {description ? <p className="mt-1.5 max-w-sm text-[13px] leading-relaxed text-muted">{description}</p> : null}
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}

export function Skel({ className, style }: { className?: string; style?: React.CSSProperties }) {
  return <div aria-hidden className={cx("skel", className)} style={style} />;
}

/** Table-like skeleton rows. */
export function SkeletonRows({ rows = 6, height = 40, className }: { rows?: number; height?: number; className?: string }) {
  return (
    <div aria-busy="true" aria-label="Loading" className={className}>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-4 border-b border-line-subtle px-4 last:border-0" style={{ height }}>
          <Skel className="h-2 w-2 rounded-full" />
          <Skel className="h-3" style={{ width: `${28 + ((i * 17) % 22)}%` }} />
          <Skel className="ml-auto h-3 w-16" />
          <Skel className="h-3 w-20" />
        </div>
      ))}
    </div>
  );
}

export function Notice({
  tone,
  title,
  children,
  action,
  className,
}: {
  tone: "error" | "info" | "ok" | "warn";
  title?: string;
  children?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  const t = {
    error: "border-danger-border bg-danger-soft text-danger",
    ok: "border-success-border bg-success-soft text-success",
    warn: "border-warning-border bg-warning-soft text-warning",
    info: "border-line bg-well text-fg-2",
  }[tone];
  const Icon = tone === "info" || tone === "ok" ? Info : AlertTriangle;
  return (
    <div role={tone === "error" ? "alert" : undefined} className={cx("flex items-start gap-2.5 rounded-sm border px-3 py-2.5 text-[13px]", t, className)}>
      <Icon className="mt-[3px] h-3.5 w-3.5 shrink-0" strokeWidth={2} />
      <div className="min-w-0 flex-1 leading-relaxed">
        {title ? <p className="font-medium">{title}</p> : null}
        {children ? <div className={cx(title && "mt-0.5 opacity-90")}>{children}</div> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

export function InlineError({ message, onRetry, className }: { message: string; onRetry?: () => void; className?: string }) {
  return (
    <Notice
      tone="error"
      className={className}
      title="Couldn’t load this"
      action={
        onRetry ? (
          <button
            onClick={onRetry}
            className="inline-flex h-6 items-center gap-1 rounded-xs px-1.5 text-[12px] font-medium hover:bg-danger/10"
          >
            <RotateCw className="h-3 w-3" /> Retry
          </button>
        ) : undefined
      }
    >
      {message}
    </Notice>
  );
}

/** A 404: the record is gone, or it sits behind a deal wall this user isn't on. */
export function Unavailable({ what }: { what: string }) {
  return (
    <Notice tone="info" title={`${what} not found`}>
      It may have been removed, or it sits behind a deal wall you’re not on.
    </Notice>
  );
}

/** Thin strip under the top bar while the server is unreachable mid-session. */
export function ServerDownBanner() {
  return (
    <div role="status" className="flex items-center gap-2 border-b border-danger-border bg-danger-soft px-6 py-2 text-[12px] text-danger">
      <WifiOff className="h-3.5 w-3.5 shrink-0" />
      <span>
        <span className="font-medium">Can’t reach the Aura server.</span> What you see may be out of date and nothing can be saved until it’s back. Retrying every few seconds…
      </span>
    </div>
  );
}

/** Full-page state when the session can’t even be restored. Aura has no offline mode. */
export function ServerDown({ onRetry, retrying }: { onRetry: () => void; retrying?: boolean }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-canvas px-6 text-center">
      <span className="flex h-11 w-11 items-center justify-center rounded-full border border-line bg-surface text-muted shadow-card">
        <WifiOff className="h-5 w-5" strokeWidth={1.8} />
      </span>
      <h1 className="mt-5 font-serif text-[28px] leading-tight text-fg">Can’t reach the Aura server</h1>
      <p className="mt-2 max-w-md text-[14px] leading-relaxed text-muted">
        The portal only works against the live server — there is no offline copy of your deals. Check that the API is running, then try again.
      </p>
      <p className="mt-2 font-mono text-[12px] text-muted">{API_BASE}</p>
      <button
        onClick={onRetry}
        disabled={retrying}
        className="mt-6 inline-flex h-9 items-center gap-2 rounded-md bg-accent px-3.5 text-[13px] font-medium text-on-accent hover:bg-accent-hover disabled:opacity-50"
      >
        <RotateCw className={cx("h-3.5 w-3.5", retrying && "animate-spin")} /> {retrying ? "Trying…" : "Try again"}
      </button>
    </div>
  );
}

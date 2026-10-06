"use client";

import * as RTooltip from "@radix-ui/react-tooltip";
import { forwardRef } from "react";
import { cx, initials } from "@/shared/lib/format";

/* --------------------------------- Button --------------------------------- */

type Variant = "primary" | "secondary" | "ghost" | "danger" | "success";
type Size = "sm" | "md" | "lg";

const variants: Record<Variant, string> = {
  primary:
    "bg-accent text-on-accent shadow-[inset_0_1px_0_rgba(255,255,255,.14),0_1px_1px_rgba(20,23,26,.12)] hover:bg-accent-hover",
  secondary: "bg-control text-fg border border-line shadow-card hover:bg-control-hover hover:border-line-strong",
  ghost: "bg-transparent text-fg-2 hover:bg-control-hover hover:text-fg",
  danger: "bg-danger text-white hover:opacity-90 dark:text-[#0b0c0e]",
  success: "bg-success text-white hover:opacity-90 dark:text-[#0b0c0e]",
};
const sizes: Record<Size, string> = {
  sm: "h-7 px-2.5 text-[12px] gap-1.5 rounded-sm",
  md: "h-8 px-3 text-[13px] gap-2 rounded-sm",
  lg: "h-9 px-3.5 text-[13px] gap-2 rounded-md",
};

export type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", loading, className, children, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      {...rest}
      disabled={rest.disabled || loading}
      className={cx(
        "inline-flex select-none items-center justify-center whitespace-nowrap font-medium",
        "transition-[background-color,border-color,color,opacity,box-shadow] duration-[var(--dur-1)] ease-[var(--ease)]",
        "disabled:pointer-events-none disabled:opacity-45",
        variants[variant],
        sizes[size],
        className,
      )}
    >
      {loading ? <Spinner /> : null}
      {children}
    </button>
  );
});

export const IconButton = forwardRef<
  HTMLButtonElement,
  React.ButtonHTMLAttributes<HTMLButtonElement> & { label: string; size?: "sm" | "md" }
>(function IconButton({ label, size = "md", className, children, ...rest }, ref) {
  return (
    <button
      ref={ref}
      aria-label={label}
      {...rest}
      className={cx(
        "inline-flex shrink-0 items-center justify-center rounded-sm text-muted transition-colors duration-[var(--dur-1)]",
        "hover:bg-control-hover hover:text-fg disabled:opacity-40",
        size === "sm" ? "h-6 w-6" : "h-8 w-8",
        className,
      )}
    >
      {children}
    </button>
  );
});

export function Spinner({ className }: { className?: string }) {
  return (
    <svg className={cx("h-3.5 w-3.5 animate-spin", className)} viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.2" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

/* ---------------------------------- Kbd ----------------------------------- */

export function Kbd({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <kbd
      className={cx(
        "inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-xs border border-line bg-control px-1",
        "font-sans text-[11px] font-medium leading-none text-muted shadow-[0_1px_0_var(--border)]",
        className,
      )}
    >
      {children}
    </kbd>
  );
}

export function Keys({ keys }: { keys: string }) {
  return (
    <span className="inline-flex items-center gap-0.5">
      {keys.split(" ").map((k, i) => (
        <Kbd key={i}>{k}</Kbd>
      ))}
    </span>
  );
}

/* --------------------------------- Tooltip -------------------------------- */

export function TooltipProvider({ children }: { children: React.ReactNode }) {
  return (
    <RTooltip.Provider delayDuration={350} skipDelayDuration={150}>
      {children}
    </RTooltip.Provider>
  );
}

export function Tip({
  label,
  keys,
  side = "bottom",
  children,
}: {
  label: React.ReactNode;
  keys?: string;
  side?: "top" | "bottom" | "left" | "right";
  children: React.ReactNode;
}) {
  return (
    <RTooltip.Root>
      <RTooltip.Trigger asChild>{children}</RTooltip.Trigger>
      <RTooltip.Portal>
        <RTooltip.Content
          side={side}
          sideOffset={6}
          className="a-fade z-[70] flex items-center gap-2 rounded-sm bg-raised px-2 py-1 text-[12px] text-fg shadow-overlay"
        >
          {label}
          {keys ? <Keys keys={keys} /> : null}
        </RTooltip.Content>
      </RTooltip.Portal>
    </RTooltip.Root>
  );
}

/* ---------------------------------- Badge --------------------------------- */

export type Tone = "neutral" | "accent" | "success" | "warning" | "danger" | "info";

const toneCls: Record<Tone, string> = {
  neutral: "bg-well text-fg-2 border-line",
  accent: "bg-accent-soft text-accent border-accent-border",
  success: "bg-success-soft text-success border-success-border",
  warning: "bg-warning-soft text-warning border-warning-border",
  danger: "bg-danger-soft text-danger border-danger-border",
  info: "bg-info-soft text-info border-info-border",
};
const dotCls: Record<Tone, string> = {
  neutral: "bg-faint",
  accent: "bg-accent",
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-danger",
  info: "bg-info",
};

export function Badge({
  tone = "neutral",
  children,
  className,
  title,
  mono,
}: {
  tone?: Tone;
  children: React.ReactNode;
  className?: string;
  title?: string;
  mono?: boolean;
}) {
  return (
    <span
      title={title}
      className={cx(
        "inline-flex h-5 shrink-0 items-center gap-1 whitespace-nowrap rounded-xs border px-1.5 text-[11px] font-medium leading-none",
        mono && "font-mono text-[11px]",
        toneCls[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function Dot({ tone = "neutral", className, pulse }: { tone?: Tone; className?: string; pulse?: boolean }) {
  return <span aria-hidden className={cx("inline-block h-1.5 w-1.5 shrink-0 rounded-full", dotCls[tone], pulse && "a-pulse", className)} />;
}

/** ID chip: mono, quiet, copy-friendly. */
export function IdChip({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <span className={cx("inline-flex h-5 items-center rounded-xs border border-line bg-well px-1.5 font-mono text-[11px] text-fg-2", className)}>
      {children}
    </span>
  );
}

/* --------------------------------- Avatar --------------------------------- */

const avatarHues = ["#1f4fd8", "#0b6a8f", "#14794a", "#a15c00", "#7a3fb8", "#b42318", "#4a5158"];
export function Avatar({ name, size = 20, className }: { name: string; size?: number; className?: string }) {
  const h = [...name].reduce((a, c) => a + c.charCodeAt(0), 0) % avatarHues.length;
  return (
    <span
      title={name}
      className={cx("inline-flex shrink-0 items-center justify-center rounded-full font-semibold text-white", className)}
      style={{ width: size, height: size, fontSize: Math.max(9, size * 0.42), background: avatarHues[h] }}
    >
      {initials(name)}
    </span>
  );
}

/* ------------------------------ Segmented ctl ------------------------------ */

export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: React.ReactNode; title?: string }[];
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex h-7 items-center rounded-sm border border-line bg-well p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          title={o.title}
          onClick={() => onChange(o.value)}
          className={cx(
            "inline-flex h-full items-center gap-1 rounded-xs px-2 text-[12px] font-medium transition-colors duration-[var(--dur-1)]",
            value === o.value ? "bg-surface text-fg shadow-card dark:bg-control-active" : "text-muted hover:text-fg",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/* ---------------------------------- Card ---------------------------------- */

export function Card({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cx("rounded-md border border-line bg-surface shadow-card", className)}>{children}</div>;
}

export function CardHeader({ title, aside, className }: { title: React.ReactNode; aside?: React.ReactNode; className?: string }) {
  return (
    <div className={cx("flex h-10 items-center gap-2 border-b border-line-subtle px-4", className)}>
      <h3 className="text-[13px] font-medium text-fg">{title}</h3>
      {aside ? <div className="ml-auto flex items-center gap-2">{aside}</div> : null}
    </div>
  );
}

/* ---------------------------------- Fields -------------------------------- */

export const inputCls =
  "h-8 w-full rounded-sm border border-line bg-control px-2.5 text-[13px] text-fg outline-none transition-[border-color,box-shadow] duration-[var(--dur-1)] placeholder:text-muted hover:border-line-strong focus:border-accent focus:shadow-[0_0_0_3px_var(--accent-soft)]";
export const selectCls = inputCls + " appearance-none bg-[length:12px] bg-[right_8px_center] bg-no-repeat pr-7 select-chevron";
export const textareaCls = inputCls.replace("h-8 ", "min-h-[72px] py-2 leading-relaxed ");
export const labelCls = "mb-1.5 block text-[12px] font-medium text-fg-2";
export const sectionLabelCls = "text-[11px] font-medium uppercase tracking-[0.06em] text-muted";

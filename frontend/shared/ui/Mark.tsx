import { cx } from "@/shared/lib/format";

/** Aura product mark: an apex over a ledger rule. */
export function AuraMark({ className, size = 24 }: { className?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden className={cx("shrink-0", className)}>
      <rect width="24" height="24" rx="6" fill="var(--accent)" />
      <path d="M6.5 16.5 12 6.5l5.5 10" fill="none" stroke="var(--on-accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M8.75 13h6.5" stroke="var(--on-accent)" strokeWidth="2" strokeLinecap="round" opacity=".55" />
      <path d="M5.5 19h13" stroke="var(--on-accent)" strokeWidth="1.5" strokeLinecap="round" opacity=".35" />
    </svg>
  );
}

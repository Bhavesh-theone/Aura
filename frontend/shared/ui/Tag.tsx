import { cx, titleCase } from "@/shared/lib/format";

export type Category =
  | "outbound"
  | "legal"
  | "money"
  | "internal_read"
  | "internal_write"
  | "unknown";

export const categoryStyles: Record<Category, { stripe: string; tag: string; label: string }> = {
  outbound: {
    stripe: "bg-cat-outbound",
    tag: "bg-cat-outbound-bg text-cat-outbound-fg",
    label: "Outbound",
  },
  legal: {
    stripe: "bg-cat-legal",
    tag: "bg-cat-legal-bg text-cat-legal-fg",
    label: "Legal",
  },
  money: {
    stripe: "bg-cat-money",
    tag: "bg-cat-money-bg text-cat-money-fg",
    label: "Money",
  },
  internal_read: {
    stripe: "bg-[#adb5bd]",
    tag: "bg-[#f1f3f5] text-[#495057]",
    label: "Internal Read",
  },
  internal_write: {
    stripe: "bg-[#4c6ef5]",
    tag: "bg-[#edf2ff] text-[#3b5bdb]",
    label: "Internal Write",
  },
  unknown: {
    stripe: "bg-[#868e96]",
    tag: "bg-[#f8f9fa] text-[#5c636a]",
    label: "Unknown",
  },
};

export function categoryStyle(category: string) {
  return categoryStyles[(category as Category) in categoryStyles ? (category as Category) : "unknown"];
}

export function CategoryTag({ category, className }: { category: string; className?: string }) {
  const style = categoryStyle(category);
  return (
    <span
      className={cx(
        "inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em]",
        style.tag,
        className,
      )}
    >
      {style.label}
    </span>
  );
}

const statusStyles: Record<string, string> = {
  pending: "bg-amber-soft text-[#8a6100] border-[#f2dfa8]",
  approved: "bg-cat-money-bg text-cat-money-fg border-[#b7ebdc]",
  rejected: "bg-cat-outbound-bg text-cat-outbound-fg border-[#f6c9c9]",
  running: "bg-[#e7f0ff] text-[#1c62d0] border-[#c7dcff]",
  queued: "bg-[#f1f3f5] text-[#495057] border-[#e2e7f0]",
  complete: "bg-cat-money-bg text-cat-money-fg border-[#b7ebdc]",
  completed: "bg-cat-money-bg text-cat-money-fg border-[#b7ebdc]",
  failed: "bg-cat-outbound-bg text-cat-outbound-fg border-[#f6c9c9]",
  awaiting_approval: "bg-amber-soft text-[#8a6100] border-[#f2dfa8]",
};

export function StatusPill({ status, className }: { status: string; className?: string }) {
  const key = status?.toLowerCase?.() ?? "unknown";
  return (
    <span
      className={cx(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium",
        statusStyles[key] || "bg-[#f8f9fa] text-muted border-line",
        className,
      )}
    >
      {titleCase(key)}
    </span>
  );
}

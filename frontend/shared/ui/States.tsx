import { cx } from "@/shared/lib/format";

export function EmptyState({
  title,
  description,
  icon,
  className,
  action,
}: {
  title: string;
  description?: string;
  icon?: React.ReactNode;
  className?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className={cx("flex h-full flex-col items-center justify-center px-8 text-center", className)}>
      {icon ? <div className="mb-3 text-line">{icon}</div> : null}
      <p className="text-sm font-semibold text-ink">{title}</p>
      {description ? <p className="mt-1.5 max-w-sm text-[13px] leading-relaxed text-muted">{description}</p> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export function SkeletonRows({ count = 5 }: { count?: number }) {
  return (
    <div className="space-y-2 p-3">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="yuki-pulse rounded-lg border border-line bg-surface p-3.5">
          <div className="h-2.5 w-20 rounded bg-line-soft" />
          <div className="mt-2.5 h-3 w-3/4 rounded bg-line-soft" />
          <div className="mt-2 h-2.5 w-1/2 rounded bg-line-soft" />
        </div>
      ))}
    </div>
  );
}

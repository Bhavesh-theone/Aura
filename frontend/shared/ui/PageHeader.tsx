import { cx } from "@/shared/lib/format";

export function PageHeader({
  title,
  description,
  actions,
  meta,
  className,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  meta?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cx("flex flex-wrap items-end gap-x-6 gap-y-3 px-8 pb-5 pt-7", className)}>
      <div className="min-w-0">
        <div className="flex items-baseline gap-3">
          <h1 className="font-serif text-[28px] leading-[1.15] text-fg">{title}</h1>
          {meta ? <span className="text-[13px] text-muted">{meta}</span> : null}
        </div>
        {description ? <p className="mt-1.5 max-w-2xl text-[13px] text-muted">{description}</p> : null}
      </div>
      {actions ? <div className="ml-auto flex items-center gap-2">{actions}</div> : null}
    </div>
  );
}

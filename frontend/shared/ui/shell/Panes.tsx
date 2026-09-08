import { cx } from "@/shared/lib/format";

export function ThreePane({ children }: { children: React.ReactNode }) {
  return <div className="flex min-h-0 flex-1">{children}</div>;
}

export function ListPane({
  title,
  subtitle,
  toolbar,
  children,
  width = "w-[380px]",
}: {
  title: string;
  subtitle?: React.ReactNode;
  toolbar?: React.ReactNode;
  children: React.ReactNode;
  width?: string;
}) {
  return (
    <section className={cx("flex min-h-0 shrink-0 flex-col border-r border-line bg-appbg", width)}>
      <div className="shrink-0 border-b border-line bg-surface px-4 py-3">
        <div className="flex items-baseline justify-between gap-2">
          <h2 className="text-[13px] font-semibold tracking-wide text-ink">{title}</h2>
          {subtitle ? <span className="text-[11px] text-muted">{subtitle}</span> : null}
        </div>
        {toolbar ? <div className="mt-2.5">{toolbar}</div> : null}
      </div>
      <div className="yuki-scroll min-h-0 flex-1 overflow-y-auto">{children}</div>
    </section>
  );
}

export function DetailPane({ children }: { children: React.ReactNode }) {
  return (
    <section className="yuki-scroll min-h-0 flex-1 overflow-y-auto bg-surface">{children}</section>
  );
}

export function OfflineBanner({ message }: { message?: string }) {
  return (
    <div className="flex items-center gap-2 border-b border-[#f5d9b8] bg-[#fff7ed] px-4 py-2 text-[12px] text-[#8a4b08]">
      <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-[#e8590c]" />
      <span>
        {message ?? "Cannot reach the Yuki OS API. Decisions made here are not recorded."} Showing
        sample data.
      </span>
    </div>
  );
}

export function ErrorBanner({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex items-center gap-2 border-b border-[#f6c9c9] bg-cat-outbound-bg px-4 py-2 text-[12px] text-cat-outbound-fg">
      <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-cat-outbound" />
      <span>{message}</span>
      {onRetry ? (
        <button onClick={onRetry} className="ml-auto font-medium underline underline-offset-2">
          Retry
        </button>
      ) : null}
    </div>
  );
}

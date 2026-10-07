import { Waypoints } from "lucide-react";
import Link from "next/link";
import { cx } from "@/shared/lib/format";

/** Link to the trace waterfall; `spanId` highlights one span on arrival. */
export function TraceLink({
  traceId,
  spanId,
  compact,
  className,
}: {
  traceId: string;
  spanId?: string | null;
  compact?: boolean;
  className?: string;
}) {
  const href = `/traces/${encodeURIComponent(traceId)}${spanId ? `?span=${encodeURIComponent(spanId)}` : ""}`;
  return (
    <Link
      href={href}
      title={`Open trace ${traceId}`}
      className={cx("inline-flex items-center gap-1 text-[12px] font-medium text-accent hover:underline", className)}
    >
      <Waypoints className="h-3.5 w-3.5" strokeWidth={1.75} />
      {compact ? null : <span>Trace</span>}
    </Link>
  );
}

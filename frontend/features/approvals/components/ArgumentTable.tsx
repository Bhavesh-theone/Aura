import { formatINR, titleCase } from "@/shared/lib/format";

function renderValue(key: string, value: unknown): React.ReactNode {
  if (value === null || value === undefined) return <span className="text-muted">—</span>;

  if (typeof value === "number" && /(amount|_inr|fee|total)/i.test(key)) {
    return <span className="font-semibold tabular-nums">{formatINR(value)}</span>;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return <span className="tabular-nums">{String(value)}</span>;
  }
  if (Array.isArray(value)) {
    return (
      <span className="flex flex-wrap gap-1.5">
        {value.map((item, i) => (
          <span key={i} className="rounded bg-line-soft px-1.5 py-0.5 text-[12px] text-ink">
            {typeof item === "object" ? JSON.stringify(item) : String(item)}
          </span>
        ))}
      </span>
    );
  }
  if (typeof value === "object") {
    return (
      <pre className="yuki-scroll overflow-x-auto rounded-md bg-[#f7f9fc] p-2.5 font-mono text-[11px] leading-relaxed text-[#40485a]">
        {JSON.stringify(value, null, 2)}
      </pre>
    );
  }

  const text = String(value);
  if (text.includes("\n") || text.length > 160) {
    return (
      <span className="block whitespace-pre-wrap rounded-md border border-line bg-[#fcfdff] p-3 text-[12.5px] leading-relaxed text-ink">
        {text}
      </span>
    );
  }
  return <span>{text}</span>;
}

/** Renders an agent's proposed tool arguments as a readable review sheet. */
export function ArgumentTable({ args }: { args: Record<string, unknown> }) {
  const entries = Object.entries(args ?? {});
  if (entries.length === 0) {
    return <p className="text-[13px] text-muted">This action takes no arguments.</p>;
  }
  return (
    <dl className="divide-y divide-line-soft">
      {entries.map(([key, value]) => (
        <div key={key} className="grid grid-cols-[150px_1fr] gap-4 py-2.5">
          <dt className="pt-0.5 text-[12px] font-medium text-muted">{titleCase(key)}</dt>
          <dd className="min-w-0 text-[13px] text-ink">{renderValue(key, value)}</dd>
        </div>
      ))}
    </dl>
  );
}

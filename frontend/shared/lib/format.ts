export function cx(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(" ");
}

export function formatINR(value: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(value);
}

/**
 * The API returns naive ISO timestamps (no zone), which are UTC. Without this
 * the feed reads hours off for anyone east of Greenwich.
 */
export function parseApiDate(iso: string): Date {
  if (typeof iso === "string" && !/(Z|[+-]\d{2}:?\d{2})$/.test(iso) && iso.includes("T")) {
    return new Date(iso + "Z");
  }
  return new Date(iso);
}

/** "12 Mar 2025, 14:05" — the format Indian back-office staff expect. */
export function formatDateTime(iso: string): string {
  const d = parseApiDate(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(d);
}

export function timeAgo(iso: string): string {
  const then = parseApiDate(iso).getTime();
  if (Number.isNaN(then)) return "";
  const seconds = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return formatDateTime(iso);
}

export function titleCase(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

/** Compact Indian money: ₹4.2 Cr, ₹18.5 L, ₹86,400. */
export function formatINRCompact(value: number): string {
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  const nf = (n: number) =>
    new Intl.NumberFormat("en-IN", { maximumFractionDigits: n >= 100 ? 0 : n >= 10 ? 1 : 2 }).format(n);
  if (abs >= 1e7) return `${sign}₹${nf(abs / 1e7)} Cr`;
  if (abs >= 1e5) return `${sign}₹${nf(abs / 1e5)} L`;
  return formatINR(value);
}

/** "BID_AUCTION" → "Bid auction". */
export function stageLabel(stage: string): string {
  const s = stage.replace(/_/g, " ").toLowerCase();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** Sentence-case a snake/kebab identifier: "approval_required" → "Approval required". */
export function humanize(value: string): string {
  if (value === "moa_aoa") return "MOA / AOA";
  return stageLabel(value.replace(/-/g, "_")).replace(ACRONYMS, (w) => w.toUpperCase());
}

/** Words that read wrong in sentence case ("Nda", "Spa", "Gst return"). */
const ACRONYMS = /\b(nda|spa|shpa|gst|cin|pan|gstin|din|llpin|upsi|cp|mac|inr|ebitda|rbi|sebi|cci|fema|huf|llp|jv)\b/gi;

/** "12 Mar, 14:05:09" in 24h — for mono audit timestamps. */
export function formatStamp(iso: string): string {
  const d = parseApiDate(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const date = new Intl.DateTimeFormat("en-IN", { day: "2-digit", month: "short" }).format(d);
  const time = new Intl.DateTimeFormat("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(d);
  return `${date} ${time}`;
}

export function shortAgo(iso: string): string {
  return timeAgo(iso).replace(" ago", "");
}

/** "3h 20m" until a future instant; "now" when past. */
export function timeUntil(iso: string): string {
  const ms = parseApiDate(iso).getTime() - Date.now();
  if (Number.isNaN(ms)) return "";
  if (ms <= 0) return "now";
  const m = Math.floor(ms / 60000);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ${m % 60}m`;
  return `${Math.floor(h / 24)}d ${h % 24}h`;
}

/** Relative for the last 30 days, then "05 Aug" (or "Aug 2025" in another year). */
export function shortDate(iso: string): string {
  const d = parseApiDate(iso);
  if (Number.isNaN(d.getTime())) return iso;
  if (Date.now() - d.getTime() < 30 * 86400000) return timeAgo(iso);
  const sameYear = d.getFullYear() === new Date().getFullYear();
  return new Intl.DateTimeFormat("en-IN", sameYear ? { day: "2-digit", month: "short" } : { month: "short", year: "numeric" }).format(d);
}

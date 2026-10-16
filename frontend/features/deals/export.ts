import { apiDownloadFile, type DownloadedFile } from "@/shared/api/client";

/** Report sections, in report order (backend core/domain/export.py SECTIONS). */
export const EXPORT_SECTIONS = [
  { id: "summary", label: "Deal summary", hint: "Header, team, flags", locked: true },
  { id: "stages", label: "Stage history", hint: "Moves, guards, overrides" },
  { id: "parties", label: "Parties", hint: "Identifiers and contacts" },
  { id: "profile", label: "Deal profile", hint: "Class-specific terms" },
  { id: "financials", label: "Financials", hint: "Figures with their sources" },
  { id: "mandate", label: "Mandate", hint: "Mandates and criteria" },
  { id: "documents", label: "Documents", hint: "List only, no file contents" },
  { id: "diligence", label: "Diligence and findings", hint: "By severity, ₹ impact" },
  { id: "conditions", label: "Conditions precedent", hint: "Status and waivers" },
  { id: "compliance", label: "Compliance", hint: "Flags and sign-offs" },
  { id: "decisions", label: "Decisions", hint: "Handoffs and reasoning" },
  { id: "agent_runs", label: "Agent runs", hint: "Counts and models" },
  { id: "audit", label: "Audit chain", hint: "Status and head hash" },
] as const;

export type ExportSectionId = (typeof EXPORT_SECTIONS)[number]["id"];
export const ALL_SECTIONS: ExportSectionId[] = EXPORT_SECTIONS.map((s) => s.id);

export type DealExportFormat = "pdf" | "docx" | "xlsx" | "json" | "zip";
export const DEAL_FORMATS: { id: DealExportFormat; label: string; hint: string }[] = [
  { id: "pdf", label: "PDF report", hint: "A4, ready to share" },
  { id: "docx", label: "Word document", hint: "Editable report" },
  { id: "xlsx", label: "Excel workbook", hint: "One sheet per section" },
  { id: "json", label: "JSON", hint: "Machine-readable, raw ₹" },
  { id: "zip", label: "ZIP of CSVs", hint: "One CSV per table" },
];

const SECTIONS_KEY = "aura_export_sections";

/** The sections chosen last time (this browser), or all of them. */
export function rememberedSections(): ExportSectionId[] {
  try {
    const raw = localStorage.getItem(SECTIONS_KEY);
    if (!raw) return ALL_SECTIONS;
    const parsed = JSON.parse(raw);
    const known = Array.isArray(parsed) ? ALL_SECTIONS.filter((s) => parsed.includes(s)) : [];
    return known.length ? Array.from(new Set<ExportSectionId>(["summary", ...known])) : ALL_SECTIONS;
  } catch {
    return ALL_SECTIONS;
  }
}

export function rememberSections(sections: ExportSectionId[]) {
  try {
    localStorage.setItem(SECTIONS_KEY, JSON.stringify(sections));
  } catch {
    /* storage unavailable */
  }
}

export function exportDeal(
  dealId: number,
  format: DealExportFormat,
  sections: ExportSectionId[],
  signal?: AbortSignal,
): Promise<DownloadedFile> {
  const params = new URLSearchParams({ format });
  if (sections.length && sections.length < ALL_SECTIONS.length) params.set("sections", sections.join(","));
  return apiDownloadFile(`/api/deals/${dealId}/export?${params}`, `deal-${dealId}.${format}`, { signal });
}

export type DealListFilters = { q?: string; classes?: string[]; stages?: string[]; outcomes?: string[] };

export function exportDealList(format: "csv" | "xlsx", f: DealListFilters): Promise<DownloadedFile> {
  const params = new URLSearchParams({ format });
  if (f.q?.trim()) params.set("q", f.q.trim());
  f.classes?.forEach((c) => params.append("transaction_class", c));
  f.stages?.forEach((s) => params.append("stage", s));
  f.outcomes?.forEach((o) => params.append("outcome", o));
  return apiDownloadFile(`/api/deals/export?${params}`, `Aura_deals.${format}`);
}

/** "1.2 MB", "84 KB". */
export function fileSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

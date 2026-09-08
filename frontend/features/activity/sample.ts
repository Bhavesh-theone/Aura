import type { ActivityEntry } from "./types";

const minutesAgo = (m: number) => new Date(Date.now() - m * 60000).toISOString();

export const sampleActivity: ActivityEntry[] = [
  { id: 9106, job_id: 312, actor: "Deal Desk Agent", action: "approval_required", created_at: minutesAgo(4), payload: { approval_id: 4187, category: "money", amount_inr: 1250000, beneficiary: "Sunrise Infra Projects Pvt. Ltd." } },
  { id: 9105, job_id: 312, actor: "Outreach Agent", action: "approval_required", created_at: minutesAgo(11), payload: { approval_id: 4186, category: "outbound", counterparty: "Ravi Menon Ventures LLP" } },
  { id: 9104, job_id: 312, actor: "Analyst Agent", action: "segment_complete", created_at: minutesAgo(13), payload: { segment: "Rebuild valuation band", band_cr: "184-198" } },
  { id: 9103, job_id: 311, actor: "Docs Agent", action: "approval_required", created_at: minutesAgo(26), payload: { approval_id: 4185, category: "legal", counterparty: "Krishna Textiles Ltd." } },
  { id: 9102, job_id: 310, actor: "Billing Agent", action: "approval_required", created_at: minutesAgo(52), payload: { approval_id: 4184, category: "money", total_inr: 4720000, client: "Deccan Agro Foods Pvt. Ltd." } },
  { id: 9101, job_id: 310, actor: "Billing Agent", action: "segment_complete", created_at: minutesAgo(54), payload: { segment: "Compute success fee", fee_inr: 4000000 } },
  { id: 9100, job_id: 310, actor: "bhavesh", action: "job_submitted", created_at: minutesAgo(63), payload: { brief: "Close out billing for the Deccan Agro Foods Series A raise." } },
  { id: 9099, job_id: 305, actor: "bhavesh", action: "approval_decided", created_at: minutesAgo(318), payload: { approval_id: 4179, decision: "approved", category: "money", amount_inr: 86400 } },
  { id: 9098, job_id: 307, actor: "Docs Agent", action: "job_complete", created_at: minutesAgo(191), payload: { shortlisted: 12, buyers_identified: 38 } },
  { id: 9097, job_id: 303, actor: "bhavesh", action: "approval_decided", created_at: minutesAgo(408), payload: { approval_id: 4176, decision: "rejected", reason: "Long-list not yet cleared with the partner group." } },
  { id: 9096, job_id: 304, actor: "Analyst Agent", action: "job_failed", created_at: minutesAgo(384), payload: { error: "OCR confidence 0.42 below threshold" } },
  { id: 9095, job_id: 304, actor: "rohit", action: "job_submitted", created_at: minutesAgo(390), payload: { brief: "Extract financials from the Bharat Logistics FY24 audited statements." } },
];

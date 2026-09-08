import type { Job } from "./types";

const minutesAgo = (m: number) => new Date(Date.now() - m * 60000).toISOString();

export const sampleJobs: Job[] = [
  {
    id: 312,
    status: "awaiting_approval",
    deal_id: 21,
    created_at: minutesAgo(18),
    inputs: {
      brief: "Prepare and circulate the revised term sheet for Project Kaveri (Ravi Menon Ventures LLP).",
      requested_by: "Bhavesh R.",
      priority: "high",
    },
    result: null,
    segments: [
      { id: 1, name: "Parse mandate & deal file", agent: "Intake Agent", status: "complete", started_at: minutesAgo(18), finished_at: minutesAgo(17), detail: "Read mandate OBS/MND/2025/117 and the last two term-sheet versions." },
      { id: 2, name: "Rebuild valuation band", agent: "Analyst Agent", status: "complete", started_at: minutesAgo(17), finished_at: minutesAgo(13), detail: "Revised pre-money band to ₹184–198 Cr on FY25E EBITDA of ₹22.4 Cr." },
      { id: 3, name: "Draft cover note", agent: "Outreach Agent", status: "complete", started_at: minutesAgo(13), finished_at: minutesAgo(11), detail: "Cover note drafted for the promoter group." },
      { id: 4, name: "Send email to counterparty", agent: "Outreach Agent", status: "awaiting_approval", started_at: minutesAgo(11), finished_at: null, detail: "Held for human approval — outbound communication." },
      { id: 5, name: "Release retainer instalment", agent: "Deal Desk Agent", status: "awaiting_approval", started_at: minutesAgo(4), finished_at: null, detail: "Held for human approval — money movement of ₹12,50,000." },
    ],
  },
  {
    id: 311,
    status: "awaiting_approval",
    deal_id: 19,
    created_at: minutesAgo(41),
    inputs: {
      brief: "Set up diligence for the Krishna Textiles Coimbatore spinning unit.",
      requested_by: "Meera Iyer",
      priority: "normal",
    },
    result: null,
    segments: [
      { id: 1, name: "Collect counterparty details", agent: "Intake Agent", status: "complete", started_at: minutesAgo(41), finished_at: minutesAgo(39) },
      { id: 2, name: "Draft mutual NDA", agent: "Docs Agent", status: "complete", started_at: minutesAgo(39), finished_at: minutesAgo(30), detail: "Three counterparty redlines accepted; Mumbai jurisdiction retained." },
      { id: 3, name: "Execute NDA", agent: "Docs Agent", status: "awaiting_approval", started_at: minutesAgo(26), finished_at: null, detail: "Held for human approval — legal execution." },
    ],
  },
  {
    id: 310,
    status: "running",
    deal_id: 24,
    created_at: minutesAgo(63),
    inputs: {
      brief: "Close out billing for the Deccan Agro Foods Series A raise.",
      requested_by: "Bhavesh R.",
      priority: "normal",
    },
    result: null,
    segments: [
      { id: 1, name: "Reconcile engagement ledger", agent: "Billing Agent", status: "complete", started_at: minutesAgo(63), finished_at: minutesAgo(57) },
      { id: 2, name: "Compute success fee", agent: "Billing Agent", status: "complete", started_at: minutesAgo(57), finished_at: minutesAgo(54), detail: "1.0% of ₹80 Cr raise less ₹40 L retainer credit." },
      { id: 3, name: "Raise GST invoice", agent: "Billing Agent", status: "awaiting_approval", started_at: minutesAgo(52), finished_at: null },
      { id: 4, name: "File in deal room", agent: "Docs Agent", status: "queued", started_at: null, finished_at: null },
    ],
  },
  {
    id: 307,
    status: "complete",
    deal_id: 21,
    created_at: minutesAgo(220),
    inputs: {
      brief: "Build the buyer long-list for Project Kaveri.",
      requested_by: "Meera Iyer",
      priority: "normal",
    },
    result: {
      buyers_identified: 38,
      shortlisted: 12,
      summary:
        "38 strategic and financial buyers screened across South India; 12 shortlisted on cheque-size and sector fit.",
    },
    segments: [
      { id: 1, name: "Screen sector universe", agent: "Analyst Agent", status: "complete", started_at: minutesAgo(220), finished_at: minutesAgo(206) },
      { id: 2, name: "Score & rank buyers", agent: "Analyst Agent", status: "complete", started_at: minutesAgo(206), finished_at: minutesAgo(198) },
      { id: 3, name: "Write long-list memo", agent: "Docs Agent", status: "complete", started_at: minutesAgo(198), finished_at: minutesAgo(191) },
    ],
  },
  {
    id: 304,
    status: "failed",
    deal_id: 17,
    created_at: minutesAgo(390),
    inputs: {
      brief: "Extract financials from the Bharat Logistics FY24 audited statements.",
      requested_by: "Rohit Shah",
      priority: "low",
    },
    result: {
      error: "Source PDF was a scanned copy without a text layer; OCR confidence below threshold.",
    },
    segments: [
      { id: 1, name: "Fetch documents", agent: "Intake Agent", status: "complete", started_at: minutesAgo(390), finished_at: minutesAgo(388) },
      { id: 2, name: "Extract statements", agent: "Analyst Agent", status: "failed", started_at: minutesAgo(388), finished_at: minutesAgo(384), detail: "OCR confidence 0.42 — below the 0.80 threshold." },
    ],
  },
];

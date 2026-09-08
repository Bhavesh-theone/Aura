import type { Approval } from "./types";

const minutesAgo = (m: number) => new Date(Date.now() - m * 60000).toISOString();

/**
 * Shown only when the API is unreachable, so the portal can still be reviewed.
 * Content mirrors a mid-market Indian investment-banking desk.
 */
export const sampleApprovals: Approval[] = [
  {
    id: 4187,
    segment_id: 9021,
    job_id: 312,
    status: "pending",
    category: "money",
    created_at: minutesAgo(4),
    requested_by: "Deal Desk Agent",
    proposed_action: {
      tool: "payments.initiate_transfer",
      category: "money",
      summary:
        "Release retainer instalment of ₹12,50,000 to Sunrise Infra Projects Pvt. Ltd. against mandate OBS/MND/2025/117.",
      arguments: {
        beneficiary: "Sunrise Infra Projects Pvt. Ltd.",
        beneficiary_account: "HDFC0001432 / XXXXXX8841",
        amount_inr: 1250000,
        gst_inclusive: true,
        mandate_ref: "OBS/MND/2025/117",
        value_date: "2025-03-14",
        narration: "Retainer instalment 2 of 4 — buy-side advisory",
      },
    },
  },
  {
    id: 4186,
    segment_id: 9018,
    job_id: 312,
    status: "pending",
    category: "outbound",
    created_at: minutesAgo(11),
    requested_by: "Outreach Agent",
    proposed_action: {
      tool: "email.send",
      category: "outbound",
      summary:
        "Send the revised term-sheet cover note to Ravi Menon Ventures LLP ahead of Thursday's promoter call.",
      arguments: {
        to: ["ravi.menon@rmventures.in", "cfo@rmventures.in"],
        cc: ["deals@opulencegroups.com"],
        subject: "Revised indicative term sheet — Project Kaveri",
        body:
          "Dear Mr. Menon,\n\nFurther to our discussion on Monday, please find the revised indicative terms for Project Kaveri. We have moved the valuation band to ₹184–198 Cr on a pre-money basis and shortened the exclusivity window to 45 days.\n\nWe would be glad to walk the promoter group through the changes on Thursday at 11:00 IST.\n\nWarm regards,\nOpulence Business Solutions Pvt. Ltd.",
        attachments: ["Project_Kaveri_Indicative_Terms_v3.pdf"],
      },
    },
  },
  {
    id: 4185,
    segment_id: 9014,
    job_id: 311,
    status: "pending",
    category: "legal",
    created_at: minutesAgo(26),
    requested_by: "Docs Agent",
    proposed_action: {
      tool: "documents.execute_nda",
      category: "legal",
      summary:
        "Execute the mutual NDA with Krishna Textiles Ltd. for the Coimbatore spinning-unit diligence.",
      arguments: {
        counterparty: "Krishna Textiles Ltd.",
        document: "Mutual_NDA_KrishnaTextiles_v2.docx",
        governing_law: "Courts at Mumbai, Maharashtra",
        term_months: 24,
        signatory: "Bhavesh R. — Partner, Opulence Business Solutions",
        redlines_accepted: 3,
      },
    },
  },
  {
    id: 4184,
    segment_id: 9009,
    job_id: 310,
    status: "pending",
    category: "money",
    created_at: minutesAgo(52),
    requested_by: "Billing Agent",
    proposed_action: {
      tool: "invoicing.raise_invoice",
      category: "money",
      summary:
        "Raise success-fee invoice of ₹47,20,000 (incl. 18% GST) on Deccan Agro Foods Pvt. Ltd. for the completed Series A raise.",
      arguments: {
        client: "Deccan Agro Foods Pvt. Ltd.",
        gstin: "27AAECD1234F1ZP",
        base_amount_inr: 4000000,
        gst_amount_inr: 720000,
        total_inr: 4720000,
        payment_terms: "Net 15",
        engagement: "Series A private placement — ₹80 Cr",
      },
    },
  },
  {
    id: 4183,
    segment_id: 9002,
    job_id: 309,
    status: "pending",
    category: "outbound",
    created_at: minutesAgo(88),
    requested_by: "Outreach Agent",
    proposed_action: {
      tool: "whatsapp.send_message",
      category: "outbound",
      summary: "Message Ms. Anjali Deshpande (Nirmaan Capital) confirming the Friday data-room walkthrough.",
      arguments: {
        to: "+91 98204 41209",
        contact: "Anjali Deshpande — Principal, Nirmaan Capital",
        message:
          "Good morning Anjali — confirming the Project Kaveri data-room walkthrough on Friday, 11:30 IST. Access credentials will follow by email from our side. — Opulence",
      },
    },
  },
  {
    id: 4182,
    segment_id: 8994,
    job_id: 308,
    status: "pending",
    category: "legal",
    created_at: minutesAgo(140),
    requested_by: "Docs Agent",
    proposed_action: {
      tool: "documents.file_roc",
      category: "legal",
      summary: "File Form MGT-14 with the RoC for the board resolution approving the Bharat Logistics share transfer.",
      arguments: {
        entity: "Bharat Logistics Solutions Pvt. Ltd.",
        cin: "U63030MH2016PTC287651",
        form: "MGT-14",
        resolution_date: "2025-03-06",
        filing_fee_inr: 600,
      },
    },
  },
  {
    id: 4179,
    segment_id: 8971,
    job_id: 305,
    status: "approved",
    category: "money",
    created_at: minutesAgo(320),
    requested_by: "Billing Agent",
    proposed_action: {
      tool: "payments.initiate_transfer",
      category: "money",
      summary: "Reimburse ₹86,400 of Chennai due-diligence travel to the Vaidyanathan & Co. engagement account.",
      arguments: {
        beneficiary: "Vaidyanathan & Co. Chartered Accountants",
        amount_inr: 86400,
        narration: "DD travel reimbursement — Project Kaveri",
      },
    },
  },
  {
    id: 4176,
    segment_id: 8950,
    job_id: 303,
    status: "rejected",
    category: "outbound",
    created_at: minutesAgo(410),
    requested_by: "Outreach Agent",
    proposed_action: {
      tool: "email.send",
      category: "outbound",
      summary: "Cold outreach to 42 promoters on the Gujarat chemicals long-list.",
      arguments: {
        recipients: 42,
        segment: "Gujarat speciality chemicals — revenue ₹50–200 Cr",
        subject: "Exploring strategic options for your business",
      },
    },
  },
];

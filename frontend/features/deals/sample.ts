import type { Deal } from "./types";

const hoursAgo = (h: number) => new Date(Date.now() - h * 3600000).toISOString();

export const sampleDeals: Deal[] = [
  { id: 21, name: "Project Kaveri", client: "Ravi Menon Ventures LLP", stage: "Term Sheet", sector: "Speciality Chemicals", value_inr: 1920000000, owner: "Bhavesh R.", updated_at: hoursAgo(1) },
  { id: 24, name: "Deccan Series A", client: "Deccan Agro Foods Pvt. Ltd.", stage: "Closing", sector: "Agri Processing", value_inr: 800000000, owner: "Meera Iyer", updated_at: hoursAgo(3) },
  { id: 19, name: "Coimbatore Spinning Unit", client: "Krishna Textiles Ltd.", stage: "Diligence", sector: "Textiles", value_inr: 640000000, owner: "Meera Iyer", updated_at: hoursAgo(6) },
  { id: 17, name: "Bharat Logistics Buyout", client: "Bharat Logistics Solutions Pvt. Ltd.", stage: "Diligence", sector: "Logistics", value_inr: 1150000000, owner: "Rohit Shah", updated_at: hoursAgo(11) },
  { id: 15, name: "Sunrise Infra Mandate", client: "Sunrise Infra Projects Pvt. Ltd.", stage: "Mandate Signed", sector: "Infrastructure", value_inr: 2450000000, owner: "Bhavesh R.", updated_at: hoursAgo(26) },
  { id: 12, name: "Nirmaan Capital Co-invest", client: "Nirmaan Capital", stage: "Origination", sector: "Financial Services", value_inr: 350000000, owner: "Rohit Shah", updated_at: hoursAgo(50) },
  { id: 9, name: "Vaidyanathan Roll-up", client: "Vaidyanathan & Co.", stage: "Origination", sector: "Professional Services", value_inr: 180000000, owner: "Meera Iyer", updated_at: hoursAgo(74) },
];

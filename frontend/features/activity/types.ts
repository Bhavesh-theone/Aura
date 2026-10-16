/** AuditResponse (api/schemas/dto.py), as served by GET /api/activity. */
export type ActivityEntry = {
  id: number;
  job_id: number | null;
  deal_id: number | null;
  actor: string;
  action: string;
  payload: Record<string, unknown>;
  created_at: string;
  /** Hash-chain fields: row_hash = SHA-256(prev_hash ‖ canonical row). */
  prev_hash: string;
  row_hash: string;
};

export type ActivityEntry = {
  id: number;
  job_id: number | null;
  actor: string;
  action: string;
  payload: Record<string, unknown> | null;
  created_at: string;
};

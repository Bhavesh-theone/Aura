import { apiFetch } from "@/shared/api/client";

/** UserOut (api/schemas/deals.py). */
export type AdminUser = {
  id: number;
  username: string;
  role: string;
  active: boolean;
};

export const listUsers = () => apiFetch<AdminUser[]>("/api/users");
export const createUser = (b: { username: string; password: string; role: string }) =>
  apiFetch<AdminUser>("/api/users", { method: "POST", body: b });
export const updateUser = (id: number, b: { role?: string; active?: boolean }) =>
  apiFetch<AdminUser>(`/api/users/${id}`, { method: "PATCH", body: b });

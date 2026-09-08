import { apiFetch } from "@/shared/api/client";
import type { Approval } from "./types";

export function listApprovals() {
  return apiFetch<Approval[]>("/api/approvals");
}

export function approveApproval(id: number) {
  return apiFetch<Approval>(`/api/approvals/${id}/approve`, { method: "POST" });
}

export function rejectApproval(id: number) {
  return apiFetch<Approval>(`/api/approvals/${id}/reject`, { method: "POST" });
}

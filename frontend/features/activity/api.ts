import { apiFetch } from "@/shared/api/client";
import type { ActivityEntry } from "./types";

export function listActivity() {
  return apiFetch<ActivityEntry[]>("/api/activity");
}

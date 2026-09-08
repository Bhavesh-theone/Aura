import { apiFetch } from "@/shared/api/client";
import type { Deal } from "./types";

/** The deals endpoint is optional on the backend; callers fall back to samples. */
export function listDeals() {
  return apiFetch<Deal[]>("/api/deals");
}

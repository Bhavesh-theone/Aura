import { apiFetch } from "@/shared/api/client";
import type { TraceResponse } from "./types";

export function getTrace(traceId: string) {
  return apiFetch<TraceResponse>(`/api/traces/${encodeURIComponent(traceId)}`);
}

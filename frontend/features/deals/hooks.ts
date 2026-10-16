"use client";

import { dealListEvents } from "@/shared/api/events";
import { useApi } from "@/shared/lib/useApi";
import { listDeals } from "./api";
import type { Deal } from "./types";

export function useDeals() {
  const r = useApi<Deal[]>(listDeals, [], [], { live: dealListEvents });
  return { ...r, deals: r.data };
}

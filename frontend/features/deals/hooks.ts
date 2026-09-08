"use client";

import { useResource } from "@/shared/lib/useResource";
import { listDeals } from "./api";
import { sampleDeals } from "./sample";
import type { Deal } from "./types";

export function useDeals() {
  const resource = useResource<Deal[]>(listDeals, sampleDeals, [], { pollMs: 30000, sampleOnMissing: true });
  return { ...resource, deals: resource.data };
}

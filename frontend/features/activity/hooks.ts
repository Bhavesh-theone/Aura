"use client";

import { useResource } from "@/shared/lib/useResource";
import { listActivity } from "./api";
import { sampleActivity } from "./sample";
import type { ActivityEntry } from "./types";

export function useActivity() {
  const resource = useResource<ActivityEntry[]>(listActivity, sampleActivity, [], { pollMs: 15000 });
  return { ...resource, activity: resource.data };
}

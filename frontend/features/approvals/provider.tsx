"use client";

import { createContext, useContext } from "react";
import { useApprovalsSource } from "./hooks";

type ApprovalsValue = ReturnType<typeof useApprovalsSource>;

const ApprovalsContext = createContext<ApprovalsValue | null>(null);

/**
 * ONE approvals subscription for the whole portal.
 *
 * The rail badge, the dashboard and the approvals workspace all read the same
 * queue. Calling the hook separately in each gave three independent polls and
 * three copies of the state, so deciding an approval in the workspace left the
 * rail badge showing a stale count until a reload.
 */
export function ApprovalsProvider({ children }: { children: React.ReactNode }) {
  const value = useApprovalsSource();
  return <ApprovalsContext.Provider value={value}>{children}</ApprovalsContext.Provider>;
}

export function useApprovals(): ApprovalsValue {
  const ctx = useContext(ApprovalsContext);
  if (!ctx) {
    throw new Error("useApprovals must be used within an ApprovalsProvider");
  }
  return ctx;
}

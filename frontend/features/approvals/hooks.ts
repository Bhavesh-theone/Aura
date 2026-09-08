"use client";

import { useCallback, useEffect, useState } from "react";
import { useResource } from "@/shared/lib/useResource";
import { approveApproval, listApprovals, rejectApproval } from "./api";
import { sampleApprovals } from "./sample";
import type { Approval } from "./types";

type StatusMap = Record<number, Approval["status"]>;

export function useApprovalsSource() {
  const resource = useResource<Approval[]>(listApprovals, sampleApprovals, [], { pollMs: 10000 });
  const [pendingId, setPendingId] = useState<number | null>(null);
  const [decisionError, setDecisionError] = useState<string | null>(null);

  // Decisions the server accepted, held only until a refresh reflects them.
  const [optimistic, setOptimistic] = useState<StatusMap>({});
  // Decisions made against sample data. These were never recorded anywhere and
  // must never leak onto real approvals.
  const [offlinePreview, setOfflinePreview] = useState<StatusMap>({});

  const { offline, data } = resource;

  // The moment we are talking to the real API again, discard preview-only
  // decisions — otherwise a still-pending live approval renders as decided and
  // loses its Approve/Reject buttons.
  useEffect(() => {
    if (!offline) setOfflinePreview((prev) => (Object.keys(prev).length ? {} : prev));
  }, [offline]);

  // Drop each optimistic entry once the server's own data agrees (or the item
  // has left the pending queue), so the override can never outlive its purpose.
  useEffect(() => {
    setOptimistic((prev) => {
      const ids = Object.keys(prev);
      if (ids.length === 0) return prev;
      const next: StatusMap = {};
      let changed = false;
      for (const key of ids) {
        const id = Number(key);
        const server = data.find((a) => a.id === id);
        if (server && server.status === "pending") next[id] = prev[id];
        else changed = true;
      }
      return changed ? next : prev;
    });
  }, [data]);

  const decide = useCallback(
    async (id: number, decision: "approve" | "reject") => {
      setPendingId(id);
      setDecisionError(null);
      const nextStatus = decision === "approve" ? "approved" : "rejected";
      try {
        await (decision === "approve" ? approveApproval(id) : rejectApproval(id));
        setOptimistic((prev) => ({ ...prev, [id]: nextStatus }));
        resource.refresh();
      } catch (err) {
        if (resource.offline) {
          setOfflinePreview((prev) => ({ ...prev, [id]: nextStatus }));
        } else {
          setDecisionError(err instanceof Error ? err.message : "Could not record the decision.");
        }
      } finally {
        setPendingId(null);
      }
    },
    [resource],
  );

  const overrides = offline ? { ...optimistic, ...offlinePreview } : optimistic;
  const approvals = data.map((a) => (overrides[a.id] ? { ...a, status: overrides[a.id] } : a));

  return { ...resource, approvals, decide, pendingId, decisionError };
}

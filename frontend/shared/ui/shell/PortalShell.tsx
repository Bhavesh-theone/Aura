"use client";

import { useApprovals } from "@/features/approvals/provider";
import { IconRail } from "./IconRail";
import { TopBar } from "./TopBar";

/**
 * Chrome for every portal page. Sits inside EventsProvider so the approvals
 * badge stays current off the single socket.
 */
export function PortalShell({ children }: { children: React.ReactNode }) {
  const { approvals } = useApprovals();
  const pending = approvals.filter((a) => a.status === "pending").length;

  return (
    <div className="flex h-screen overflow-hidden">
      <IconRail pendingCount={pending} />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main className="flex min-h-0 flex-1 flex-col">{children}</main>
      </div>
    </div>
  );
}

"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/features/auth/hooks";
import { ApprovalsProvider } from "@/features/approvals/provider";
import { EventsProvider } from "@/shared/api/events";
import { PortalShell } from "@/shared/ui/shell/PortalShell";
import { Spinner } from "@/shared/ui/Button";

export default function PortalLayout({ children }: { children: React.ReactNode }) {
  const { user, ready } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (ready && !user) router.replace("/login");
  }, [ready, user, router]);

  if (!ready || !user) {
    return (
      <div className="flex h-screen items-center justify-center bg-appbg text-muted">
        <Spinner className="h-5 w-5" />
      </div>
    );
  }

  return (
    <EventsProvider enabled>
      <ApprovalsProvider>
        <PortalShell>{children}</PortalShell>
      </ApprovalsProvider>
    </EventsProvider>
  );
}

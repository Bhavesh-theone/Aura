"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/features/auth/hooks";
import { EventsProvider } from "@/shared/api/events";
import { PortalShell } from "@/shared/ui/shell/PortalShell";
import { AuraMark } from "@/shared/ui/Mark";
import { ServerDown } from "@/shared/ui/States";

export default function PortalLayout({ children }: { children: React.ReactNode }) {
  const { user, ready, serverDown, retry } = useAuth();
  const router = useRouter();
  const [retrying, setRetrying] = useState(false);

  useEffect(() => {
    if (ready && !user && !serverDown) router.replace("/login");
  }, [ready, user, serverDown, router]);

  // Keep knocking while the server is away; the page recovers by itself.
  useEffect(() => {
    if (!serverDown) return;
    setRetrying(false);
    const id = setInterval(retry, 8000);
    return () => clearInterval(id);
  }, [serverDown, retry]);

  if (ready && serverDown) {
    return (
      <ServerDown
        retrying={retrying}
        onRetry={() => {
          setRetrying(true);
          retry();
          setTimeout(() => setRetrying(false), 1500);
        }}
      />
    );
  }

  if (!ready || !user) {
    return (
      <div className="flex h-screen items-center justify-center bg-canvas">
        <AuraMark size={28} className="a-pulse" />
      </div>
    );
  }

  return (
    <EventsProvider enabled>
      <PortalShell>{children}</PortalShell>
    </EventsProvider>
  );
}

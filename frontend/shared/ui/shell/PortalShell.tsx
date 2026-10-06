"use client";

import { useCallback, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/features/auth/hooks";
import { listHandoffs } from "@/features/handoffs/api";
import { handoffEvents, useEvents } from "@/shared/api/events";
import { useApi } from "@/shared/lib/useApi";
import { TooltipProvider } from "@/shared/ui/primitives";
import { ServerDownBanner } from "@/shared/ui/States";
import { ToastProvider } from "@/shared/ui/toast";
import { CommandPalette } from "./CommandPalette";
import { CrumbContext, type Crumb } from "./crumbs";
import { chordRoutesFor } from "./nav";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

export function isTyping(t: EventTarget | null) {
  const el = t as HTMLElement | null;
  return !!el && (["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName) || el.isContentEditable);
}

/** App chrome: sidebar, sticky top bar, ⌘K palette, global chords, toasts. */
export function PortalShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [palette, setPalette] = useState(false);
  const [crumbs, setCrumbs] = useState<Crumb[] | null>(null);
  const { user } = useAuth();
  const { connection } = useEvents();
  // Open decisions badge: live on handoff events, polled while the socket is down.
  const handoffs = useApi(listHandoffs, [], [], { live: handoffEvents });
  const refresh = handoffs.refresh;
  const role = user?.role;

  // Belt and braces: also re-count on navigation.
  useEffect(() => {
    refresh();
  }, [pathname, refresh]);

  useEffect(() => {
    try {
      setCollapsed(localStorage.getItem("aura_sidebar") === "1");
    } catch {
      /* ignore */
    }
  }, []);
  const toggleSidebar = useCallback(() => {
    setCollapsed((c) => {
      try {
        localStorage.setItem("aura_sidebar", c ? "0" : "1");
      } catch {
        /* ignore */
      }
      return !c;
    });
  }, []);

  useEffect(() => {
    let g = 0;
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette((p) => !p);
        return;
      }
      if (isTyping(e.target) || e.ctrlKey || e.metaKey || e.altKey) return;
      if (document.querySelector("[role=dialog]")) return;
      if (e.key === "[") {
        toggleSidebar();
        return;
      }
      if (e.key === "g") {
        g = Date.now();
      } else if (Date.now() - g < 900) {
        const href = chordRoutesFor(role)[e.key];
        if (href) router.push(href);
        g = 0;
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [router, toggleSidebar, role]);

  return (
    <TooltipProvider>
      <ToastProvider>
        <CrumbContext.Provider value={setCrumbs}>
          <div className="flex h-screen overflow-hidden bg-canvas">
            <Sidebar decisionCount={handoffs.data.length} collapsed={collapsed} onToggle={toggleSidebar} />
            <div id="main-scroll" className="scroll relative flex min-w-0 flex-1 flex-col overflow-y-auto">
              <TopBar onSearch={() => setPalette(true)} crumbs={crumbs} />
              {connection === "offline" ? <ServerDownBanner /> : null}
              <main className="flex min-h-0 flex-1 flex-col">{children}</main>
            </div>
          </div>
          <CommandPalette open={palette} onClose={() => setPalette(false)} />
        </CrumbContext.Provider>
      </ToastProvider>
    </TooltipProvider>
  );
}

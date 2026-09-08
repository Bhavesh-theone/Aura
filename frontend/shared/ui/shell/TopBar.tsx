"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { cx, initials, titleCase } from "@/shared/lib/format";
import { useAuth } from "@/features/auth/hooks";
import { useEvents } from "@/shared/api/events";
import { LogoutIcon } from "@/shared/ui/icons";
import { sectionForPath } from "./nav";

export function TopBar() {
  const pathname = usePathname();
  const { user, signOut, demo } = useAuth();
  const { status } = useEvents();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  const live = status === "open";

  return (
    <header className="flex h-12 shrink-0 items-center gap-4 border-b border-black/20 bg-navy px-4">
      <span className="text-[13px] font-bold tracking-[0.2em] text-white">YUKI OS</span>
      <span className="h-4 w-px bg-white/15" />
      <span className="text-[13px] font-medium text-white/70">{sectionForPath(pathname)}</span>

      <div className="ml-auto flex items-center gap-3">
        <span
          title={
            demo
              ? "API unreachable — showing sample data"
              : live
                ? "Live event stream connected"
                : "Event stream reconnecting — polling for updates"
          }
          className="hidden items-center gap-1.5 rounded-full bg-white/5 px-2.5 py-1 text-[11px] font-medium text-white/60 sm:flex"
        >
          <span
            className={cx(
              "h-1.5 w-1.5 rounded-full",
              demo ? "bg-[#e8590c]" : live ? "bg-[#37b24d]" : "bg-amber yuki-pulse",
            )}
          />
          {demo ? "Offline preview" : live ? "Live" : "Polling"}
        </span>

        <div ref={ref} className="relative">
          <button
            onClick={() => setOpen((v) => !v)}
            aria-haspopup="menu"
            aria-expanded={open}
            className="flex items-center gap-2 rounded-md py-1 pl-1 pr-2 text-left transition-colors hover:bg-white/10"
          >
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-amber text-[11px] font-bold text-navy">
              {initials(user?.username || "Yuki User")}
            </span>
            <span className="hidden leading-tight sm:block">
              <span className="block text-[12px] font-medium text-white">{user?.username ?? "—"}</span>
              <span className="block text-[10px] text-white/50">{titleCase(user?.role ?? "")}</span>
            </span>
          </button>

          {open ? (
            <div
              role="menu"
              className="yuki-fade absolute right-0 top-11 z-40 w-56 overflow-hidden rounded-lg border border-line bg-surface shadow-[0_12px_32px_rgba(27,36,54,0.16)]"
            >
              <div className="border-b border-line px-3 py-2.5">
                <p className="text-[13px] font-semibold text-ink">{user?.username ?? "—"}</p>
                <p className="text-[11px] text-muted">Opulence Business Solutions Pvt. Ltd.</p>
              </div>
              <button
                role="menuitem"
                onClick={signOut}
                className="flex w-full items-center gap-2 px-3 py-2.5 text-[13px] text-ink transition-colors hover:bg-line-soft"
              >
                <LogoutIcon className="h-4 w-4 text-muted" />
                Sign out
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </header>
  );
}

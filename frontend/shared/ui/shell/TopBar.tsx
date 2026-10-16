"use client";

import { ChevronRight, Moon, Search, Sun } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { FALLBACK_POLL_MS, useEvents } from "@/shared/api/events";
import { cx } from "@/shared/lib/format";
import { Dot, IconButton, Kbd, Tip } from "@/shared/ui/primitives";
import { useTheme } from "@/shared/ui/theme";
import type { Crumb } from "./crumbs";
import { sectionForPath } from "./nav";

export function useModKey() {
  const [mod, setMod] = useState("Ctrl");
  useEffect(() => {
    if (/Mac|iPhone|iPad/.test(navigator.platform)) setMod("⌘");
  }, []);
  return mod;
}

const PILL = {
  live: { label: "Live", tone: "success", tip: "Live updates connected — pages refresh as things change" },
  reconnecting: { label: "Reconnecting", tone: "warning", tip: `Live updates are reconnecting — pages refresh every ${FALLBACK_POLL_MS / 1000}s meanwhile` },
  offline: { label: "Offline", tone: "danger", tip: "Can’t reach the Aura server — retrying" },
} as const;

export function TopBar({ onSearch, crumbs }: { onSearch: () => void; crumbs: Crumb[] | null }) {
  const pathname = usePathname();
  const { connection } = useEvents();
  const { theme, toggle } = useTheme();
  const mod = useModKey();
  const section = sectionForPath(pathname);
  const trail: Crumb[] = crumbs ?? [{ label: section.label }];

  return (
    <header
      className="sticky top-0 z-30 flex h-12 shrink-0 items-center gap-3 px-5 backdrop-blur-md backdrop-saturate-150"
      style={{ background: "var(--topbar-bg)", boxShadow: "var(--topbar-highlight)" }}
    >
      <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1.5 text-[13px]">
        {trail.map((c, i) => {
          const last = i === trail.length - 1;
          return (
            <span key={i} className="flex min-w-0 items-center gap-1.5">
              {i > 0 ? <ChevronRight className="h-3.5 w-3.5 shrink-0 text-faint" /> : null}
              {c.href && !last ? (
                <Link href={c.href} className="truncate text-muted transition-colors hover:text-fg">
                  {c.label}
                </Link>
              ) : (
                <span className={cx("truncate", last ? "font-medium text-fg" : "text-muted")} aria-current={last ? "page" : undefined}>
                  {c.label}
                </span>
              )}
            </span>
          );
        })}
      </nav>

      <div className="ml-auto flex items-center gap-1.5">
        <button
          onClick={onSearch}
          aria-label={`Search or jump to (${mod} K)`}
          className="group flex h-8 w-[260px] items-center gap-2 rounded-sm border border-line bg-control px-2.5 text-[13px] text-muted shadow-card transition-colors hover:border-line-strong hover:text-fg-2"
        >
          <Search className="h-3.5 w-3.5" strokeWidth={2} />
          <span className="flex-1 text-left">Search or jump to…</span>
          <span className="flex items-center gap-0.5">
            <Kbd>{mod}</Kbd>
            <Kbd>K</Kbd>
          </span>
        </button>

        <Tip label={PILL[connection].tip}>
          <span role="status" aria-live="polite" className="ml-1 hidden h-8 items-center gap-1.5 rounded-sm px-2 text-[12px] text-muted md:flex">
            <Dot tone={PILL[connection].tone} pulse={connection === "reconnecting"} />
            {PILL[connection].label}
          </span>
        </Tip>

        <Tip label={theme === "dark" ? "Light theme" : "Dark theme"}>
          <IconButton label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"} onClick={toggle}>
            {theme === "dark" ? <Sun className="h-4 w-4" strokeWidth={1.8} /> : <Moon className="h-4 w-4" strokeWidth={1.8} />}
          </IconButton>
        </Tip>
      </div>
    </header>
  );
}

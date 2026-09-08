"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cx } from "@/shared/lib/format";
import { YukiMark } from "@/shared/ui/icons";
import { navItems } from "./nav";

export function IconRail({ pendingCount }: { pendingCount?: number }) {
  const pathname = usePathname();

  return (
    <nav
      aria-label="Primary"
      className="flex w-14 shrink-0 flex-col items-center gap-1 border-r border-black/20 bg-navy py-3"
    >
      <Link
        href="/"
        aria-label="Yuki OS home"
        className="mb-3 flex h-9 w-9 items-center justify-center rounded-lg bg-white/5 text-amber transition-colors hover:bg-white/10"
      >
        <YukiMark className="h-5 w-5" />
      </Link>

      {navItems.map(({ href, label, Icon }) => {
        const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
        const badge = label === "Approvals" && pendingCount ? pendingCount : 0;
        return (
          <Link
            key={href}
            href={href}
            aria-label={label}
            aria-current={active ? "page" : undefined}
            className="group relative flex h-10 w-10 items-center justify-center rounded-lg text-white/55 transition-colors hover:bg-white/10 hover:text-white"
          >
            <span
              className={cx(
                "absolute left-[-10px] h-5 w-[3px] rounded-r-full bg-amber transition-opacity",
                active ? "opacity-100" : "opacity-0",
              )}
            />
            <Icon className={cx("h-[19px] w-[19px]", active && "text-amber")} />
            {badge > 0 ? (
              <span className="absolute right-1 top-1 min-w-4 rounded-full bg-amber px-1 text-center text-[10px] font-bold leading-4 text-navy">
                {badge > 99 ? "99+" : badge}
              </span>
            ) : null}
            <span
              role="tooltip"
              className="pointer-events-none absolute left-12 z-30 whitespace-nowrap rounded-md bg-navy-700 px-2 py-1 text-xs font-medium text-white opacity-0 shadow-lg ring-1 ring-white/10 transition-opacity duration-100 group-hover:opacity-100"
            >
              {label}
            </span>
          </Link>
        );
      })}
    </nav>
  );
}

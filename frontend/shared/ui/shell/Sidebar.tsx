"use client";

import * as Menu from "@radix-ui/react-dropdown-menu";
import { ChevronsUpDown, LogOut, Moon, PanelLeft, Sun } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/features/auth/hooks";
import { roleLabel } from "@/features/auth/roles";
import { FIRM_NAME, PRODUCT_LINE } from "@/shared/config";
import { cx, titleCase } from "@/shared/lib/format";
import { AuraMark } from "@/shared/ui/Mark";
import { Avatar, Tip } from "@/shared/ui/primitives";
import { useTheme } from "@/shared/ui/theme";
import { isActive, visibleNav, type NavItem } from "./nav";

function NavLink({ item, collapsed, badge }: { item: NavItem; collapsed: boolean; badge: number }) {
  const pathname = usePathname();
  const active = isActive(item.href, pathname);
  const { Icon } = item;
  const link = (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      aria-label={collapsed ? item.label : undefined}
      className={cx(
        "group relative flex h-8 items-center gap-2.5 rounded-sm text-[13px] transition-colors duration-[var(--dur-1)]",
        collapsed ? "w-8 justify-center" : "px-2",
        active ? "font-semibold text-fg" : "font-normal text-fg-2 hover:bg-control-hover hover:text-fg",
      )}
    >
      {active ? <span aria-hidden className={cx("absolute top-1.5 bottom-1.5 w-[2px] rounded-full bg-accent", collapsed ? "-left-3" : "-left-3")} /> : null}
      <Icon className={cx("h-4 w-4 shrink-0", active ? "text-accent" : "text-muted group-hover:text-fg-2")} strokeWidth={active ? 2.2 : 1.8} />
      {!collapsed ? <span className="flex-1 truncate">{item.label}</span> : null}
      {badge > 0 ? (
        collapsed ? (
          <span className="absolute right-0.5 top-0.5 h-1.5 w-1.5 rounded-full bg-accent ring-2 ring-canvas" />
        ) : (
          <span className="num min-w-[20px] rounded-full bg-accent px-1.5 text-center text-[11px] font-semibold leading-[18px] text-on-accent">
            {badge > 99 ? "99+" : badge}
          </span>
        )
      ) : null}
    </Link>
  );
  if (collapsed || item.shortcut) {
    return (
      <Tip label={item.label} keys={item.shortcut} side="right">
        {link}
      </Tip>
    );
  }
  return link;
}

export function Sidebar({
  decisionCount,
  collapsed,
  onToggle,
}: {
  decisionCount: number;
  collapsed: boolean;
  onToggle: () => void;
}) {
  const { user, signOut } = useAuth();
  const { theme, toggle } = useTheme();
  const items = visibleNav(user?.role);
  const sections: { label: string | null; items: NavItem[] }[] = [
    { label: null, items: items.filter((n) => n.group === "primary") },
    { label: "Automation", items: items.filter((n) => n.group === "automation") },
    { label: "Admin", items: items.filter((n) => n.group === "admin") },
  ].filter((sec) => sec.items.length);

  return (
    <nav
      aria-label="Primary"
      className={cx(
        "flex shrink-0 flex-col border-r border-line bg-canvas transition-[width] duration-[var(--dur-panel)] ease-[var(--ease)]",
        collapsed ? "w-14 items-center px-3" : "w-[232px] px-3",
      )}
    >
      {/* Workspace */}
      <div className={cx("flex h-12 items-center", collapsed ? "justify-center" : "gap-2.5 px-1")}>
        <AuraMark size={22} />
        {!collapsed ? (
          <div className="min-w-0 flex-1 leading-tight">
            <div className="truncate text-[13px] font-semibold text-fg">{FIRM_NAME}</div>
            <div className="truncate text-[11px] text-muted">{PRODUCT_LINE}</div>
          </div>
        ) : null}
        {!collapsed ? (
          <Tip label="Collapse sidebar" keys="[">
            <button onClick={onToggle} aria-label="Collapse sidebar" className="flex h-6 w-6 items-center justify-center rounded-xs text-muted hover:bg-control-hover hover:text-fg">
              <PanelLeft className="h-4 w-4" strokeWidth={1.8} />
            </button>
          </Tip>
        ) : null}
      </div>

      {sections.map((sec, i) => (
        <div key={sec.label ?? "main"} className={cx(i === 0 ? "mt-3" : "mt-6", "flex flex-col gap-px", collapsed && "items-center")}>
          {sec.label ? (!collapsed ? <div className="mb-1 px-2 text-[11px] font-medium text-muted">{sec.label}</div> : <div className="mb-2 h-px w-6 bg-line" />) : null}
          {sec.items.map((item) => (
            <NavLink key={item.href} item={item} collapsed={collapsed} badge={item.href === "/decisions" ? decisionCount : 0} />
          ))}
        </div>
      ))}

      <div className="mt-auto pb-3">
        {collapsed ? (
          <Tip label="Expand sidebar" keys="[" side="right">
            <button onClick={onToggle} aria-label="Expand sidebar" className="mb-2 flex h-8 w-8 items-center justify-center rounded-sm text-muted hover:bg-control-hover hover:text-fg">
              <PanelLeft className="h-4 w-4" strokeWidth={1.8} />
            </button>
          </Tip>
        ) : null}
        <Menu.Root>
          <Menu.Trigger asChild>
            <button
              aria-label="Account menu"
              className={cx(
                "flex items-center gap-2.5 rounded-sm text-left transition-colors hover:bg-control-hover data-[state=open]:bg-control-hover",
                collapsed ? "h-8 w-8 justify-center" : "h-10 w-full px-2",
              )}
            >
              <Avatar name={user?.username ?? "User"} size={collapsed ? 24 : 26} />
              {!collapsed ? (
                <>
                  <span className="min-w-0 flex-1 leading-tight">
                    <span className="block truncate text-[13px] font-medium text-fg">{titleCase(user?.username ?? "—")}</span>
                    <span className="block truncate text-[11px] text-muted">{roleLabel(user?.role)}</span>
                  </span>
                  <ChevronsUpDown className="h-3.5 w-3.5 text-muted" />
                </>
              ) : null}
            </button>
          </Menu.Trigger>
          <Menu.Portal>
            <Menu.Content side="top" align="start" sideOffset={6} className="a-pop z-50 w-56 rounded-md bg-raised p-1 shadow-overlay">
              <div className="px-2 py-2">
                <div className="text-[13px] font-medium text-fg">{titleCase(user?.username ?? "—")}</div>
                <div className="text-[12px] text-muted">{roleLabel(user?.role)} · {FIRM_NAME}</div>
              </div>
              <Menu.Separator className="my-1 h-px bg-line-subtle" />
              <Menu.Item onSelect={toggle} className="flex h-8 cursor-default items-center gap-2 rounded-xs px-2 text-[13px] text-fg outline-none data-[highlighted]:bg-control-hover">
                {theme === "dark" ? <Sun className="h-4 w-4 text-muted" /> : <Moon className="h-4 w-4 text-muted" />}
                {theme === "dark" ? "Light theme" : "Dark theme"}
              </Menu.Item>
              <Menu.Item onSelect={signOut} className="flex h-8 cursor-default items-center gap-2 rounded-xs px-2 text-[13px] text-fg outline-none data-[highlighted]:bg-control-hover">
                <LogOut className="h-4 w-4 text-muted" /> Sign out
              </Menu.Item>
            </Menu.Content>
          </Menu.Portal>
        </Menu.Root>
      </div>
    </nav>
  );
}

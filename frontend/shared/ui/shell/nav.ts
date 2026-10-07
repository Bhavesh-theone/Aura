import { Activity, BarChart3, Bot, Gauge, Briefcase, Inbox, LayoutGrid, UserCog, type LucideIcon } from "lucide-react";

export type NavItem = {
  href: string;
  label: string;
  shortcut?: string;
  Icon: LucideIcon;
  group: "primary" | "automation" | "admin";
  /** Only these roles see the item (nav, ⌘K). Omit for everyone. */
  roles?: string[];
};

export const navItems: NavItem[] = [
  { href: "/", label: "Dashboard", shortcut: "g h", Icon: LayoutGrid, group: "primary" },
  { href: "/deals", label: "Deals", shortcut: "g d", Icon: Briefcase, group: "primary" },
  { href: "/decisions", label: "Decisions", shortcut: "g a", Icon: Inbox, group: "primary" },
  { href: "/activity", label: "Activity", shortcut: "g l", Icon: Activity, group: "primary" },
  { href: "/metrics", label: "Metrics", shortcut: "g m", Icon: BarChart3, group: "primary" },
  { href: "/jobs", label: "Agent jobs", shortcut: "g j", Icon: Bot, group: "automation" },
  { href: "/quality", label: "Agent quality", shortcut: "g q", Icon: Gauge, group: "automation" },
  { href: "/admin/users", label: "Users", shortcut: "g u", Icon: UserCog, group: "admin", roles: ["admin"] },
];

export const visibleNav = (role: string | undefined) => navItems.filter((n) => !n.roles || (role && n.roles.includes(role)));

/** Second key of a "g _" chord → route, for the items this role can see. */
export function chordRoutesFor(role: string | undefined): Record<string, string> {
  return Object.fromEntries(visibleNav(role).filter((n) => n.shortcut).map((n) => [n.shortcut!.split(" ")[1], n.href]));
}

export function isActive(href: string, pathname: string) {
  // A trace belongs to an agent job, so the sidebar keeps "Agent jobs" lit.
  const path = pathname.startsWith("/traces") ? "/jobs" : pathname;
  return href === "/" ? path === "/" : path.startsWith(href);
}

export function sectionForPath(pathname: string): NavItem {
  const path = pathname.startsWith("/traces") ? "/jobs" : pathname;
  return navItems.filter((i) => i.href !== "/").find((i) => path.startsWith(i.href)) ?? navItems[0];
}

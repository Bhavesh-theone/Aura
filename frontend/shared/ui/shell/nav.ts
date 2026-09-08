import {
  ActivityIcon,
  ApprovalsIcon,
  DashboardIcon,
  DealsIcon,
  JobsIcon,
} from "@/shared/ui/icons";

export type NavItem = {
  href: string;
  label: string;
  Icon: (props: { className?: string }) => React.ReactElement;
};

export const navItems: NavItem[] = [
  { href: "/", label: "Dashboard", Icon: DashboardIcon },
  { href: "/approvals", label: "Approvals", Icon: ApprovalsIcon },
  { href: "/jobs", label: "Jobs", Icon: JobsIcon },
  { href: "/activity", label: "Activity", Icon: ActivityIcon },
  { href: "/deals", label: "Deals", Icon: DealsIcon },
];

export function sectionForPath(pathname: string): string {
  const match = navItems
    .filter((item) => item.href !== "/")
    .find((item) => pathname.startsWith(item.href));
  if (match) return match.label;
  return "Dashboard";
}

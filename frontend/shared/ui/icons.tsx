type IconProps = { className?: string };

const base = {
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

export function DashboardIcon({ className }: IconProps) {
  return (
    <svg {...base} className={className}>
      <rect x="3" y="3" width="7.5" height="8" rx="1.5" />
      <rect x="13.5" y="3" width="7.5" height="5" rx="1.5" />
      <rect x="3" y="14" width="7.5" height="7" rx="1.5" />
      <rect x="13.5" y="11" width="7.5" height="10" rx="1.5" />
    </svg>
  );
}

export function ApprovalsIcon({ className }: IconProps) {
  return (
    <svg {...base} className={className}>
      <path d="M20 7.5v9.2a2.3 2.3 0 0 1-2.3 2.3H6.3A2.3 2.3 0 0 1 4 16.7V7.5" />
      <path d="M4 7.5 12 13l8-5.5" />
      <path d="M4 7.5A2.3 2.3 0 0 1 6.3 5.2h11.4A2.3 2.3 0 0 1 20 7.5" />
    </svg>
  );
}

export function JobsIcon({ className }: IconProps) {
  return (
    <svg {...base} className={className}>
      <rect x="3" y="6.5" width="18" height="13" rx="2" />
      <path d="M8.5 6.5V5a1.8 1.8 0 0 1 1.8-1.8h3.4A1.8 1.8 0 0 1 15.5 5v1.5" />
      <path d="M3 11.5h18" />
    </svg>
  );
}

export function ActivityIcon({ className }: IconProps) {
  return (
    <svg {...base} className={className}>
      <path d="M3 12h4l2.5-6 4.5 12 2.5-6H21" />
    </svg>
  );
}

export function DealsIcon({ className }: IconProps) {
  return (
    <svg {...base} className={className}>
      <path d="M4 20V9.5" />
      <path d="M10 20V4.5" />
      <path d="M16 20v-8" />
      <path d="M2.5 20h19" />
    </svg>
  );
}

export function ChevronRight({ className }: IconProps) {
  return (
    <svg {...base} className={className}>
      <path d="m9.5 6 6 6-6 6" />
    </svg>
  );
}

export function CheckIcon({ className }: IconProps) {
  return (
    <svg {...base} className={className} strokeWidth={2}>
      <path d="m5 12.5 4.5 4.5L19 7" />
    </svg>
  );
}

export function CrossIcon({ className }: IconProps) {
  return (
    <svg {...base} className={className} strokeWidth={2}>
      <path d="M6 6l12 12M18 6 6 18" />
    </svg>
  );
}

export function AlertIcon({ className }: IconProps) {
  return (
    <svg {...base} className={className}>
      <path d="M12 3.8 21 19.5H3L12 3.8Z" />
      <path d="M12 10v4" />
      <path d="M12 17h.01" />
    </svg>
  );
}

export function ClockIcon({ className }: IconProps) {
  return (
    <svg {...base} className={className}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5V12l3 1.8" />
    </svg>
  );
}

export function SearchIcon({ className }: IconProps) {
  return (
    <svg {...base} className={className}>
      <circle cx="11" cy="11" r="6.5" />
      <path d="m16 16 4.5 4.5" />
    </svg>
  );
}

export function LogoutIcon({ className }: IconProps) {
  return (
    <svg {...base} className={className}>
      <path d="M15 8.5V6.3A2.3 2.3 0 0 0 12.7 4H6.3A2.3 2.3 0 0 0 4 6.3v11.4A2.3 2.3 0 0 0 6.3 20h6.4a2.3 2.3 0 0 0 2.3-2.3V15.5" />
      <path d="M10.5 12H21m0 0-3-3m3 3-3 3" />
    </svg>
  );
}

export function InboxEmptyIcon({ className }: IconProps) {
  return (
    <svg {...base} className={className} strokeWidth={1.2}>
      <path d="M3 13.5 5.6 5.8A2 2 0 0 1 7.5 4.4h9a2 2 0 0 1 1.9 1.4L21 13.5v4.2a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" />
      <path d="M3 13.5h5l1.4 2.4h5.2L16 13.5h5" />
    </svg>
  );
}

/** Yuki mark: a stylised snow-crystal in amber. */
export function YukiMark({ className }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round">
      <path d="M12 2.5v19" />
      <path d="m3.8 7.2 16.4 9.6" />
      <path d="m20.2 7.2-16.4 9.6" />
      <path d="M12 6.4 9.6 4.5M12 6.4l2.4-1.9M12 17.6l-2.4 1.9M12 17.6l2.4 1.9" />
    </svg>
  );
}

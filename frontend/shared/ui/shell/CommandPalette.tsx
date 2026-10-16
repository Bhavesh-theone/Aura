"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { Briefcase, CornerDownLeft, LogOut, Moon, Plus, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "@/features/auth/hooks";
import { listDeals } from "@/features/deals/api";
import { openIntake } from "@/features/intake";
import type { Deal } from "@/features/deals/types";
import { cx, stageLabel } from "@/shared/lib/format";
import { Kbd, Keys } from "@/shared/ui/primitives";
import { useTheme } from "@/shared/ui/theme";
import { visibleNav } from "./nav";

type Cmd = {
  id: string;
  label: string;
  group: "Deals" | "Pages" | "Actions";
  icon: React.ReactNode;
  meta?: React.ReactNode;
  keys?: string;
  search: string;
  run: () => void;
};

const GROUP_ORDER: Cmd["group"][] = ["Deals", "Pages", "Actions"];

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const { signOut, user } = useAuth();
  const { toggle } = useTheme();
  const [q, setQ] = useState("");
  const [idx, setIdx] = useState(0);
  const [deals, setDeals] = useState<Deal[]>([]);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    setQ("");
    setIdx(0);
    listDeals().then(setDeals).catch(() => setDeals([]));
  }, [open]);

  const groups = useMemo(() => {
    const go = (href: string) => () => router.push(href);
    const all: Cmd[] = [
      ...deals.map<Cmd>((d) => ({
        id: `deal-${d.id}`,
        label: d.name,
        group: "Deals",
        icon: <Briefcase className="h-4 w-4" />,
        meta: (
          <span className="flex items-center gap-2">
            <span className="font-mono text-[11px] text-muted">{d.external_id}</span>
            <span className="w-[136px] truncate text-right text-[12px] text-muted">{stageLabel(d.stage)}</span>
          </span>
        ),
        search: `${d.name} ${d.external_id} ${d.stage} ${d.transaction_class}`,
        run: go(`/deals/${d.id}`),
      })),
      ...visibleNav(user?.role).map<Cmd>((n) => ({
        id: n.href,
        label: n.label,
        group: "Pages",
        icon: <n.Icon className="h-4 w-4" />,
        keys: n.shortcut,
        search: `go ${n.label}`,
        run: go(n.href),
      })),
      { id: "new", label: "New deal from documents", group: "Actions", icon: <Plus className="h-4 w-4" />, keys: "c", search: "new create deal intake upload documents wizard", run: () => openIntake(router) },
      { id: "quick", label: "Quick-create blank deal", group: "Actions", icon: <Plus className="h-4 w-4" />, search: "new create deal quick blank empty", run: () => { router.push("/deals?new=1"); window.dispatchEvent(new Event("aura:new-deal")); } },
      { id: "theme", label: "Toggle light / dark theme", group: "Actions", icon: <Moon className="h-4 w-4" />, search: "theme dark light mode", run: toggle },
      { id: "out", label: "Sign out", group: "Actions", icon: <LogOut className="h-4 w-4" />, search: "sign out logout", run: signOut },
    ];
    const s = q.trim().toLowerCase();
    const filtered = s
      ? all.filter((c) => s.split(/\s+/).every((t) => `${c.label} ${c.search}`.toLowerCase().includes(t)))
      : [...all.filter((c) => c.group === "Deals").slice(0, 5), ...all.filter((c) => c.group !== "Deals")];
    return GROUP_ORDER.map((g) => ({ group: g, items: filtered.filter((c) => c.group === g) })).filter((g) => g.items.length);
  }, [q, deals, router, toggle, signOut, user?.role]);

  const flat = groups.flatMap((g) => g.items);

  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>(`[data-idx="${idx}"]`)?.scrollIntoView({ block: "nearest" });
  }, [idx]);

  const choose = (c?: Cmd) => {
    if (!c) return;
    onClose();
    c.run();
  };

  let n = -1;
  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="a-scrim fixed inset-0 z-50 bg-(--scrim)" />
        <Dialog.Content
          aria-describedby={undefined}
          className="a-pop fixed left-1/2 top-[14vh] z-50 w-[min(620px,calc(100vw-32px))] -translate-x-1/2 overflow-hidden rounded-lg bg-raised shadow-overlay outline-none"
        >
          <Dialog.Title className="sr-only">Command palette</Dialog.Title>
          <div className="flex h-12 items-center gap-3 border-b border-line-subtle px-4">
            <Search className="h-4 w-4 text-muted" />
            <input
              autoFocus
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
                setIdx(0);
              }}
              onKeyDown={(e) => {
                if (e.key === "ArrowDown" || (e.ctrlKey && e.key === "n")) {
                  e.preventDefault();
                  setIdx((i) => Math.min(flat.length - 1, i + 1));
                } else if (e.key === "ArrowUp" || (e.ctrlKey && e.key === "p")) {
                  e.preventDefault();
                  setIdx((i) => Math.max(0, i - 1));
                } else if (e.key === "Enter") {
                  e.preventDefault();
                  choose(flat[idx]);
                }
              }}
              placeholder="Search deals by name or ID, jump to a page, run an action…"
              aria-label="Search commands"
              role="combobox"
              aria-expanded
              aria-controls="cmdk-list"
              aria-activedescendant={flat[idx] ? `cmd-${flat[idx].id}` : undefined}
              className="h-full flex-1 bg-transparent text-[14px] text-fg outline-none placeholder:text-muted"
            />
            <Kbd>Esc</Kbd>
          </div>

          <div ref={listRef} id="cmdk-list" role="listbox" className="scroll max-h-[min(420px,56vh)] overflow-y-auto p-1.5">
            {flat.length === 0 ? (
              <div className="px-3 py-10 text-center">
                <p className="font-serif text-[16px] text-fg">Nothing matches “{q}”</p>
                <p className="mt-1 text-[12px] text-muted">Try a deal ID like OBS-2026-014, or a page name.</p>
              </div>
            ) : null}
            {groups.map((g) => (
              <div key={g.group} role="group" aria-label={g.group} className="pb-1">
                <div className="px-2.5 pb-1 pt-2 text-[11px] font-medium text-muted">{g.group}</div>
                {g.items.map((c) => {
                  n += 1;
                  const i = n;
                  const sel = i === idx;
                  return (
                    <div
                      key={c.id}
                      id={`cmd-${c.id}`}
                      data-idx={i}
                      role="option"
                      aria-selected={sel}
                      onMouseMove={() => setIdx(i)}
                      onClick={() => choose(c)}
                      className={cx(
                        "flex h-9 cursor-default items-center gap-3 rounded-sm px-2.5 text-[13px]",
                        sel ? "bg-control-active text-fg" : "text-fg-2",
                      )}
                    >
                      <span className={sel ? "text-fg" : "text-muted"}>{c.icon}</span>
                      <span className="min-w-0 flex-1 truncate">{c.label}</span>
                      {c.meta}
                      {c.keys ? <Keys keys={c.keys} /> : null}
                      {sel ? <CornerDownLeft className="h-3.5 w-3.5 text-muted" /> : null}
                    </div>
                  );
                })}
              </div>
            ))}
          </div>

          <div className="flex h-9 items-center gap-4 border-t border-line-subtle bg-canvas px-4 text-[11px] text-muted dark:bg-surface">
            <span className="flex items-center gap-1.5"><Kbd>↑</Kbd><Kbd>↓</Kbd> navigate</span>
            <span className="flex items-center gap-1.5"><Kbd>↵</Kbd> open</span>
            <span className="ml-auto flex items-center gap-1.5">Go to: <Keys keys="g d" /> deals <Keys keys="g a" /> decisions</span>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

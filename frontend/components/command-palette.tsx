"use client";

import * as D from "@radix-ui/react-dialog";
import { CornerDownLeft, Inbox, Monitor, Moon, PanelLeft, Play, Search, Sun, Target } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState, type ComponentType } from "react";

import { useTheme } from "@/components/providers";
import { Kbd } from "@/components/ui/misc";
import { isActive, useDrafts, useMatches, useOverview, useStartRun } from "@/lib/queries";
import { cn } from "@/lib/utils";

export interface PaletteLink {
  href: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
}

type Group = "Actions" | "Go to" | "Jobs" | "Theme";

interface Item {
  id: string;
  group: Group;
  label: string;
  hint?: string;
  keywords?: string;
  icon: ComponentType<{ className?: string }>;
  run: () => void;
}

const GROUPS: Group[] = ["Actions", "Go to", "Jobs", "Theme"];

/** ⌘K / Ctrl-K: jump anywhere, open a job, review the next approval, run the agents or switch theme, without the mouse. */
export function CommandPalette({ links, open, setOpen, onToggleSidebar }: { links: PaletteLink[]; open: boolean; setOpen: (v: boolean) => void; onToggleSidebar?: () => void }) {
  const router = useRouter();
  const start = useStartRun();
  const { setTheme, theme } = useTheme();
  const { data: overview } = useOverview();
  const { data: drafts } = useDrafts("pending");
  const { data: matches } = useMatches({ sort: "score", limit: 12, stage: ["found", "shortlisted", "applied", "interview", "offer"] });
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const list = useRef<HTMLUListElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen(!open);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, setOpen]);

  useEffect(() => {
    if (open) {
      setQ("");
      setActive(0);
    }
  }, [open]);

  const items = useMemo<Item[]>(() => {
    const close = (fn: () => void) => () => {
      setOpen(false);
      fn();
    };
    const go = (href: string) => close(() => router.push(href));
    const running = isActive(overview?.last_run);
    const pending = drafts?.length ?? overview?.pending_approvals ?? 0;
    const next = drafts?.[0];
    const all: Item[] = [
      {
        id: "run",
        group: "Actions",
        label: running ? "Agents are running…" : "Run agents now",
        hint: running ? undefined : "Scout → Tracker",
        keywords: "start fetch scan",
        icon: Play,
        run: running ? close(() => router.push("/runs")) : close(() => start.mutate()),
      },
      {
        id: "approve-next",
        group: "Actions",
        label: next ? `Review next approval · ${next.company}` : "Review approvals",
        hint: pending ? `${pending} waiting` : "None waiting",
        keywords: "approve draft email outreach send",
        icon: Inbox,
        run: go(next ? `/approvals?draft=${next.id}` : "/approvals"),
      },
      ...(onToggleSidebar ? [{ id: "sidebar", group: "Actions" as const, label: "Collapse or expand sidebar", hint: "⌘B", icon: PanelLeft, run: close(onToggleSidebar) }] : []),
      ...links.map((l) => ({ id: l.href, group: "Go to" as const, label: l.label, icon: l.icon, run: go(l.href) })),
      ...(matches?.items ?? []).map((m) => ({
        id: m.id,
        group: "Jobs" as const,
        label: `${m.job.title} · ${m.job.company}`,
        hint: `${Math.round(m.score)} fit`,
        icon: Target,
        run: go(`/jobs/${m.id}`),
      })),
      ...([
        { v: "light", label: "Light", icon: Sun },
        { v: "dark", label: "Dark", icon: Moon },
        { v: "system", label: "System", icon: Monitor },
      ] as const).map((t) => ({
        id: `theme-${t.v}`,
        group: "Theme" as const,
        label: `Switch to ${t.label.toLowerCase()} theme`,
        hint: theme === t.v ? "Current" : undefined,
        keywords: "appearance mode color",
        icon: t.icon,
        run: close(() => setTheme(t.v)),
      })),
    ];
    const needle = q.trim().toLowerCase();
    const filtered = needle ? all.filter((i) => `${i.label} ${i.keywords ?? ""} ${i.group}`.toLowerCase().includes(needle)) : all;
    return GROUPS.flatMap((g) => filtered.filter((i) => i.group === g)); // keep order stable for ↑ ↓
  }, [q, links, matches, drafts, overview, router, setOpen, start, theme, setTheme, onToggleSidebar]);

  useEffect(() => {
    list.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") (e.preventDefault(), setActive((a) => Math.min(a + 1, items.length - 1)));
    if (e.key === "ArrowUp") (e.preventDefault(), setActive((a) => Math.max(a - 1, 0)));
    if (e.key === "Home") (e.preventDefault(), setActive(0));
    if (e.key === "End") (e.preventDefault(), setActive(items.length - 1));
    if (e.key === "Enter") (e.preventDefault(), items[active]?.run());
  };

  return (
    <D.Root open={open} onOpenChange={setOpen}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-[90] bg-black/55 backdrop-blur-[2px] data-[state=open]:animate-[fade-in_var(--dur-fast)_var(--ease)]" />
        <D.Content
          aria-describedby={undefined}
          className="panel fixed top-3 left-1/2 z-[91] flex max-h-[min(560px,calc(100dvh-24px))] w-[calc(100vw-24px)] max-w-xl -translate-x-1/2 flex-col overflow-hidden outline-none data-[state=open]:animate-[pop-in_var(--dur-base)_var(--ease)] md:top-[12vh]"
        >
          <D.Title className="sr-only">Command palette</D.Title>
          <div className="flex items-center gap-3 border-b border-border px-4">
            <Search className="size-4 shrink-0 text-text-3" aria-hidden />
            <input
              autoFocus
              role="combobox"
              aria-expanded
              aria-controls="palette-list"
              aria-activedescendant={items[active] ? `palette-${active}` : undefined}
              aria-autocomplete="list"
              value={q}
              onChange={(e) => (setQ(e.target.value), setActive(0))}
              onKeyDown={onKey}
              placeholder="Search pages, jobs and actions…"
              className="h-14 min-w-0 flex-1 bg-transparent text-[15px] text-text outline-none placeholder:text-text-3"
            />
            <span className="hidden sm:inline">
              <Kbd>esc</Kbd>
            </span>
          </div>
          <ul ref={list} id="palette-list" role="listbox" aria-label="Results" className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-2">
            {items.length === 0 && <li className="px-3 py-8 text-center text-[13.5px] text-text-3">Nothing matches “{q}”.</li>}
            {items.map((it, i) => (
              <li key={it.id} role="presentation">
                {(i === 0 || items[i - 1].group !== it.group) && (
                  <div role="presentation" className="eyebrow px-3 pt-3 pb-1.5 first:pt-1">
                    {it.group}
                  </div>
                )}
                <div
                  id={`palette-${i}`}
                  data-index={i}
                  role="option"
                  aria-selected={i === active}
                  onMouseMove={() => setActive(i)}
                  onClick={it.run}
                  className={cn(
                    "flex min-h-11 cursor-pointer items-center gap-3 rounded-[var(--radius-control)] px-3 py-2 text-[14px] md:min-h-10",
                    i === active ? "bg-elevated text-text" : "text-text-2",
                  )}
                >
                  <it.icon className={cn("size-4 shrink-0", i === active ? "text-cobalt-text" : "text-text-3")} />
                  <span className="min-w-0 flex-1 truncate">{it.label}</span>
                  {it.hint && <span className="num shrink-0 text-[12px] text-text-3">{it.hint}</span>}
                  {i === active && <CornerDownLeft className="size-3.5 shrink-0 text-text-3" aria-hidden />}
                </div>
              </li>
            ))}
          </ul>
          <div className="hidden items-center gap-3 border-t border-border px-4 py-2 text-[12px] text-text-3 sm:flex">
            <span className="flex items-center gap-1.5">
              <Kbd>↑</Kbd>
              <Kbd>↓</Kbd> move
            </span>
            <span className="flex items-center gap-1.5">
              <Kbd>↵</Kbd> open
            </span>
            <span className="ml-auto flex items-center gap-1.5">
              <Kbd>⌘K</Kbd> toggle
            </span>
          </div>
        </D.Content>
      </D.Portal>
    </D.Root>
  );
}

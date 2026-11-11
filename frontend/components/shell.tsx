"use client";

import {
  Activity,
  BadgeCheck,
  Briefcase,
  Building2,
  ChartLine,
  Gauge,
  GraduationCap,
  Inbox,
  KanbanSquare,
  LayoutDashboard,
  LogOut,
  Menu,
  MessageCircleQuestion,
  Monitor,
  Moon,
  MoreHorizontal,
  PanelLeftClose,
  PanelLeftOpen,
  Play,
  Search,
  Settings,
  Sparkles,
  Sun, IndianRupee, CreditCard, FileText } from "lucide-react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type ComponentType, type ReactNode } from "react";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { CrewStatusProvider, statusesFromRun } from "@/components/agents/crew-status";
import { AgeGateBanner } from "@/components/account-settings";
import { CommandPalette } from "@/components/command-palette";
import { Logo } from "@/components/logo";
import { NotificationBell } from "@/components/notification-bell";
import { useTheme } from "@/components/providers";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/misc";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { Tooltip, TooltipProvider } from "@/components/ui/tooltip";
import { api, signOut } from "@/lib/api";
import { useT, type Key } from "@/lib/i18n";
import { useLiveUpdates } from "@/lib/live";
import { isActive, useCampus, useMe, useOverview, useProfile, useStartRun } from "@/lib/queries";
import type { Overview, User } from "@/lib/types";
import { useMediaQuery } from "@/lib/use-media";
import { cn } from "@/lib/utils";

const PROVIDER_NAME: Record<string, string> = {
  groq: "Groq",
  anthropic: "Claude",
  offline: "Offline",
};
const short = (model: string) => model.split("/").pop()!.replace("claude-", "");

export interface NavItem {
  href: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
  badge?: "approvals" | "questions";
}

const NAV_KEYS: Record<string, Key> = {
  "/dashboard": "nav.dashboard", "/jobs": "nav.matches", "/approvals": "nav.approvals", "/skills": "nav.skills", "/tracker": "nav.tracker",
  "/insights": "nav.insights", "/campus": "nav.campus", "/proof": "nav.proof", "/runs": "nav.runs", "/settings": "nav.settings",
};

const NAV: NavItem[] = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/jobs", label: "Matches", icon: Briefcase },
  { href: "/resume", label: "Resume & ATS", icon: FileText },
  { href: "/approvals", label: "Approvals", icon: Inbox, badge: "approvals" },
  {
    href: "/skills",
    label: "Skill check",
    icon: MessageCircleQuestion,
    badge: "questions",
  },
  { href: "/tracker", label: "Tracker", icon: KanbanSquare },
  { href: "/insights", label: "Insights", icon: ChartLine },
  { href: "/campus", label: "Campus", icon: GraduationCap },
  { href: "/proof", label: "Proof pack", icon: BadgeCheck },
  { href: "/stipends", label: "Stipends", icon: IndianRupee },
  { href: "/billing", label: "Plans & billing", icon: CreditCard },
  { href: "/runs", label: "Agent runs", icon: Activity },
  { href: "/settings", label: "Settings", icon: Settings },
];

/** The four destinations a phone gets in its tab bar; everything else lives under "More". */
const TABS = ["/dashboard", "/jobs", "/approvals", "/tracker"];

const THEMES = [
  { v: "light" as const, label: "Light", icon: Sun },
  { v: "system" as const, label: "System", icon: Monitor },
  { v: "dark" as const, label: "Dark", icon: Moon },
];

const count = (item: NavItem, o?: Overview) => (item.badge === "approvals" ? (o?.pending_approvals ?? 0) : item.badge === "questions" ? (o?.open_questions ?? 0) : 0);

/* ───────────────────────── Run agents ───────────────────────── */

function useRunControl() {
  const { data: overview } = useOverview();
  const { data: profile } = useProfile();
  const start = useStartRun();
  const last = overview?.last_run;
  const active = isActive(last);
  const step = last?.current_step;
  return {
    start: () => start.mutate(),
    pending: start.isPending,
    active,
    stepLabel: step ? `${step[0].toUpperCase()}${step.slice(1)}…` : "Queued…",
    disabled: active || !profile?.has_resume,
    reason: !profile?.has_resume ? "Upload your resume first" : undefined,
  };
}

/** The one primary action. `compact` is the top-bar size: "Run" on tablets, "Run agents" from 1024px. */
export function RunButton({ compact = false }: { compact?: boolean }) {
  const run = useRunControl();
  return (
    <Button
      variant="primary"
      onClick={run.start}
      loading={run.pending}
      disabled={run.disabled}
      title={run.reason}
      aria-label={run.active ? `Agents running: ${run.stepLabel}` : "Run agents"}
      className={cn(compact ? "lg:min-w-32" : "min-w-32")}
    >
      {run.active ? (
        <>
          <span className="size-2 animate-pulse-soft rounded-full bg-[var(--on-cobalt)]" />
          {compact ? (
            <>
              <span className="lg:hidden">Running</span>
              <span className="hidden lg:inline">{run.stepLabel}</span>
            </>
          ) : (
            run.stepLabel
          )}
        </>
      ) : (
        <>
          {!run.pending && <Play className="size-3.5 fill-current" />}
          {compact ? (
            <>
              <span className="lg:hidden">Run</span>
              <span className="hidden lg:inline">Run agents</span>
            </>
          ) : (
            "Run agents"
          )}
        </>
      )}
    </Button>
  );
}

/** Phones: the primary action floats above the tab bar, in thumb reach. */
function RunFab() {
  const run = useRunControl();
  return (
    <button
      type="button"
      onClick={run.start}
      disabled={run.disabled || run.pending}
      title={run.reason}
      aria-label={run.active ? `Agents running: ${run.stepLabel}` : "Run agents"}
      className={cn(
        "fixed right-4 bottom-[calc(76px+env(safe-area-inset-bottom))] z-40 flex h-14 items-center gap-2 rounded-full bg-cobalt px-5 text-[14px] font-semibold text-on-cobalt shadow-[var(--shadow-2),0_8px_24px_-8px_var(--cobalt)] transition-[transform,background-color] duration-[var(--dur-fast)] active:scale-95 disabled:opacity-60 md:hidden",
        !run.disabled && "hover:bg-cobalt-hover",
      )}
    >
      {run.active || run.pending ? <span className="size-2.5 animate-pulse-soft rounded-full bg-[var(--on-cobalt)]" /> : <Play className="size-4 fill-current" />}
      {run.active ? run.stepLabel : "Run agents"}
    </button>
  );
}

/* ───────────────────────── Sidebar ───────────────────────── */

/**
 * The sidebar body is a container (`@container/sb`): under 121px wide it renders as the 64px rail
 * (labels become screen-reader text, footer cards shrink to icons). The same body fills the drawer.
 */
const WIDE_ONLY = "@max-[120px]/sb:hidden";
const RAIL_ONLY = "@min-[121px]/sb:hidden";

function ThemeSwitch() {
  const { theme, setTheme } = useTheme();
  const current = THEMES.find((t) => t.v === theme) ?? THEMES[2];
  const next = THEMES[(THEMES.indexOf(current) + 1) % THEMES.length];
  return (
    <>
      <div role="radiogroup" aria-label="Theme" className={cn("flex rounded-[var(--radius-control)] border border-border bg-elevated p-0.5", WIDE_ONLY)}>
        {THEMES.map(({ v, label, icon: Icon }) => (
          <button
            key={v}
            type="button"
            role="radio"
            aria-checked={theme === v}
            onClick={() => setTheme(v)}
            className={cn(
              "flex h-8 flex-1 items-center justify-center gap-1.5 rounded-[6px] text-[12px] font-medium transition-colors duration-[var(--dur-fast)]",
              theme === v ? "bg-surface text-text shadow-[var(--shadow-1)] ring-1 ring-border" : "text-text-3 hover:text-text-2",
            )}
          >
            <Icon className="size-3.5" />
            {label}
          </button>
        ))}
      </div>
      <Tooltip label={`Theme: ${current.label}. Switch to ${next.label.toLowerCase()}`}>
        <button
          type="button"
          onClick={() => setTheme(next.v)}
          aria-label={`Theme: ${current.label}. Switch to ${next.label.toLowerCase()}`}
          className={cn("mx-auto grid size-10 place-items-center rounded-[var(--radius-control)] text-text-2 hover:bg-elevated hover:text-text", RAIL_ONLY)}
        >
          <current.icon className="size-4" />
        </button>
      </Tooltip>
    </>
  );
}

function LlmStatus({ overview, rail }: { overview?: Overview; rail: boolean }) {
  const online = !!overview && overview.llm_mode !== "offline";
  const running = isActive(overview?.last_run);
  const [fast, smart] = overview?.llm_models ?? [];
  const title = !overview ? "Checking the model…" : online ? `${PROVIDER_NAME[overview.llm_mode]} connected` : "Offline mode";
  const detail = online && fast && smart ? `${short(fast)} scores · ${short(smart)} writes` : "Set GROQ_API_KEY for LLM scoring and writing";
  return (
    <Tooltip label={`Pilot · ${title}`} disabled={!rail}>
      <div
        tabIndex={rail ? 0 : undefined}
        className="card flex items-center gap-2.5 p-2.5 @max-[120px]/sb:justify-center @max-[120px]/sb:border-transparent @max-[120px]/sb:bg-transparent @max-[120px]/sb:p-0 @max-[120px]/sb:shadow-none"
      >
        <AgentAvatar agent="pilot" status={running ? "running" : online ? "idle" : "off"} size={32} decorative />
        <div className="min-w-0 flex-1 @max-[120px]/sb:sr-only">
          <div className="flex items-center gap-1.5 text-[12.5px] font-medium text-text">
            <span className={cn("size-1.5 shrink-0 rounded-full", online ? "bg-done" : "bg-your-turn")} aria-hidden />
            <span className="truncate">{title}</span>
          </div>
          <div className={cn("mt-0.5 truncate text-[11.5px] text-text-3", online && "num")}>{detail}</div>
        </div>
      </div>
    </Tooltip>
  );
}

function UserCard({ me, onLogout, rail }: { me?: User; onLogout: () => void; rail: boolean }) {
  const name = me?.name || "You";
  const plan =
    me && !me.is_demo ? (
      <Link
        href="/settings#plan"
        className={cn(
          "rounded-[4px] px-1 text-[10px] font-semibold tracking-wide uppercase",
          me.plan === "pro" ? "bg-cobalt-subtle text-cobalt-text" : "bg-elevated-2 text-text-3",
        )}
      >
        {me.plan}
      </Link>
    ) : me?.is_demo ? (
      <span className="rounded-[4px] bg-your-turn/15 px-1 text-[10px] font-semibold tracking-wide text-your-turn uppercase">Demo</span>
    ) : null;
  const details = (
    <div className="min-w-0 flex-1">
      <div className="flex items-center gap-1.5 text-[13px] font-medium">
        <span className="truncate">{name}</span>
        {plan}
      </div>
      <div className="truncate text-[11.5px] text-text-3">{me?.email}</div>
    </div>
  );
  return (
    <>
      <div className={cn("flex items-center gap-2.5 px-1", WIDE_ONLY)}>
        <AgentAvatar agent="you" user={{ name: me?.name || me?.email }} size={32} decorative />
        {details}
        <Tooltip label="Sign out" side="top">
          <button
            type="button"
            onClick={onLogout}
            aria-label="Sign out"
            className="grid size-9 place-items-center rounded-[var(--radius-control)] text-text-3 hover:bg-elevated hover:text-text"
          >
            <LogOut className="size-4" />
          </button>
        </Tooltip>
      </div>
      <Popover>
        <Tooltip label={name} disabled={!rail}>
          <PopoverTrigger asChild>
            <button type="button" aria-label={`Account: ${name}`} className={cn("mx-auto grid place-items-center rounded-[var(--radius-avatar)]", RAIL_ONLY)}>
              <AgentAvatar agent="you" user={{ name: me?.name || me?.email }} size={32} decorative />
            </button>
          </PopoverTrigger>
        </Tooltip>
        <PopoverContent side="right" align="end" label="Account" className="w-64 p-3">
          <div className="flex items-center gap-2.5">
            <AgentAvatar agent="you" user={{ name: me?.name || me?.email }} size={32} decorative />
            {details}
          </div>
          <div className="hairline my-3" />
          <button
            type="button"
            onClick={onLogout}
            className="flex h-9 w-full items-center gap-2 rounded-[var(--radius-control)] px-2 text-[13px] text-text-2 hover:bg-elevated hover:text-text"
          >
            <LogOut className="size-4" /> Sign out
          </button>
        </PopoverContent>
      </Popover>
    </>
  );
}

function SidebarBody({
  nav,
  overview,
  me,
  pathname,
  rail,
  drawer = false,
  collapsed = false,
  onToggle,
  onLogout,
}: {
  nav: NavItem[];
  overview?: Overview;
  me?: User;
  pathname: string;
  rail: boolean;
  drawer?: boolean;
  collapsed?: boolean;
  onToggle?: () => void;
  onLogout: () => void;
}) {
  return (
    <div className="@container/sb flex h-full min-h-0 flex-col">
      <div className="flex h-14 shrink-0 items-center gap-2.5 px-4 @max-[120px]/sb:h-auto @max-[120px]/sb:flex-col @max-[120px]/sb:gap-2 @max-[120px]/sb:px-0 @max-[120px]/sb:pt-4 @max-[120px]/sb:pb-2">
        <Link href="/dashboard" aria-label="JobPilot, dashboard" className="flex min-w-0 items-center gap-2.5 rounded-[var(--radius-control)]">
          <Logo size={28} />
          <span className="truncate text-[16px] font-semibold tracking-[-0.02em] @max-[120px]/sb:sr-only">JobPilot</span>
        </Link>
        {!drawer && onToggle && (
          <Tooltip
            label={
              <span className="flex items-center gap-2">
                {collapsed ? "Expand" : "Collapse"} <Kbd>⌘B</Kbd>
              </span>
            }
            side={collapsed ? "right" : "bottom"}
          >
            <button
              type="button"
              onClick={onToggle}
              aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              aria-keyshortcuts="Meta+B Control+B"
              aria-expanded={!collapsed}
              className="ml-auto hidden size-8 place-items-center rounded-[var(--radius-control)] text-text-3 hover:bg-elevated hover:text-text xl:grid @max-[120px]/sb:ml-0"
            >
              {collapsed ? <PanelLeftOpen className="size-4" /> : <PanelLeftClose className="size-4" />}
            </button>
          </Tooltip>
        )}
      </div>

      <nav aria-label="Main" className="min-h-0 flex-1 overflow-y-auto px-3 py-2 @max-[120px]/sb:px-2">
        <ul className="space-y-0.5">
          {nav.map((item) => {
            const n = count(item, overview);
            const on = pathname.startsWith(item.href);
            const Icon = item.icon;
            return (
              <li key={item.href}>
                <Tooltip label={n ? `${item.label} · ${n}` : item.label} disabled={!rail}>
                  <Link
                    href={item.href}
                    aria-current={on ? "page" : undefined}
                    className={cn(
                      "group relative flex h-10 items-center gap-2.5 rounded-[var(--radius-control)] px-3 text-[13.5px] transition-colors duration-[var(--dur-fast)] md:h-9 @max-[120px]/sb:h-10 @max-[120px]/sb:justify-center @max-[120px]/sb:px-0",
                      on ? "bg-elevated font-medium text-text" : "text-text-2 hover:bg-elevated/60 hover:text-text",
                    )}
                  >
                    {on && <span aria-hidden className="absolute inset-y-2 left-0 w-[2px] rounded-full bg-cobalt" />}
                    <span className="relative grid size-5 shrink-0 place-items-center">
                      <Icon className={cn("size-4", on ? "text-cobalt-text" : "text-text-3 group-hover:text-text-2")} />
                      {n > 0 && (
                        <span
                          aria-hidden
                          className={cn(
                            "num absolute -top-1.5 -right-2 grid h-4 min-w-4 place-items-center rounded-full bg-cobalt px-1 text-[9.5px] font-semibold text-on-cobalt",
                            RAIL_ONLY,
                          )}
                        >
                          {n > 9 ? "9+" : n}
                        </span>
                      )}
                    </span>
                    <span className="truncate @max-[120px]/sb:sr-only">
                      {item.label}
                      {n > 0 && <span className="sr-only">, {n} waiting</span>}
                    </span>
                    {n > 0 && (
                      <span aria-hidden className={cn("num ml-auto rounded-full bg-cobalt-subtle px-1.5 text-[11px] font-semibold text-cobalt-text", WIDE_ONLY)}>
                        {n}
                      </span>
                    )}
                  </Link>
                </Tooltip>
              </li>
            );
          })}
        </ul>
      </nav>

      <div className={cn("shrink-0 space-y-3 border-t border-border p-3 @max-[120px]/sb:space-y-2 @max-[120px]/sb:px-2", drawer && "pb-[calc(12px+env(safe-area-inset-bottom))]")}>
        <LlmStatus overview={overview} rail={rail} />
        <ThemeSwitch />
        <UserCard me={me} onLogout={onLogout} rail={rail} />
      </div>
    </div>
  );
}

/* ───────────────────────── Phone tab bar ───────────────────────── */

function TabBar({ nav, overview, pathname, onMore }: { nav: NavItem[]; overview?: Overview; pathname: string; onMore: () => void }) {
  const tabs = TABS.map((h) => nav.find((n) => n.href === h)!).filter(Boolean);
  const moreOn = !TABS.some((h) => pathname.startsWith(h));
  const cell = "relative flex h-16 flex-col items-center justify-center gap-1 text-[11px] font-medium transition-colors duration-[var(--dur-fast)]";
  return (
    <nav aria-label="Main" className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-surface/92 pb-[env(safe-area-inset-bottom)] backdrop-blur-xl md:hidden">
      <ul className="grid grid-cols-5">
        {tabs.map((item) => {
          const on = pathname.startsWith(item.href);
          const n = count(item, overview);
          const Icon = item.icon;
          return (
            <li key={item.href}>
              <Link href={item.href} aria-current={on ? "page" : undefined} className={cn(cell, on ? "text-text" : "text-text-3")}>
                {on && <span aria-hidden className="absolute top-0 h-[2px] w-8 rounded-full bg-cobalt" />}
                <span className="relative">
                  <Icon className={cn("size-5", on && "text-cobalt-text")} />
                  {n > 0 && (
                    <span
                      aria-hidden
                      className="num absolute -top-1.5 -right-2.5 grid h-4 min-w-4 place-items-center rounded-full bg-cobalt px-1 text-[9.5px] font-semibold text-on-cobalt"
                    >
                      {n > 9 ? "9+" : n}
                    </span>
                  )}
                </span>
                {item.label}
                {n > 0 && <span className="sr-only">, {n} waiting</span>}
              </Link>
            </li>
          );
        })}
        <li>
          <button type="button" onClick={onMore} aria-label="More pages" className={cn(cell, "w-full", moreOn ? "text-text" : "text-text-3")}>
            {moreOn && <span aria-hidden className="absolute top-0 h-[2px] w-8 rounded-full bg-cobalt" />}
            <MoreHorizontal className={cn("size-5", moreOn && "text-cobalt-text")} />
            More
          </button>
        </li>
      </ul>
    </nav>
  );
}

/* ───────────────────────── Shell ───────────────────────── */

/** Shown to demo visitors: what they're looking at, and the way to keep it. */
function DemoBanner({ expiresAt }: { expiresAt: string | null }) {
  const router = useRouter();
  const qc = useQueryClient();
  const hours = expiresAt ? Math.max(1, Math.round((new Date(expiresAt).getTime() - Date.now()) / 3_600_000)) : 24;
  const signUp = async () => {
    await api.post("/auth/logout");
    qc.clear();
    router.replace("/register");
  };
  return (
    <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 border-b border-border bg-cobalt-subtle px-4 py-2 text-center text-[13px] text-text-2">
      <Sparkles className="hidden size-3.5 text-cobalt-text sm:block" aria-hidden />
      <span>
        <b className="font-semibold text-text">Live demo.</b>
        <span className="sm:hidden"> Deleted in {hours}h, sending off.</span>
        <span className="hidden sm:inline">
          {" "}
          A private copy with real jobs, deleted in about {hours} hour
          {hours === 1 ? "" : "s"}. Sending is turned off.
        </span>
      </span>
      <button type="button" onClick={signUp} className="font-medium text-cobalt-text hover:underline">
        <span className="sm:hidden">Sign up →</span>
        <span className="hidden sm:inline">Create your free account →</span>
      </button>
    </div>
  );
}

/** Whenever the latest run advances a step, refresh everything that step may have produced. */
function useRunSync(signature: string | undefined) {
  const qc = useQueryClient();
  const prev = useRef(signature);
  useEffect(() => {
    if (prev.current !== undefined && signature !== prev.current) {
      for (const key of ["matches", "drafts", "reminders", "runs", "match", "questions", "notifications", "research", "profile"]) qc.invalidateQueries({ queryKey: [key] });
    }
    prev.current = signature;
  }, [signature, qc]);
}

/** ⌘B (Ctrl-B) collapses the desktop sidebar to its rail; the choice is remembered per browser. */
function useCollapsed() {
  const [collapsed, setCollapsed] = useState(false);
  useEffect(() => {
    try {
      setCollapsed(localStorage.getItem("jp-sidebar") === "rail");
    } catch {}
  }, []);
  const toggle = useCallback(() => {
    setCollapsed((v) => {
      try {
        localStorage.setItem("jp-sidebar", v ? "wide" : "rail");
      } catch {}
      return !v;
    });
  }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.key.toLowerCase() !== "b" || e.altKey || e.shiftKey) return;
      const t = e.target as HTMLElement | null;
      if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return; // bold in editors stays bold
      e.preventDefault();
      toggle();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggle]);
  return [collapsed, toggle] as const;
}

function IconButton({ label, onClick, className, children }: { label: string; onClick: () => void; className?: string; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className={cn(
        "grid size-11 shrink-0 place-items-center rounded-[var(--radius-control)] text-text-2 transition-colors hover:bg-elevated hover:text-text md:size-9",
        className,
      )}
    >
      {children}
    </button>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { data: me } = useMe();
  const { data: overview } = useOverview();
  const { data: campus } = useCampus();
  const last = overview?.last_run;
  useRunSync(last ? `${last.id}:${last.status}:${last.current_step}:${last.steps.length}` : undefined);
  useLiveUpdates();

  const [palette, setPalette] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const [collapsed, toggleCollapsed] = useCollapsed();
  const wideScreen = useMediaQuery("(min-width: 1280px)");
  const rail = collapsed || !wideScreen;

  useEffect(() => setDrawer(false), [pathname]);

  const logout = () => signOut(); // always lands on the landing page

  const t = useT();
  const nav: NavItem[] = [
    ...NAV.map((n) => ({ ...n, label: NAV_KEYS[n.href] ? t(NAV_KEYS[n.href]) : n.label })),
    ...(campus?.college?.role === "officer" ? [{ href: "/college", label: "College", icon: Building2 }] : []),
    ...(me?.is_admin ? [{ href: "/admin", label: "Admin", icon: Gauge }] : []),
  ];
  const current = nav.find((n) => pathname.startsWith(n.href));
  const body = { nav, overview, me, pathname, onLogout: logout };

  return (
    // Every character in the app follows the live run (and drafts waiting on you) unless told otherwise.
    <CrewStatusProvider value={statusesFromRun(last, overview?.pending_approvals ?? 0)}>
      <TooltipProvider delayDuration={250} skipDelayDuration={100}>
        <a href="#main" className="sr-only z-[100] rounded-[var(--radius-control)] bg-cobalt px-3 py-2 text-on-cobalt focus:not-sr-only focus:fixed focus:top-3 focus:left-3">
          Skip to content
        </a>
        <CommandPalette links={nav} open={palette} setOpen={setPalette} onToggleSidebar={toggleCollapsed} />

        <div className="flex min-h-dvh">
          {/* ≥1024: sticky sidebar. 1024–1279 is always the 64px rail; ≥1280 is 248px unless collapsed. */}
          <aside
            aria-label="Sidebar"
            className={cn(
              "sticky top-0 hidden h-dvh w-16 shrink-0 border-r border-border bg-surface transition-[width] duration-[var(--dur-base)] ease-[var(--ease)] lg:block",
              !collapsed && "xl:w-[248px]",
            )}
          >
            <SidebarBody {...body} rail={rail} collapsed={collapsed} onToggle={toggleCollapsed} />
          </aside>

          {/* 768–1023 opens it as a drawer from the left; on phones "More" opens it as a bottom sheet. */}
          <Sheet open={drawer} onOpenChange={setDrawer}>
            <SheetContent title="Navigation" side="left" hideHeader className="md:w-[280px]">
              <SidebarBody {...body} rail={false} drawer />
            </SheetContent>
          </Sheet>

          {/* overflow-x-clip (not hidden) keeps one wide child from widening the page without breaking the sticky top bar. */}
          <div className="flex min-w-0 flex-1 flex-col overflow-x-clip">
            {me?.is_demo && <DemoBanner expiresAt={me.expires_at} />}
            <header className="sticky top-0 z-30 border-b border-border bg-bg/80 backdrop-blur-xl">
              <div className="mx-auto flex h-14 max-w-[1440px] items-center gap-1.5 px-2 md:gap-2 md:px-6 lg:px-8">
                <IconButton label="Open navigation" onClick={() => setDrawer(true)} className="hidden md:grid lg:hidden">
                  <Menu className="size-[18px]" />
                </IconButton>
                <Link href="/dashboard" aria-label="JobPilot, dashboard" className="grid size-11 shrink-0 place-items-center rounded-[var(--radius-control)] md:size-9 lg:hidden">
                  <Logo size={26} />
                </Link>
                <span className="truncate text-[15px] font-semibold tracking-[-0.01em] lg:hidden">{current?.label ?? "JobPilot"}</span>

                <button
                  type="button"
                  onClick={() => setPalette(true)}
                  aria-keyshortcuts="Meta+K Control+K"
                  className="hidden h-9 w-full max-w-[420px] items-center gap-2 rounded-[var(--radius-control)] border border-border bg-elevated px-3 text-[13px] text-text-3 transition-colors hover:border-border-strong hover:text-text-2 lg:flex"
                >
                  <Search className="size-4" aria-hidden />
                  Search, jump to a job, or run an action…
                  <span className="ml-auto">
                    <Kbd>⌘K</Kbd>
                  </span>
                </button>

                <div className="ml-auto flex items-center gap-0.5 md:gap-2">
                  <IconButton label="Search (⌘K)" onClick={() => setPalette(true)} className="lg:hidden">
                    <Search className="size-[18px]" />
                  </IconButton>
                  <NotificationBell />
                  <div className="hidden md:block">
                    <RunButton compact />
                  </div>
                </div>
              </div>
            </header>

            <main
              id="main"
              tabIndex={-1}
              className="mx-auto w-full max-w-[1440px] flex-1 px-4 pt-5 pb-[calc(152px+env(safe-area-inset-bottom))] outline-none md:px-6 md:pt-6 md:pb-10 lg:px-8 lg:pt-8"
            >
              <AgeGateBanner />
              {children}
            </main>
          </div>
        </div>

        <RunFab />
        <TabBar nav={nav} overview={overview} pathname={pathname} onMore={() => setDrawer(true)} />
      </TooltipProvider>
    </CrewStatusProvider>
  );
}

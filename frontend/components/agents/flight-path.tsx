"use client";

import { ArrowRight, ChevronDown } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { AgentAvatar, type AgentStatus } from "@/components/agents/agent-avatar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { StatusPill } from "@/components/ui/status-dot";
import { AGENTS, FLIGHT_PATH, type CrewKey } from "@/config/agents";
import { useMe, useRun } from "@/lib/queries";
import type { Run, RunStep } from "@/lib/types";
import { cn, ms, usd } from "@/lib/utils";

interface Node {
  key: CrewKey;
  name: string;
  role: string;
  status: AgentStatus;
  /** What the step reported, or the agent's job when it hasn't run. */
  detail: string;
  duration: number | null;
  index: number;
}

const stepKey = (k: CrewKey) => (k === "you" ? "approval" : k);

function toStatus(step: RunStep | undefined, run: Run | null | undefined, index: number): AgentStatus {
  switch (step?.status) {
    case "completed":
      return "done";
    case "running":
      return "running";
    case "waiting":
      return "your-turn";
    case "failed":
      return "error";
    case "skipped":
      return "off";
  }
  return run?.status === "queued" && index === 0 ? "running" : "idle";
}

function buildNodes(run: Run | null | undefined, pending: number): Node[] {
  return FLIGHT_PATH.map((key, index) => {
    const step = run?.steps.find((s) => s.agent === stepKey(key));
    const started = step?.started_at ? new Date(step.started_at).getTime() : null;
    const ended = step?.ended_at ? new Date(step.ended_at).getTime() : null;
    const isYou = key === "you";
    return {
      key,
      index,
      name: isYou ? "Your turn" : AGENTS[key].name,
      role: isYou ? "You approve before anything is sent" : AGENTS[key].role,
      // Drafts waiting in Approvals make it your turn, whatever the latest run says.
      status: isYou && pending > 0 ? "your-turn" : toStatus(step, run, index),
      detail:
        isYou && pending > 0
          ? `${pending} draft${pending === 1 ? "" : "s"} waiting for your approval`
          : step?.status === "skipped"
            ? `Skipped: ${step.detail}`
            : step?.detail || (isYou ? "You approve before anything is sent" : AGENTS[key].role),
      duration: started && ended ? ended - started : null,
    };
  });
}

/** The node the eye should go to: whoever is running or waiting on you, else the last one that finished. */
function focusIndex(nodes: Node[]) {
  const live = nodes.findIndex((n) => n.status === "running" || n.status === "your-turn" || n.status === "error");
  if (live >= 0) return live;
  const reached = nodes.map((n) => n.status !== "idle").lastIndexOf(true);
  return Math.max(0, reached);
}

/** Popover body: the full result text, timing and this step's share of the run's LLM spend. */
function NodeDetail({ node, runId, user }: { node: Node; runId?: string; user?: string | null }) {
  const { data: detail } = useRun(runId ?? "");
  const calls = runId ? detail?.calls.filter((c) => c.agent === node.key) ?? [] : [];
  const cost = calls.reduce((t, c) => t + Number(c.cost_usd), 0);
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <AgentAvatar agent={node.key} status={node.status} size={96} user={{ name: user }} decorative />
        <div className="min-w-0">
          <div className="text-[15px] font-semibold">{node.name}</div>
          <div className="text-[12.5px] leading-snug text-text-3">{node.role}</div>
          <div className="mt-2">
            <StatusPill status={node.status} />
          </div>
        </div>
      </div>
      <p className="text-[13.5px] leading-relaxed text-text-2">{node.detail}</p>
      <div className="num flex flex-wrap gap-x-3 gap-y-1 text-[12px] text-text-3">
        <span>{node.duration != null ? ms(node.duration) : "No timing yet"}</span>
        {calls.length > 0 && (
          <>
            <span>{usd(cost, 2)}</span>
            <span>
              {calls.length} LLM call{calls.length === 1 ? "" : "s"}
            </span>
          </>
        )}
      </div>
      {node.key === "you" ? (
        <Link href="/approvals" className="inline-flex items-center gap-1 text-[13px] font-medium text-cobalt-text hover:underline">
          Open approvals <ArrowRight className="size-3.5" />
        </Link>
      ) : (
        runId && (
          <Link href={`/runs/${runId}`} className="inline-flex items-center gap-1 text-[13px] font-medium text-cobalt-text hover:underline">
            Trace <ArrowRight className="size-3.5" />
          </Link>
        )
      )}
    </div>
  );
}

/** Opens on click, tap or Enter, and on hover for a mouse (never hover-only). */
function NodePopover({ node, runId, user, children, side = "bottom" }: { node: Node; runId?: string; user?: string | null; children: ReactNode; side?: "bottom" | "right" }) {
  const [open, setOpen] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const hover = (v: boolean) => (e: React.PointerEvent) => {
    if (e.pointerType !== "mouse") return;
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setOpen(v), v ? 220 : 160);
  };
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild onPointerEnter={hover(true)} onPointerLeave={hover(false)}>
        {children}
      </PopoverTrigger>
      <PopoverContent side={side} align="center" label={`${node.name} details`} className="w-[min(320px,calc(100vw-24px))] p-4">
        <div onPointerEnter={hover(true)} onPointerLeave={hover(false)}>
          <NodeDetail node={node} runId={runId} user={user} />
        </div>
      </PopoverContent>
    </Popover>
  );
}

const STATUS_WORD: Record<AgentStatus, string> = { idle: "waiting", off: "skipped", running: "working", done: "done", "your-turn": "waiting for you", error: "stopped" };

/**
 * The crew as a flight path: ten connected avatars on a track that fills as stages complete.
 * ≥1280 the full track · 768–1279 a snap-scrolling track that keeps the active node in view ·
 * under 768 a vertical timeline of the current stage and its neighbours, with "Show full crew".
 */
export function FlightPath({ run, pendingApprovals = 0 }: { run?: Run | null; pendingApprovals?: number }) {
  const { data: me } = useMe();
  const user = me?.name || me?.email;
  const nodes = buildNodes(run, pendingApprovals);
  const focus = focusIndex(nodes);
  const reached = nodes.map((n) => n.status === "done" || n.status === "off").lastIndexOf(true);
  // The line fills to the last finished stage, plus half a segment into a stage that's in progress.
  const fill = Math.max(0, Math.min(1, (reached + (nodes[reached + 1] && nodes[reached + 1].status !== "idle" ? 0.5 : 0)) / (nodes.length - 1)));
  const live = nodes[focus];

  const track = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = track.current;
    const node = el?.querySelector<HTMLElement>(`[data-node="${focus}"]`);
    if (!el || !node || el.scrollWidth <= el.clientWidth) return;
    el.scrollTo({ left: node.offsetLeft - (el.clientWidth - node.offsetWidth) / 2, behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  }, [focus]);

  const [full, setFull] = useState(false);
  const shown = full ? nodes : nodes.filter((n) => Math.abs(n.index - focus) <= 1);

  return (
    <section aria-label="Crew flight path">
      <p className="sr-only" aria-live="polite">
        {run ? `${live.name} is ${STATUS_WORD[live.status]}.` : "The crew hasn’t run yet."}
      </p>

      {/* ≥768: horizontal track */}
      <div
        ref={track}
        className="hidden snap-x snap-mandatory overflow-x-auto overscroll-x-contain pb-1 [scrollbar-width:none] [mask-image:linear-gradient(90deg,transparent,#000_28px,#000_calc(100%-28px),transparent)] md:block xl:overflow-visible xl:[mask-image:none] [&::-webkit-scrollbar]:hidden"
      >
        <ol className="relative flex w-max px-4 xl:grid xl:w-full xl:grid-cols-10 xl:px-0">
          <span aria-hidden className="absolute top-[38px] right-[84px] left-[84px] h-px bg-border-strong xl:right-[5%] xl:left-[5%]">
            <span className="absolute inset-0 origin-left bg-cobalt transition-transform duration-[var(--dur-slow)] ease-[var(--ease)]" style={{ transform: `scaleX(${fill})` }} />
          </span>
          {nodes.map((n) => {
            const isYou = n.key === "you";
            const body = (
              <span className="flex w-full flex-col items-center rounded-[var(--radius-card)] px-1.5 pt-0 pb-2 text-center transition-colors hover:bg-elevated/60">
                <span className="grid h-[76px] place-items-center">
                  <AgentAvatar agent={n.key} status={isYou && n.status === "idle" ? "idle" : n.status} size={isYou ? 76 : 64} user={{ name: user }} decorative />
                </span>
                <span className={cn("mt-2 text-[13px] font-semibold", isYou && n.status === "your-turn" && "text-your-turn")}>{n.name}</span>
                <span className="mt-0.5 line-clamp-1 w-full text-[12px] text-text-3">{n.detail}</span>
                <span className="num mt-0.5 h-4 text-[11px] text-text-3">{n.duration != null ? ms(n.duration) : ""}</span>
              </span>
            );
            return (
              <li key={n.key} data-node={n.index} className="relative w-[136px] shrink-0 snap-center xl:w-auto">
                {isYou ? (
                  <Link href="/approvals" aria-label={`Your turn: ${STATUS_WORD[n.status]}. Open approvals`} className="block rounded-[var(--radius-card)]">
                    {body}
                  </Link>
                ) : (
                  <NodePopover node={n} runId={run?.id} user={user}>
                    <button type="button" aria-label={`${n.name}: ${STATUS_WORD[n.status]}. Show details`} className="block w-full rounded-[var(--radius-card)]">
                      {body}
                    </button>
                  </NodePopover>
                )}
              </li>
            );
          })}
        </ol>
      </div>

      {/* <768: vertical timeline */}
      <div className="md:hidden">
        <ol className="relative">
          <span aria-hidden className="absolute top-6 bottom-6 left-[23px] w-px bg-border-strong" />
          {shown.map((n) => {
            const isYou = n.key === "you";
            const row = (
              <span className="relative flex min-h-14 w-full items-center gap-3 rounded-[var(--radius-card)] py-2 pr-2 text-left">
                <AgentAvatar agent={n.key} status={n.status} size={48} user={{ name: user }} decorative />
                <span className="min-w-0 flex-1">
                  <span className="flex items-center justify-between gap-2">
                    <span className={cn("text-[14px] font-semibold", isYou && n.status === "your-turn" && "text-your-turn")}>{n.name}</span>
                    <span className="num text-[11.5px] text-text-3">{n.duration != null ? ms(n.duration) : ""}</span>
                  </span>
                  <span className="mt-0.5 line-clamp-2 block text-[12.5px] leading-snug text-text-2">{n.detail}</span>
                </span>
              </span>
            );
            return (
              <li key={n.key}>
                {isYou ? (
                  <Link href="/approvals" aria-label={`Your turn: ${STATUS_WORD[n.status]}. Open approvals`} className="block rounded-[var(--radius-card)]">
                    {row}
                  </Link>
                ) : (
                  <NodePopover node={n} runId={run?.id} user={user}>
                    <button type="button" aria-label={`${n.name}: ${STATUS_WORD[n.status]}. Show details`} className="block w-full rounded-[var(--radius-card)]">
                      {row}
                    </button>
                  </NodePopover>
                )}
              </li>
            );
          })}
        </ol>
        <button
          type="button"
          onClick={() => setFull((v) => !v)}
          aria-expanded={full}
          className="mt-1 flex h-11 w-full items-center justify-center gap-1.5 rounded-[var(--radius-control)] text-[13px] font-medium text-text-2 hover:bg-elevated hover:text-text"
        >
          {full ? "Show current stage" : "Show full crew"}
          <ChevronDown className={cn("size-4 transition-transform duration-[var(--dur-fast)]", full && "rotate-180")} />
        </button>
      </div>
    </section>
  );
}

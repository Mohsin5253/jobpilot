"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import type { AgentStatus } from "@/components/agents/agent-avatar";
import { FLIGHT_PATH, type CrewKey } from "@/config/agents";
import type { Run } from "@/lib/types";

/**
 * One run state for the whole page. Every AgentAvatar that isn't given an explicit status follows it,
 * so a character anywhere (an empty state, a popover, the landing carousel) plays its part in the run.
 */
export type CrewStatusMap = Partial<Record<CrewKey, AgentStatus>>;

const CrewStatusCtx = createContext<CrewStatusMap | null>(null);
const DemoStepCtx = createContext<{ step: CrewKey | null; phase: "running" | "finished" | "idle"; running: CrewKey[] }>({ step: null, phase: "idle", running: [] });

export function CrewStatusProvider({ value, children }: { value: CrewStatusMap; children: ReactNode }) {
  return <CrewStatusCtx.Provider value={value}>{children}</CrewStatusCtx.Provider>;
}

export const useCrewStatus = (k: CrewKey): AgentStatus | undefined => useContext(CrewStatusCtx)?.[k];
export const useCrewStatuses = () => useContext(CrewStatusCtx);
export const useDemoStep = () => useContext(DemoStepCtx);

const STEP: Record<string, AgentStatus> = { completed: "done", running: "running", waiting: "your-turn", failed: "error", skipped: "off" };

/** The crew's state from the latest real run (and drafts waiting on you). */
export function statusesFromRun(run: Run | null | undefined, pendingApprovals: number): CrewStatusMap {
  const map: CrewStatusMap = {};
  if (!run) {
    if (pendingApprovals > 0) map.you = "your-turn";
    return map;
  }
  for (const k of FLIGHT_PATH) {
    const step = run.steps.find((s) => s.agent === (k === "you" ? "approval" : k));
    map[k] = step ? (STEP[step.status] ?? "idle") : "idle";
  }
  if (pendingApprovals > 0) map.you = "your-turn";
  const active = run.status === "running" || run.status === "queued" || run.status === "resume_queued";
  map.pilot = run.status === "failed" ? "error" : active ? "running" : pendingApprovals > 0 || run.status === "awaiting_approval" ? "your-turn" : "done";
  return map;
}

const STAGE_MS = 1700;
const YOUR_TURN_MS = 3000;
const FINISHED_MS = 2600;
const IDLE_MS = 1400;

/**
 * The demo run plays the real run's parallel lanes (see backend agents/graph.py): the Researcher works alongside the
 * Scout → Verifier → Matcher lane; then the Interviewer, the Tailor and the Tracker run together; then Outreach,
 * your approval and Dispatch. `lead` is the main-lane agent each phase is captioned by.
 */
const DEMO_PHASES: { lead: CrewKey; running: CrewKey[] }[] = [
  { lead: "scout", running: ["researcher", "scout"] },
  { lead: "verifier", running: ["researcher", "verifier"] },
  { lead: "matcher", running: ["researcher", "matcher"] },
  { lead: "tailor", running: ["interviewer", "tailor", "tracker"] },
  { lead: "outreach", running: ["outreach"] },
  { lead: "you", running: ["you"] },
  { lead: "dispatch", running: ["dispatch"] },
];

/**
 * The landing page's demo run, on a loop; every character on the page plays along.
 */
export function DemoRunProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ i: number; phase: "running" | "finished" | "idle" }>({ i: -1, phase: "idle" });

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    const next = (i: number) => {
      if (i >= DEMO_PHASES.length) {
        setState({ i, phase: "finished" });
        timer = setTimeout(() => {
          setState({ i: -1, phase: "idle" });
          timer = setTimeout(() => next(0), IDLE_MS);
        }, FINISHED_MS);
        return;
      }
      setState({ i, phase: "running" });
      timer = setTimeout(() => next(i + 1), DEMO_PHASES[i].lead === "you" ? YOUR_TURN_MS : STAGE_MS);
    };
    timer = setTimeout(() => next(0), 2200); // let the stage's intro play first
    return () => clearTimeout(timer);
  }, []);

  const map: CrewStatusMap = {};
  const now = state.phase === "running" ? DEMO_PHASES[state.i].running : [];
  const before = new Set(state.phase === "finished" ? DEMO_PHASES.flatMap((p) => p.running) : DEMO_PHASES.slice(0, Math.max(0, state.i)).flatMap((p) => p.running));
  FLIGHT_PATH.forEach((k) => {
    map[k] = state.phase === "idle" ? "idle" : now.includes(k) ? (k === "you" ? "your-turn" : "running") : before.has(k) ? "done" : "idle";
  });
  const step = state.phase === "running" ? DEMO_PHASES[state.i].lead : null;
  map.pilot = state.phase === "running" ? (step === "you" ? "your-turn" : "running") : state.phase === "finished" ? "done" : "idle";

  return (
    <DemoStepCtx.Provider value={{ step, phase: state.phase, running: now }}>
      <CrewStatusProvider value={map}>{children}</CrewStatusProvider>
    </DemoStepCtx.Provider>
  );
}

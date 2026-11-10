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
const DemoStepCtx = createContext<{ step: CrewKey | null; phase: "running" | "finished" | "idle" }>({ step: null, phase: "idle" });

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
 * The landing page's demo run: the crew works through the pipeline in a loop (Researcher → … → your turn
 * → Dispatch → Tracker), and every character on the page plays along.
 */
export function DemoRunProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ i: number; phase: "running" | "finished" | "idle" }>({ i: -1, phase: "idle" });

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    const next = (i: number) => {
      if (i >= FLIGHT_PATH.length) {
        setState({ i, phase: "finished" });
        timer = setTimeout(() => {
          setState({ i: -1, phase: "idle" });
          timer = setTimeout(() => next(0), IDLE_MS);
        }, FINISHED_MS);
        return;
      }
      setState({ i, phase: "running" });
      timer = setTimeout(() => next(i + 1), FLIGHT_PATH[i] === "you" ? YOUR_TURN_MS : STAGE_MS);
    };
    timer = setTimeout(() => next(0), 2200); // let the stage's intro play first
    return () => clearTimeout(timer);
  }, []);

  const map: CrewStatusMap = {};
  FLIGHT_PATH.forEach((k, idx) => {
    map[k] = state.phase === "idle" ? "idle" : idx < state.i ? "done" : idx === state.i ? (k === "you" ? "your-turn" : "running") : "idle";
  });
  const step = state.phase === "running" ? FLIGHT_PATH[state.i] : null;
  map.pilot = state.phase === "running" ? (step === "you" ? "your-turn" : "running") : state.phase === "finished" ? "done" : "idle";

  return (
    <DemoStepCtx.Provider value={{ step, phase: state.phase }}>
      <CrewStatusProvider value={map}>{children}</CrewStatusProvider>
    </DemoStepCtx.Provider>
  );
}

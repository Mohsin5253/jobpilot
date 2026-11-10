"use client";

import { useEffect, useRef, useState } from "react";

import { useCrewStatuses } from "@/components/agents/crew-status";
import { AGENTS, headOf, type AgentKey } from "@/config/agents";
import type { Crew3DStatus } from "@/lib/crew3d/material";
import type { StageActorSpec } from "@/lib/crew3d/stage";
import { cn } from "@/lib/utils";

type Spot = [AgentKey, number, number, number, number];

/** The group on the stage: Pilot in front, the crew fanning back on either side. [agent, x, y, z, height] */
const WIDE: Spot[] = [
  ["researcher", -2.05, 0.2, -1.1, 0.82],
  ["tailor", 2.05, 0.2, -1.1, 0.82],
  ["scout", -1.45, 0.14, -0.55, 0.88],
  ["outreach", 1.45, 0.14, -0.55, 0.88],
  ["verifier", -0.78, 0.08, 0, 0.95],
  ["matcher", 0.78, 0.08, 0, 0.95],
  ["pilot", 0, 0.02, 0.5, 1.15],
];
const NARROW: Spot[] = [
  ["scout", -1.05, 0.14, -0.6, 0.86],
  ["outreach", 1.05, 0.14, -0.6, 0.86],
  ["verifier", -0.6, 0.08, -0.05, 0.92],
  ["matcher", 0.6, 0.08, -0.05, 0.92],
  ["pilot", 0, 0.02, 0.5, 1.12],
];

const spec = ([key, x, y, z, scale]: Spot): StageActorSpec => ({
  key,
  pos: [x, y, z],
  scale,
  source: { color: AGENTS[key].images, depth: AGENTS[key].depth, mask: AGENTS[key].mask, head: headOf(key) },
});

/**
 * The crew in one 3D scene. It draws over a poster (the still group shot), which stays as the loading
 * state and the fallback. Statuses come from the page's shared run, so the stage and every other
 * character on the page move together.
 */
export default function CrewStage({ className, onReady }: { className?: string; onReady?: () => void }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const handle = useRef<import("@/lib/crew3d/stage").StageHandle | null>(null);
  const statuses = useCrewStatuses();
  const latest = useRef(statuses);
  latest.current = statuses;
  const [ready, setReady] = useState(false);
  const ready$ = useRef(onReady);
  ready$.current = onReady;

  useEffect(() => {
    let cancelled = false;
    const narrow = matchMedia("(max-width: 767px)").matches;
    import("@/lib/crew3d/stage").then(({ mountStage }) => {
      if (cancelled || !canvas.current) return;
      handle.current = mountStage(canvas.current, (narrow ? NARROW : WIDE).map(spec), () => {
        setReady(true);
        ready$.current?.();
      });
      handle.current?.setStatuses((latest.current ?? {}) as Record<string, Crew3DStatus>);
    });
    return () => {
      cancelled = true;
      handle.current?.destroy();
      handle.current = null;
    };
  }, []);

  const key = JSON.stringify(statuses ?? {});
  useEffect(() => {
    handle.current?.setStatuses((statuses ?? {}) as Record<string, Crew3DStatus>);
    // Re-run only when a status actually changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return (
    <canvas
      ref={canvas}
      aria-hidden
      className={cn("stage-feather absolute inset-0 size-full transition-opacity duration-[var(--dur-slow)]", ready ? "opacity-100" : "opacity-0", className)}
    />
  );
}

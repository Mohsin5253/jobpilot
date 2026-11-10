"use client";

import { useEffect, useRef } from "react";

import { AGENTS, headOf, type AgentKey } from "@/config/agents";
import { mountCrew3D, type Crew3DStatus } from "@/lib/crew3d/engine";
import { cn } from "@/lib/utils";

/**
 * A crew member in 3D, drawn over its still render. It stays invisible until its textures are on the GPU,
 * then fades in, so the still image is the loading state and the fallback.
 */
export default function Agent3D({ agent, status, className, onReady }: { agent: AgentKey; status: Crew3DStatus; className?: string; onReady?: () => void }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const handle = useRef<ReturnType<typeof mountCrew3D>>(null);
  const ready = useRef(onReady);
  ready.current = onReady;

  useEffect(() => {
    if (!canvas.current) return;
    const cfg = AGENTS[agent];
    handle.current = mountCrew3D(canvas.current, {
      source: { color: cfg.images, depth: cfg.depth, head: headOf(agent) },
      status,
      onReady: () => {
        canvas.current?.setAttribute("data-ready", "");
        ready.current?.();
      },
    });
    return () => {
      handle.current?.destroy();
      handle.current = null;
    };
    // Mount once per agent; status changes are played on the live character below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agent]);

  useEffect(() => {
    handle.current?.setStatus(status);
  }, [status]);

  return <canvas ref={canvas} aria-hidden className={cn("absolute inset-0 size-full opacity-0 transition-opacity duration-[var(--dur-slow)] data-[ready]:opacity-100", className)} />;
}

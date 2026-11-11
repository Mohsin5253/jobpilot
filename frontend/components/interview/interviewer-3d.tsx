"use client";

import Image from "next/image";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";

import { INTERVIEWERS, type InterviewerKey } from "@/components/interview/interviewers";
import { AGENTS, headOf } from "@/config/agents";
import { crew3DSupported } from "@/lib/crew3d/support";
import type { Talker } from "@/lib/crew3d/talker";
import { cn } from "@/lib/utils";

export type InterviewerHandle = Pick<Talker, "speakStart" | "speakWord" | "speakEnd" | "listen" | "nod">;

/** The interviewer as a 3D talking head over their still portrait (the portrait is the loading state and fallback). */
export const Interviewer3D = forwardRef<InterviewerHandle, { who: InterviewerKey; speaking?: boolean; className?: string }>(function Interviewer3D({ who, speaking, className }, ref) {
  const iv = INTERVIEWERS[who];
  const cfg = AGENTS[iv.agent];
  const canvas = useRef<HTMLCanvasElement>(null);
  const talker = useRef<Talker | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!canvas.current || !crew3DSupported()) return;
    let cancelled = false;
    import("@/lib/crew3d/talker").then(({ mountTalker }) => {
      if (cancelled || !canvas.current) return;
      talker.current = mountTalker(canvas.current, { color: cfg.images, depth: cfg.depth, head: headOf(iv.agent) }, iv.mouth, () => setReady(true));
    });
    return () => {
      cancelled = true;
      talker.current?.destroy();
      talker.current = null;
      setReady(false);
    };
  }, [who, cfg.images, cfg.depth, iv.agent, iv.mouth]);

  useImperativeHandle(ref, () => ({
    speakStart: () => talker.current?.speakStart(),
    speakWord: () => talker.current?.speakWord(),
    speakEnd: () => talker.current?.speakEnd(),
    listen: (on: boolean) => talker.current?.listen(on),
    nod: () => talker.current?.nod(),
  }));

  return (
    <div className={cn("relative aspect-square overflow-hidden rounded-[var(--radius-card)] bg-[#0b0d12]", className)}>
      <Image src={cfg.images.idle} alt={`${iv.name}, ${iv.role}`} fill sizes="(min-width: 1024px) 460px, 100vw" className={cn("object-cover transition-opacity duration-[var(--dur-slow)]", ready && "opacity-0")} priority />
      <canvas ref={canvas} aria-hidden className={cn("absolute inset-0 size-full transition-opacity duration-[var(--dur-slow)]", ready ? "opacity-100" : "opacity-0")} />
      <div className="absolute inset-x-0 bottom-0 flex items-center justify-between gap-2 bg-gradient-to-t from-black/75 to-transparent p-3 pt-10 text-white">
        <div>
          <div className="text-[14px] font-semibold">{iv.name}</div>
          <div className="text-[12px] text-white/75">{iv.role}</div>
        </div>
        {speaking && (
          <span className="flex items-end gap-0.5" aria-label="Speaking">
            {[0, 1, 2, 3].map((i) => (
              <span key={i} className="w-1 animate-pulse rounded-full bg-white/85" style={{ height: 6 + ((i * 5) % 11), animationDelay: `${i * 120}ms` }} />
            ))}
          </span>
        )}
      </div>
    </div>
  );
});

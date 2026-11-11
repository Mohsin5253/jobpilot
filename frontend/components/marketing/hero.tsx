"use client";

import { ArrowRight, Play } from "lucide-react";
import { useReducedMotion } from "motion/react";
import dynamic from "next/dynamic";
import Image from "next/image";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { useDemoStep } from "@/components/agents/crew-status";
import { RUN_STAGES } from "@/components/marketing/crew-copy";
import { Button, buttonClass } from "@/components/ui/button";
import { AGENTS, CREW_HERO, FLIGHT_PATH } from "@/config/agents";
import { crew3DSupported } from "@/lib/crew3d/support";
import { useStartDemo } from "@/lib/demo";
import { cn } from "@/lib/utils";

// Three.js and the stage load after first paint; the still group shot is the poster meanwhile.
const CrewStage = dynamic(() => import("@/components/marketing/crew-stage"), { ssr: false });

/** Drifts the crew shot up to 8px toward the pointer (mouse only, and never with reduced motion). */
function useParallax() {
  const ref = useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();
  useEffect(() => {
    const el = ref.current;
    if (!el || reduce || !matchMedia("(pointer: fine) and (min-width: 1024px)").matches) return;
    let frame = 0;
    const onMove = (e: PointerEvent) => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const x = (e.clientX / innerWidth - 0.5) * 16;
        const y = (e.clientY / innerHeight - 0.5) * 10;
        el.style.transform = `translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, 0) scale(1.03)`;
      });
    };
    window.addEventListener("pointermove", onMove, { passive: true });
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("pointermove", onMove);
    };
  }, [reduce]);
  return ref;
}

/** The crew on a track, following the demo run: the line fills, the current stage's avatar works, and a caption says what's happening. */
function MiniFlightPath({ className }: { className?: string }) {
  const { step, phase, running } = useDemoStep();
  const i = step ? FLIGHT_PATH.indexOf(step) : phase === "finished" ? FLIGHT_PATH.length - 1 : -1;
  const fill = i < 0 ? 0 : i / (FLIGHT_PATH.length - 1);
  const name = step === "you" ? "Your turn" : step ? AGENTS[step].name : null;
  const together = running.filter((k) => k !== "you").map((k) => AGENTS[k as keyof typeof AGENTS].name);
  return (
    <div className={cn("relative", className)}>
      <div aria-hidden className="relative">
        <span className="absolute inset-x-[14px] top-1/2 h-px -translate-y-1/2 bg-border-strong">
          <span className="absolute inset-0 origin-left bg-cobalt shadow-[0_0_10px_var(--cobalt)] transition-transform duration-[var(--dur-slow)] ease-[var(--ease)]" style={{ transform: `scaleX(${fill})` }} />
        </span>
        <div className="relative flex justify-between">
          {FLIGHT_PATH.map((k) => (
            <AgentAvatar key={k} agent={k} size={28} user={{ name: "You" }} decorative />
          ))}
        </div>
      </div>
      <p aria-live="polite" className="mt-3 min-h-10 text-center text-[13px] leading-snug text-text-2">
        {phase === "finished" ? (
          <span className="text-text">Run complete. Nothing was sent without your approval.</span>
        ) : together.length > 1 ? (
          <>
            <span className="font-medium text-text">{together.join(" + ")}</span> · working in parallel
          </>
        ) : name && step ? (
          <>
            <span className="font-medium text-text">{name}</span> · {RUN_STAGES[step].slice(RUN_STAGES[step].startsWith(name) ? name.length : 0).replace(/^[.\s]+/, "")}
          </>
        ) : (
          "The crew is getting ready…"
        )}
      </p>
    </div>
  );
}

/**
 * Hero: the crew group shot is the page's one large character moment. It's always shown on graphite,
 * in both themes, because that's what the renders are lit for.
 */
export function Hero({ costPerRun }: { costPerRun: string | null }) {
  const demo = useStartDemo();
  const parallax = useParallax();
  const [stage, setStage] = useState(false);
  const [stageReady, setStageReady] = useState(false);
  useEffect(() => setStage(crew3DSupported()), []);
  const image = (
    <Image
      src={CREW_HERO.src}
      alt={CREW_HERO.alt}
      width={CREW_HERO.width}
      height={CREW_HERO.height}
      priority
      sizes="(min-width: 1024px) 760px, 100vw"
      className="size-full object-cover object-[95%_30%]"
    />
  );
  return (
    <section className="dark relative isolate overflow-hidden bg-bg text-text">
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(800px_480px_at_78%_40%,color-mix(in_oklab,var(--cobalt)_16%,transparent),transparent_70%)]" />
      <div className="mx-auto grid max-w-[1200px] items-center gap-8 px-4 pt-12 md:px-6 md:pt-16 lg:min-h-[min(720px,calc(100dvh-64px))] lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-4 lg:py-12">
        <div className="relative z-10 max-w-[600px]">
          <div className="eyebrow mb-5 flex items-center gap-2 text-cobalt-text">
            <span className="rounded-full border border-[color-mix(in_oklab,var(--cobalt)_40%,transparent)] px-2 py-0.5 text-[11px]">Beta</span>
            Internship agent for students in India
          </div>
          <h1 className="font-display text-[clamp(40px,5.6vw,68px)] leading-[1.02]">
            Real internships. Zero scams. <span className="text-cobalt-text">Every application approved by you.</span>
          </h1>
          <p className="mt-6 max-w-[540px] text-[17px] leading-relaxed text-text-2">
            JobPilot finds real internships, blocks the scams, and sends only applications you approve, each one backed by proof a recruiter can check.
          </p>
          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <Link href="/scam-check" className={buttonClass({ variant: "primary", size: "lg", className: "w-full sm:w-auto" })}>
              Check an offer for scams (free) <ArrowRight />
            </Link>
            <Button size="lg" className="w-full sm:w-auto" onClick={demo.start} loading={demo.loading}>
              {!demo.loading && <Play className="fill-current" />} Watch the crew work
            </Button>
          </div>
          <p className="mt-3 text-[12.5px] text-text-3">
            No sign-up for either. Ready to apply?{" "}
            <Link href="/register" className="text-cobalt-text hover:underline">
              Start free
            </Link>
            .
          </p>
          <ul className="mt-8 flex flex-wrap gap-x-5 gap-y-2 text-[13px] text-text-2">
            {["Nothing sent without your approval", "Never automates LinkedIn", costPerRun ? `${costPerRun} average AI cost per run` : "Exact ₹ cost on every run"].map((t) => (
              <li key={t} className="flex items-center gap-2">
                <span aria-hidden className="size-1.5 rounded-full bg-cobalt" />
                {t}
              </li>
            ))}
          </ul>
        </div>

        <div className="relative -mx-4 md:-mx-6 lg:mx-0 lg:-mr-12">
          {/* The crew as a live 3D stage; the still group shot (feathered into the page) is its poster and fallback. */}
          <div className="relative aspect-[4/3] lg:aspect-[1.2]">
            <div className={cn("hero-feather absolute inset-0 overflow-hidden transition-opacity duration-[var(--dur-slow)]", stageReady && "opacity-0")}>
              <div ref={parallax} className="size-full transition-transform duration-[var(--dur-slow)] ease-[var(--ease)] will-change-transform">
                {image}
              </div>
            </div>
            {stage && <CrewStage onReady={() => setStageReady(true)} />}
          </div>
          <MiniFlightPath className="mx-auto mt-2 w-[min(92%,520px)] pb-10 lg:pb-0" />
        </div>
      </div>
    </section>
  );
}

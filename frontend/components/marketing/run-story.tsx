"use client";

import { useInView, useMotionValueEvent, useReducedMotion, useScroll } from "motion/react";
import { useRef, useState } from "react";

import { AgentAvatar, type AgentStatus } from "@/components/agents/agent-avatar";
import { RUN_STAGES } from "@/components/marketing/crew-copy";
import { AGENTS, FLIGHT_PATH, type CrewKey } from "@/config/agents";
import { useMediaQuery } from "@/lib/use-media";
import { cn } from "@/lib/utils";

const name = (k: CrewKey) => (k === "you" ? "Your turn" : AGENTS[k].name);
const statusAt = (i: number, active: number): AgentStatus => (i < active ? "done" : i === active ? (FLIGHT_PATH[i] === "you" ? "your-turn" : "running") : "idle");

const Header = () => (
  <div className="max-w-[640px]">
    <div className="eyebrow mb-3">How a run works</div>
    <h2 className="font-display text-[clamp(32px,4.4vw,52px)] leading-[1.04]">From job boards to your outbox, with you in the middle.</h2>
    <p className="mt-4 text-[16px] leading-relaxed text-text-2">A run takes a couple of minutes. Every step is logged with its cost and timing, so you can see exactly what happened.</p>
  </div>
);

/** Desktop: the section pins, and scrolling advances the run one stage at a time. */
function Pinned() {
  const section = useRef<HTMLElement>(null);
  const [active, setActive] = useState(0);
  const { scrollYProgress } = useScroll({ target: section, offset: ["start start", "end end"] });
  useMotionValueEvent(scrollYProgress, "change", (p) => setActive(Math.min(FLIGHT_PATH.length - 1, Math.max(0, Math.floor(p * FLIGHT_PATH.length)))));
  const fill = active / (FLIGHT_PATH.length - 1);
  const k = FLIGHT_PATH[active];
  return (
    <section id="how" ref={section} aria-label="How a run works" className="relative h-[260vh] scroll-mt-16">
      <div className="sticky top-16 flex h-[calc(100dvh-64px)] items-center">
        <div className="mx-auto w-full max-w-[1200px] px-6">
          <Header />
          <ol className="relative mt-14 grid grid-cols-10">
            <span aria-hidden className="absolute top-[38px] right-[5%] left-[5%] h-px bg-border-strong">
              <span className="absolute inset-0 origin-left bg-cobalt transition-transform duration-[var(--dur-slow)] ease-[var(--ease)]" style={{ transform: `scaleX(${fill})` }} />
            </span>
            {FLIGHT_PATH.map((key, i) => (
              <li key={key} className="relative flex flex-col items-center text-center">
                <span className="grid h-[76px] place-items-center">
                  <AgentAvatar agent={key} status={statusAt(i, active)} size={key === "you" ? 76 : 64} user={{ name: "You" }} decorative />
                </span>
                <span className={cn("mt-2 text-[13px] font-semibold transition-colors", i <= active ? "text-text" : "text-text-3", key === "you" && i === active && "text-your-turn")}>{name(key)}</span>
              </li>
            ))}
          </ol>
          <div className="mt-10 flex min-h-24 items-start gap-4 rounded-[var(--radius-card)] border border-border bg-surface p-5" aria-live="polite">
            <span className="num text-[13px] text-text-3">{String(active + 1).padStart(2, "0")}/{String(FLIGHT_PATH.length).padStart(2, "0")}</span>
            <div>
              <div className="text-[15px] font-semibold">{name(k)}</div>
              <p className="mt-1 text-[14.5px] leading-relaxed text-text-2">{RUN_STAGES[k]}</p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

/** Phones: a vertical timeline; each stage lights up as it crosses the middle of the screen. */
function Row({ k, last }: { k: CrewKey; last: boolean }) {
  const ref = useRef<HTMLLIElement>(null);
  const centred = useInView(ref, { margin: "-42% 0px -42% 0px" });
  const passed = useInView(ref, { margin: "0px 0px -58% 0px" });
  const status: AgentStatus = centred ? (k === "you" ? "your-turn" : "running") : passed ? "done" : "idle";
  return (
    <li ref={ref} className="relative flex gap-4 pb-8">
      {!last && <span aria-hidden className={cn("absolute top-14 bottom-0 left-[27px] w-px transition-colors duration-[var(--dur-slow)]", passed ? "bg-cobalt" : "bg-border-strong")} />}
      <AgentAvatar agent={k} status={status} size={56} user={{ name: "You" }} decorative />
      <div className="min-w-0 pt-1.5">
        <div className={cn("text-[15px] font-semibold", k === "you" && centred && "text-your-turn")}>{name(k)}</div>
        <p className="mt-1 text-[14px] leading-relaxed text-text-2">{RUN_STAGES[k]}</p>
      </div>
    </li>
  );
}

function Timeline() {
  return (
    <section id="how" aria-label="How a run works" className="mx-auto max-w-[1200px] scroll-mt-16 px-4 py-20 md:px-6 md:py-28">
      <Header />
      <ol className="mt-10">
        {FLIGHT_PATH.map((k, i) => (
          <Row key={k} k={k} last={i === FLIGHT_PATH.length - 1} />
        ))}
      </ol>
    </section>
  );
}

export function RunStory() {
  const desktop = useMediaQuery("(min-width: 1024px)");
  const reduce = useReducedMotion();
  return desktop && !reduce ? <Pinned /> : <Timeline />;
}

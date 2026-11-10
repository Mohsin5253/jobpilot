"use client";

import { motion, useReducedMotion, useScroll, useTransform } from "motion/react";
import { useEffect, useRef, useState } from "react";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { CREW_STORY } from "@/components/marketing/crew-copy";
import { AGENTS } from "@/config/agents";
import { useMediaQuery } from "@/lib/use-media";

function CrewCard({ k, job, sample, i }: { k: (typeof CREW_STORY)[number]["key"]; job: string; sample: string; i: number }) {
  const a = AGENTS[k];
  return (
    <article className="card flex h-full w-[min(300px,78vw)] shrink-0 snap-start flex-col overflow-hidden lg:w-[340px]">
      <div className="relative grid place-items-center pt-6 pb-2" style={{ background: `radial-gradient(70% 80% at 50% 30%, color-mix(in oklab, ${a.tint} 16%, transparent), transparent 75%)` }}>
        <span className="num absolute top-4 left-4 text-[12px] text-text-3">{String(i + 1).padStart(2, "0")}</span>
        <AgentAvatar agent={k} size={200} decorative />
      </div>
      <div className="flex flex-1 flex-col p-5 pt-4">
        <h3 className="text-[18px] font-semibold tracking-[-0.02em]">{a.name}</h3>
        <div className="text-[13px] text-text-3">{a.role}</div>
        <p className="mt-3 text-[14px] leading-relaxed text-text-2">{job}</p>
        <div className="num mt-auto rounded-[var(--radius-control)] border border-border bg-elevated px-3 py-2.5 text-[12px] leading-relaxed text-text-2">
          <span className="mr-1.5 text-cobalt-text">›</span>
          {sample}
        </div>
      </div>
    </article>
  );
}

const Header = () => (
  <div className="mb-8 max-w-[640px] md:mb-10">
    <div className="eyebrow mb-3">Meet the crew</div>
    <h2 className="font-display text-[clamp(32px,4.4vw,52px)] leading-[1.04]">Ten specialists. One job each.</h2>
    <p className="mt-4 text-[16px] leading-relaxed text-text-2">Pilot leads, nine agents do the work, and you’re the final member of the crew. Sample outputs are illustrative.</p>
  </div>
);

/** Desktop: the section pins and vertical scroll walks the crew past horizontally. */
function Pinned() {
  const section = useRef<HTMLElement>(null);
  const track = useRef<HTMLDivElement>(null);
  const [shift, setShift] = useState(0);
  useEffect(() => {
    const el = track.current;
    if (!el) return;
    const measure = () => setShift(Math.max(0, el.scrollWidth - el.parentElement!.clientWidth));
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const { scrollYProgress } = useScroll({ target: section, offset: ["start start", "end end"] });
  const x = useTransform(scrollYProgress, [0.08, 0.92], [0, -shift]);
  return (
    <section id="crew" ref={section} aria-label="Meet the crew" className="relative scroll-mt-16" style={{ height: `calc(100dvh + ${shift}px)` }}>
      <div className="sticky top-16 flex h-[calc(100dvh-64px)] flex-col justify-center overflow-hidden">
        <div className="mx-auto w-full max-w-[1200px] px-6">
          <Header />
          <div className="overflow-visible">
            <motion.div ref={track} style={{ x }} className="flex w-max gap-4">
              {CREW_STORY.map((c, i) => (
                <CrewCard key={c.key} k={c.key} job={c.job} sample={c.sample} i={i} />
              ))}
            </motion.div>
          </div>
        </div>
      </div>
    </section>
  );
}

/** Phones, tablets and reduced motion: a swipeable snap carousel. */
function Carousel() {
  return (
    <section id="crew" aria-label="Meet the crew" className="mx-auto max-w-[1200px] scroll-mt-16 px-4 py-20 md:px-6 md:py-28">
      <Header />
      <div className="-mx-4 flex snap-x snap-mandatory scroll-px-4 gap-3 overflow-x-auto px-4 pb-2 [scrollbar-width:none] md:-mx-6 md:scroll-px-6 md:px-6 [&::-webkit-scrollbar]:hidden">
        {CREW_STORY.map((c, i) => (
          <CrewCard key={c.key} k={c.key} job={c.job} sample={c.sample} i={i} />
        ))}
      </div>
      <p className="mt-3 text-[12.5px] text-text-3 lg:hidden">Swipe to meet everyone →</p>
    </section>
  );
}

export function CrewStory() {
  const desktop = useMediaQuery("(min-width: 1024px)");
  const reduce = useReducedMotion();
  return desktop && !reduce ? <Pinned /> : <Carousel />;
}

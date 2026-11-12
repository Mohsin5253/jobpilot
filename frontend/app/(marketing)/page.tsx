import type { Metadata } from "next";

import { DemoRunProvider } from "@/components/agents/crew-status";
import { BetaCounters } from "@/components/marketing/beta-counters";
import { CrewStory } from "@/components/marketing/crew-story";
import { Hero } from "@/components/marketing/hero";
import { RunStory } from "@/components/marketing/run-story";
import { Campus, Control, Credibility, Faq, FinalCta, Honesty, InterviewReady, Outcomes, Pricing, Safety, TraceSample, WhatsNew } from "@/components/marketing/sections";
import { formatInr, getPublicStats } from "@/lib/server-api";

export const metadata: Metadata = { alternates: { canonical: "/" } };

// Rebuilt at most every five minutes, so the live counters stay fresh and the page is still served from cache.
export const revalidate = 300;

/**
 * Landing: hero → live beta counters → what's new → safety → honesty → control → credibility → interview-ready (resume & ATS,
 * mock interviews, one-click apply) → outcomes →
 * how it works (crew, run, trace) → pricing → campus → FAQ → CTA.
 */
export default async function LandingPage() {
  const stats = await getPublicStats();
  const cost = stats?.avg_cost_inr_per_run != null ? formatInr(stats.avg_cost_inr_per_run) : null;
  return (
    // A demo run plays on a loop, and every character on the page (the 3D stage, the crew cards) follows it.
    <DemoRunProvider>
      <Hero costPerRun={cost} />
      <BetaCounters stats={stats} />
      <WhatsNew />
      <Safety />
      <Honesty />
      <Control />
      <Credibility />
      <InterviewReady />
      <Outcomes />
      <CrewStory />
      <RunStory />
      <TraceSample costPerRun={cost} />
      <Pricing />
      <Campus />
      <Faq costPerRun={cost} />
      <FinalCta />
    </DemoRunProvider>
  );
}

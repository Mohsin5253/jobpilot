import { DemoRunProvider } from "@/components/agents/crew-status";
import { CrewStory } from "@/components/marketing/crew-story";
import { Hero } from "@/components/marketing/hero";
import { RunStory } from "@/components/marketing/run-story";
import { Bento, Campus, Control, Faq, FinalCta, Pricing, Stories } from "@/components/marketing/sections";

/** Landing: hero (crew group shot) → crew → how a run works → control → product → campus → stories → pricing → FAQ → CTA. */
export default function LandingPage() {
  return (
    // A demo run plays on a loop, and every character on the page (the 3D stage, the crew cards) follows it.
    <DemoRunProvider>
      <Hero />
      <CrewStory />
      <RunStory />
      <Control />
      <Bento />
      <Campus />
      <Stories />
      <Pricing />
      <Faq />
      <FinalCta />
    </DemoRunProvider>
  );
}

import type { Metadata } from "next";

import { CampusEnquiry, CampusPlans } from "@/components/marketing/campus-pricing";
import { CAMPUS_FAQ, CAMPUS_TERMS } from "@/lib/campus-pricing";

export const metadata: Metadata = {
  title: "Campus pricing",
  description: "JobPilot for placement cells: staff roles for TPOs, HODs and faculty, a live placement pipeline, AI match proposals you approve, and drives with eligibility checks. From ₹4,999 a year per department; free pilot for one season.",
  alternates: { canonical: "/campus-pricing" },
};

const HOW = [
  { t: "Import your roster; students claim it", d: "Your records (name, roll no., programme, score) are yours to see in scope. What students add in JobPilot appears by name only if they share it." },
  { t: "Unlimited verified staff", d: "Staff code + college email + your approval. HODs see their department, faculty their batches, the TPO the whole college. Every staff view is logged." },
  { t: "Post a job, get ranked students", d: "Paste a recruiter's link and description. JobPilot ranks your students for it and proposes the best fits." },
  { t: "Approve, then track every round", d: "Approved students are shortlisted and told. Move them through Round 1, Technical, HR to Placed; dashboards update live." },
];

export default async function CampusPricingPage({ searchParams }: { searchParams: Promise<{ plan?: string }> }) {
  const { plan } = await searchParams;
  return (
    <div className="mx-auto max-w-[1180px] px-4 py-14 sm:px-6">
      <header className="mx-auto max-w-[760px] text-center">
        <p className="eyebrow">For placement cells</p>
        <h1 className="mt-3 text-[34px] leading-tight font-semibold tracking-[-0.02em] sm:text-[44px]">Run your college&rsquo;s placements in one place</h1>
        <p className="mt-4 text-[16px] text-text-2">TPOs, HODs and faculty track every sharing student&rsquo;s applications live, approve the AI&rsquo;s job matches, and move students through each round to placed.</p>
      </header>

      <section className="mt-12" aria-label="Plans">
        <CampusPlans />
        <p className="mt-4 text-center text-[12.5px] text-text-3">Flat yearly prices, GST extra. The Pilot needs no payment details.</p>
      </section>

      <section className="mt-12" aria-labelledby="terms">
        <h2 id="terms" className="text-center text-[24px] font-semibold">Terms, in plain words</h2>
        <ul className="mx-auto mt-5 grid max-w-[920px] gap-2.5 sm:grid-cols-2">
          {CAMPUS_TERMS.map((t) => (
            <li key={t} className="card p-4 text-[13.5px] text-text-2">
              {t}
            </li>
          ))}
        </ul>
      </section>

      <section className="mt-16" aria-labelledby="how">
        <h2 id="how" className="text-center text-[24px] font-semibold">How it works</h2>
        <ol className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {HOW.map((h, i) => (
            <li key={h.t} className="card p-5">
              <div className="num text-[13px] text-cobalt-text">{i + 1}</div>
              <div className="mt-1 font-medium">{h.t}</div>
              <p className="mt-1.5 text-[13.5px] text-text-2">{h.d}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="mt-16 grid gap-8 lg:grid-cols-[1fr_1.1fr]" aria-labelledby="faq">
        <div>
          <h2 id="faq" className="text-[24px] font-semibold">Questions colleges ask</h2>
          <dl className="mt-5 space-y-5">
            {CAMPUS_FAQ.map((f) => (
              <div key={f.q}>
                <dt className="font-medium">{f.q}</dt>
                <dd className="mt-1 text-[14px] text-text-2">{f.a}</dd>
              </div>
            ))}
          </dl>
        </div>
        <div id="enquire" className="scroll-mt-24">
          <h2 className="text-[24px] font-semibold">Ask for a college workspace</h2>
          <p className="mt-1 mb-4 text-[14px] text-text-2">We set it up with you and issue your student and staff codes.</p>
          <CampusEnquiry initialPlan={["pilot", "department", "institution", "university"].includes(plan ?? "") ? plan : ""} />
        </div>
      </section>
    </div>
  );
}

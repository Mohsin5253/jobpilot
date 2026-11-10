"use client";

import { ArrowRight, BadgeCheck, ChartLine, Check, GraduationCap, MessageCircle, Pencil, Play, Puzzle, Send, ShieldCheck, Users, X } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { AgentAvatar, AgentHero } from "@/components/agents/agent-avatar";
import { Badge } from "@/components/ui/badge";
import { Button, buttonClass } from "@/components/ui/button";
import { Segmented } from "@/components/ui/misc";
import { ScoreRing } from "@/components/ui/score-ring";
import { StatusPill } from "@/components/ui/status-dot";
import type { AgentKey } from "@/config/agents";
import { useStartDemo } from "@/lib/demo";
import { cn } from "@/lib/utils";

// The one place the Pro price lives (no payments yet: Pro is switched on by hand during the beta).
const PRO_INR = 199;
// Shown only as an approximate conversion for visitors outside India; billing is in rupees.
const PRO_USD_APPROX = "2.40";

export function Reveal({ children, delay = 0, className }: { children: ReactNode; delay?: number; className?: string }) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      initial={reduce ? false : { opacity: 0, y: 16 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-60px" }}
      transition={{ duration: 0.35, delay, ease: [0.22, 1, 0.36, 1] }}
      className={className}
    >
      {children}
    </motion.div>
  );
}

export function SectionHead({ eyebrow, title, sub, center = false }: { eyebrow: string; title: ReactNode; sub?: ReactNode; center?: boolean }) {
  return (
    <Reveal className={cn("mb-10 max-w-[680px] md:mb-14", center && "mx-auto text-center")}>
      <div className="eyebrow mb-3">{eyebrow}</div>
      <h2 className="font-display text-[clamp(32px,4.4vw,52px)] leading-[1.04]">{title}</h2>
      {sub && <p className="mt-4 text-[16px] leading-relaxed text-text-2">{sub}</p>}
    </Reveal>
  );
}

const Wrap = ({ id, children, className }: { id?: string; children: ReactNode; className?: string }) => (
  <section id={id} className={cn("mx-auto max-w-[1200px] scroll-mt-16 px-4 py-20 md:px-6 md:py-28", className)}>
    {children}
  </section>
);

/* ───────────────────── You stay in control ───────────────────── */

const QUEUE = [
  { score: 86, company: "Acme AI", title: "Machine Learning Intern", active: true },
  { score: 78, company: "Northwind Labs", title: "Generative AI Trainee" },
  { score: 71, company: "Lumen Analytics", title: "Data Analyst Intern" },
];

const TRACE: { agent: AgentKey; step: string; ms: string; cost: string }[] = [
  { agent: "scout", step: "142 openings checked", ms: "14.2s", cost: "$0.0000" },
  { agent: "matcher", step: "48 scored, 4 strong", ms: "41.8s", cost: "$0.0031" },
  { agent: "interviewer", step: "1 question asked", ms: "6.1s", cost: "$0.0004" },
  { agent: "tailor", step: "4 resumes tailored", ms: "33.5s", cost: "$0.0021" },
  { agent: "outreach", step: "4 drafts written", ms: "20.4s", cost: "$0.0014" },
];

export function Control() {
  return (
    <Wrap id="control">
      <SectionHead
        eyebrow="You stay in control"
        title="Every send waits for your yes."
        sub="Read the draft, check the tailored resume against your original, and see why the job matched. Then approve, edit or reject. Nothing is ever sent for you."
      />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
        <Reveal>
          <div className="panel overflow-hidden" aria-label="Example approval reviewer" role="img">
            <div className="grid md:grid-cols-[220px_minmax(0,1fr)]">
              <ul className="hidden border-r border-border p-2 md:block">
                <li className="eyebrow px-2 pt-1 pb-2">Queue · 3</li>
                {QUEUE.map((q) => (
                  <li key={q.company} className={cn("relative flex items-center gap-2.5 rounded-[var(--radius-control)] px-2 py-2.5", q.active && "bg-elevated")}>
                    {q.active && <span className="absolute inset-y-2 left-0 w-[2px] rounded-full bg-cobalt" />}
                    <ScoreRing score={q.score} size={34} stroke={3} />
                    <span className="min-w-0">
                      <span className="block truncate text-[13px] font-medium">{q.company}</span>
                      <span className="block truncate text-[12px] text-text-3">{q.title}</span>
                    </span>
                  </li>
                ))}
              </ul>
              <div className="min-w-0">
                <div className="flex gap-5 border-b border-border px-4 text-[13px] font-medium">
                  <span className="border-b-2 border-cobalt py-2.5">Email draft</span>
                  <span className="py-2.5 text-text-3">Tailored resume</span>
                  <span className="hidden py-2.5 text-text-3 sm:block">Why this match</span>
                </div>
                <div className="space-y-3 p-4">
                  <div className="flex items-center gap-2.5 text-[13px]">
                    <AgentAvatar agent="outreach" size={28} decorative />
                    <span className="font-medium">Outreach</span>
                    <span className="text-text-3">drafted 2 min ago</span>
                  </div>
                  <div className="card text-[13px]">
                    <div className="space-y-1 border-b border-border px-3.5 py-2.5 text-text-2">
                      <div>
                        <span className="inline-block w-14 text-text-3">To</span>
                        <span className="num">priya@acme.example</span>
                      </div>
                      <div>
                        <span className="inline-block w-14 text-text-3">Subject</span>
                        <span className="font-medium text-text">ML Intern, recommendations team</span>
                      </div>
                    </div>
                    <p className="px-3.5 py-3 leading-relaxed text-text-2">
                      Hi Priya, I’m a final-year student who built a churn model with scikit-learn that raised recall by 12%. Your recommendations internship looks like a close fit…
                    </p>
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2 border-t border-border p-3">
                  <span className={buttonClass({ variant: "danger", size: "sm" })}>
                    <X /> Reject
                  </span>
                  <span className={buttonClass({ size: "sm" })}>
                    <Pencil /> Edit
                  </span>
                  <span className={buttonClass({ variant: "primary", size: "sm", className: "ml-auto ring-2 ring-[var(--cobalt)] ring-offset-2 ring-offset-[var(--surface)]" })}>
                    <Send /> Approve & send
                  </span>
                </div>
              </div>
            </div>
          </div>
          {/* Pilot points the eye at the one button that matters. */}
          <div className="mt-4 flex items-start justify-end gap-3">
            <div className="relative max-w-[300px] rounded-[var(--radius-card)] border border-border-strong bg-elevated px-4 py-3 text-[14px] leading-relaxed">
              <span aria-hidden className="absolute -top-[7px] right-12 size-3 rotate-45 border-t border-l border-border-strong bg-elevated" />
              Nothing goes out until you press <b className="font-semibold">Approve</b>.
            </div>
            <AgentAvatar agent="pilot" size={64} decorative />
          </div>
        </Reveal>

        <Reveal delay={0.08}>
          <div className="panel h-full p-4 md:p-5" aria-label="Example run trace" role="img">
            <div className="mb-4 flex items-center justify-between">
              <div className="text-[14px] font-semibold">Run trace</div>
              <StatusPill status="your-turn">Needs you</StatusPill>
            </div>
            <ul className="divide-y divide-border">
              {TRACE.map((t) => (
                <li key={t.agent} className="flex items-center gap-3 py-2.5">
                  <AgentAvatar agent={t.agent} status="done" size={28} decorative />
                  <span className="min-w-0 flex-1 truncate text-[13px] text-text-2">{t.step}</span>
                  <span className="num text-[12px] text-text-3">{t.ms}</span>
                  <span className="num w-16 text-right text-[12px]">{t.cost}</span>
                </li>
              ))}
            </ul>
            <div className="num mt-4 flex flex-wrap gap-x-3 gap-y-1 border-t border-border pt-3 text-[12px] text-text-3">
              <span className="text-text">$0.0070</span>
              <span>1m 56s</span>
              <span>15 LLM calls</span>
            </div>
            <p className="mt-4 text-[12.5px] text-text-3">Sample run. Every real run shows its prompts, outputs, timings and cost.</p>
          </div>
        </Reveal>
      </div>
    </Wrap>
  );
}

/* ───────────────────── Feature bento ───────────────────── */

function Tile({ agent, title, text, children, className }: { agent: AgentKey; title: string; text: string; children?: ReactNode; className?: string }) {
  return (
    <div className={cn("card flex h-full flex-col gap-4 p-5 md:p-6", className)}>
      <div className="flex items-start gap-3">
        <AgentAvatar agent={agent} size={40} decorative />
        <div>
          <h3 className="text-[17px] font-semibold tracking-[-0.015em]">{title}</h3>
          <p className="mt-1 text-[14px] leading-relaxed text-text-2">{text}</p>
        </div>
      </div>
      {children && <div className="mt-auto">{children}</div>}
    </div>
  );
}

const EXTRAS = [
  { icon: Users, label: "Referral requests to real people" },
  { icon: ShieldCheck, label: "Ghost-job radar" },
  { icon: ChartLine, label: "Interview-rate insights" },
  { icon: MessageCircle, label: "WhatsApp morning digest" },
  { icon: Puzzle, label: "Autofill extension, you click Submit" },
  { icon: GraduationCap, label: "Campus drives and PPOs" },
];

export function Bento() {
  return (
    <Wrap id="product">
      <SectionHead eyebrow="Product" title="Fewer applications. Stronger ones." sub="Auto-apply bots made hiring noisier. Your crew does the opposite: only your best fits, each one tailored and provable." />
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        <Reveal className="md:col-span-2">
          <Tile agent="matcher" title="Match scoring" text="Every job is scored against your resume with embeddings, skill coverage and an LLM review, and the fit is explained in plain words.">
            <div className="flex flex-wrap items-center gap-4 rounded-[var(--radius-control)] border border-border bg-elevated p-3">
              <ScoreRing score={86} size={52} />
              <div className="flex flex-wrap gap-1.5 text-[12.5px]">
                {["Python", "scikit-learn", "SQL"].map((s) => (
                  <span key={s} className="inline-flex items-center gap-1 rounded-[6px] px-2 py-0.5 font-medium text-done" style={{ background: "color-mix(in oklab, var(--done) 12%, transparent)" }}>
                    <Check className="size-3.5" /> {s}
                  </span>
                ))}
                <span className="rounded-[6px] border border-dashed border-border-strong px-2 py-0.5 text-text-2">Docker</span>
              </div>
            </div>
          </Tile>
        </Reveal>
        <Reveal delay={0.05}>
          <Tile agent="tailor" title="Tailored resumes" text="Bullets rewritten per job. A guard checks each line against your resume and reverts anything new.">
            <p className="rounded-[var(--radius-control)] border border-border bg-elevated p-3 text-[13px] leading-relaxed">
              <del className="text-text-3">Built</del> <ins className="rounded-[3px] bg-cobalt-subtle px-0.5 no-underline">Developed</ins> a churn model{" "}
              <ins className="rounded-[3px] bg-cobalt-subtle px-0.5 no-underline">that raised recall by 12%</ins>
            </p>
          </Tile>
        </Reveal>
        <Reveal>
          <Tile agent="outreach" title="Outreach drafts" text="A short, specific email and a referral request, only to people a company lists publicly. Sent from your own address.">
            <div className="flex flex-wrap gap-1.5">
              <Badge tone="success">
                <Check /> Public contact
              </Badge>
              <Badge>5-line email</Badge>
              <Badge tone="accent">Referral note ready</Badge>
            </div>
          </Tile>
        </Reveal>
        <Reveal delay={0.05}>
          <Tile agent="interviewer" title="Skill check" text="On near misses, Interviewer asks if you have the missing skill. Say yes and those jobs are re-scored.">
            <div className="flex items-center justify-between gap-3 rounded-[var(--radius-control)] border border-border bg-elevated p-3 text-[13px]">
              <span>Used Docker?</span>
              <span className="flex gap-1.5">
                <span className={buttonClass({ size: "sm", variant: "success" })}>Yes</span>
                <span className={buttonClass({ size: "sm", variant: "ghost" })}>No</span>
              </span>
            </div>
          </Tile>
        </Reveal>
        <Reveal delay={0.1}>
          <Tile agent="researcher" title="Proof pack" text="GitHub (ownership verified), Codeforces, projects and certificates on one public page, linked in every draft.">
            <div className="flex flex-wrap gap-1.5">
              <Badge tone="success">
                <BadgeCheck /> GitHub verified
              </Badge>
              <Badge>12 repos</Badge>
              <Badge>Self-reported marked</Badge>
            </div>
          </Tile>
        </Reveal>
        <Reveal className="md:col-span-2">
          <Tile agent="tracker" title="Tracker and follow-ups" text="Every application on a board, a follow-up reminder after seven days, and the outcomes that show what’s working.">
            <div className="grid grid-cols-4 gap-2 text-center">
              {[
                ["Applied", 7],
                ["Replied", 2],
                ["Interview", 1],
                ["Offer", 0],
              ].map(([l, n]) => (
                <div key={l} className="rounded-[var(--radius-control)] border border-border bg-elevated px-2 py-2.5">
                  <div className="num text-[18px] font-semibold">{n}</div>
                  <div className="text-[11.5px] text-text-3">{l}</div>
                </div>
              ))}
            </div>
          </Tile>
        </Reveal>
        <Reveal delay={0.05}>
          <div className="card h-full p-5 md:p-6">
            <h3 className="text-[17px] font-semibold tracking-[-0.015em]">Also in every plan</h3>
            <ul className="mt-4 space-y-2.5">
              {EXTRAS.map(({ icon: Icon, label }) => (
                <li key={label} className="flex items-center gap-2.5 text-[14px] text-text-2">
                  <Icon className="size-4 shrink-0 text-cobalt-text" /> {label}
                </li>
              ))}
            </ul>
          </div>
        </Reveal>
      </div>
    </Wrap>
  );
}

/* ───────────────────── Campus ───────────────────── */

export function Campus() {
  return (
    <Wrap id="campus" className="grid items-center gap-10 lg:grid-cols-2">
      <div>
        <SectionHead
          eyebrow="For colleges"
          title="Campus mode for students and placement cells."
          sub="On-campus drives and off-campus applications on one timeline, with eligibility checked against each student’s academics."
        />
        <ul className="-mt-4 space-y-3 text-[15px] text-text-2">
          {[
            "Eligibility checked against CGPA, branch, backlogs and year",
            "Round-by-round prep for aptitude, coding, technical and HR",
            "Internship-to-PPO tracking",
            "A cohort dashboard for officers; student rows only with their consent",
          ].map((t) => (
            <li key={t} className="flex gap-2.5">
              <Check className="mt-0.5 size-4 shrink-0 text-cobalt-text" /> {t}
            </li>
          ))}
        </ul>
      </div>
      <Reveal>
        <div className="panel p-5 md:p-6" role="img" aria-label="Example campus drive">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-[16px] font-semibold">Acme AI · SDE Intern</div>
              <div className="mt-0.5 text-[13px] text-text-2">On campus · register by 14 Nov</div>
            </div>
            <Badge tone="success">
              <Check /> You’re eligible
            </Badge>
          </div>
          <div className="mt-4 grid grid-cols-3 gap-2 text-[12.5px]">
            {[
              ["Min CGPA", "7.0"],
              ["Branches", "CSE, IT"],
              ["Backlogs", "None"],
            ].map(([l, v]) => (
              <div key={l} className="rounded-[var(--radius-control)] border border-border bg-elevated px-3 py-2">
                <div className="text-text-3">{l}</div>
                <div className="num mt-0.5 font-medium text-text">{v}</div>
              </div>
            ))}
          </div>
          <ol className="mt-5 space-y-2.5">
            {[
              { r: "Aptitude test", s: "done" as const, d: "Passed" },
              { r: "Coding round", s: "your-turn" as const, d: "18 Nov · prep checklist ready" },
              { r: "Technical + HR", s: "idle" as const, d: "After the coding round" },
            ].map((x) => (
              <li key={x.r} className="flex items-center justify-between gap-3 text-[13.5px]">
                <span className="font-medium">{x.r}</span>
                <span className="flex items-center gap-2 text-text-2">
                  {x.d} <StatusPill status={x.s} />
                </span>
              </li>
            ))}
          </ol>
          <p className="mt-5 text-[12.5px] text-text-3">Sample drive with a fictional company.</p>
        </div>
      </Reveal>
    </Wrap>
  );
}

/* ───────────────────── Stories (placeholders) ───────────────────── */

/** No invented testimonials: these slots stay visibly empty until real students share their stories. */
export function Stories() {
  return (
    <Wrap className="py-0 md:py-0">
      <div className="rounded-[var(--radius-panel)] border border-dashed border-border-strong p-6 md:p-8">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h2 className="text-[20px] font-semibold tracking-[-0.02em]">Student stories</h2>
          <Badge tone="outline">Placeholder</Badge>
        </div>
        <p className="mt-2 max-w-xl text-[14px] text-text-2">We’re in beta. Real stories from students will appear here once they share them. We don’t publish made-up quotes.</p>
        <div className="mt-6 grid gap-3 md:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <div key={i} aria-hidden className="flex h-28 items-center justify-center rounded-[var(--radius-card)] border border-dashed border-border text-[13px] text-text-3">
              Story {i + 1} · coming after the beta
            </div>
          ))}
        </div>
      </div>
    </Wrap>
  );
}

/* ───────────────────── Pricing ───────────────────── */

export function Pricing() {
  const [cur, setCur] = useState<"inr" | "usd">("inr");
  const plans = [
    {
      name: "Free",
      price: cur === "inr" ? "₹0" : "$0",
      note: "forever",
      items: ["The whole crew of ten", "Live job alerts", "10 tailored applications a day", "Referral requests and proof page", "Send from your own Gmail"],
      cta: (
        <Link href="/register" className={buttonClass({ size: "lg", className: "w-full" })}>
          Start free
        </Link>
      ),
    },
    {
      name: "Pro",
      price: cur === "inr" ? `₹${PRO_INR}` : `≈ $${PRO_USD_APPROX}`,
      note: cur === "inr" ? "per month · free during the beta" : "per month, billed in ₹ · free during the beta",
      items: ["Everything in Free", "Alerts every minute", "50 tailored applications a day", "20 on-demand runs a day", "10× the AI budget"],
      cta: (
        <Link href="/register" className={buttonClass({ variant: "primary", size: "lg", className: "w-full" })}>
          Start free, request Pro
        </Link>
      ),
      highlight: true,
    },
    {
      name: "Campus",
      price: "Custom",
      note: "per college",
      items: ["Cohort dashboard for officers", "Drives posted to every student", "Automatic eligibility checks", "Student data shared only with consent"],
      cta: (
        <Link href="/register" className={buttonClass({ size: "lg", className: "w-full" })}>
          Ask for a college workspace
        </Link>
      ),
    },
  ];
  return (
    <Wrap id="pricing">
      <SectionHead center eyebrow="Pricing" title="Free to start. Pro when you’re applying hard." />
      <div className="-mt-4 mb-8 flex justify-center md:-mt-6">
        <Segmented
          value={cur}
          onChange={setCur}
          options={[
            { value: "inr", label: "₹ INR" },
            { value: "usd", label: "$ USD" },
          ]}
        />
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        {plans.map((p, i) => (
          <Reveal key={p.name} delay={i * 0.05}>
            <div className={cn("card flex h-full flex-col p-6 md:p-7", p.highlight && "border-[color-mix(in_oklab,var(--cobalt)_45%,transparent)] shadow-[0_0_0_1px_color-mix(in_oklab,var(--cobalt)_25%,transparent),var(--shadow-2)]")}>
              <div className="flex items-center justify-between">
                <div className="eyebrow">{p.name}</div>
                {p.highlight && <Badge tone="accent">Most popular in beta</Badge>}
              </div>
              <div className="mt-4 flex flex-wrap items-baseline gap-x-2">
                <span className="num text-[44px] leading-none font-semibold tracking-[-0.03em]">{p.price}</span>
                <span className="text-[13px] text-text-3">{p.note}</span>
              </div>
              <div className="my-6 h-px bg-border" />
              <ul className="mb-8 space-y-2.5 text-[14px]">
                {p.items.map((it) => (
                  <li key={it} className="flex gap-2.5 text-text-2">
                    <Check className="mt-0.5 size-4 shrink-0 text-cobalt-text" /> {it}
                  </li>
                ))}
              </ul>
              <div className="mt-auto">{p.cta}</div>
            </div>
          </Reveal>
        ))}
      </div>
    </Wrap>
  );
}

/* ───────────────────── FAQ ───────────────────── */

const FAQ = [
  ["Is it really free?", "Yes. Free includes the whole crew, 10 tailored applications a day and live alerts. Pro raises the limits for heavy applying."],
  ["Does it apply for me automatically?", "No, on purpose. The crew prepares everything and you approve each one. Emails go from your own address, and the extension fills forms but never submits."],
  ["Will it get my LinkedIn banned?", "No. JobPilot never automates LinkedIn. It only gives you links, like an alumni search, that you open yourself."],
  ["Where do the jobs come from?", "Public company career boards (Greenhouse, Lever, Ashby) and official job APIs. Scams are filtered, dead links dropped and ghost jobs flagged."],
  ["Who does it email?", "Only people and inboxes a company lists publicly, or a contact provider that cites its sources. Never guessed addresses."],
  ["What does a run cost?", "A run usually costs a fraction of a rupee in AI calls, and every run shows its exact cost in the trace."],
  ["What happens to my data?", "It’s used only for your applications, under consent you can withdraw. Mail passwords are encrypted, and you can export or delete everything in Settings."],
];

export function Faq() {
  return (
    <Wrap id="faq" className="grid gap-10 lg:grid-cols-[minmax(0,4fr)_minmax(0,7fr)]">
      <SectionHead eyebrow="FAQ" title="Questions, answered." sub="Anything else? The live demo shows the whole crew at work." />
      <div className="card divide-y divide-border">
        {FAQ.map(([q, a]) => (
          <details key={q} className="group [&_summary::-webkit-details-marker]:hidden">
            <summary className="flex min-h-14 cursor-pointer list-none items-center justify-between gap-4 rounded-[var(--radius-card)] px-5 py-4 text-[15px] font-medium">
              {q}
              <span aria-hidden className="grid size-7 shrink-0 place-items-center rounded-full border border-border text-text-2 transition-transform duration-[var(--dur-base)] group-open:rotate-45">
                +
              </span>
            </summary>
            <p className="-mt-1 px-5 pb-5 text-[14px] leading-relaxed text-text-2">{a}</p>
          </details>
        ))}
      </div>
    </Wrap>
  );
}

/* ───────────────────── Final CTA ───────────────────── */

export function FinalCta() {
  const demo = useStartDemo();
  return (
    <Wrap className="pt-0 md:pt-0">
      <Reveal>
        <div className="panel grid items-center gap-8 overflow-hidden p-6 md:grid-cols-[auto_minmax(0,1fr)] md:p-10">
          <div className="mx-auto md:mx-0">
            <AgentHero agent="pilot" size={160} priority={false} />
          </div>
          <div className="text-center md:text-left">
            <div className="eyebrow mb-3">Pilot</div>
            <h2 className="font-display text-[clamp(30px,4vw,48px)] leading-[1.05]">Ready when you are.</h2>
            <p className="mt-3 max-w-lg text-[16px] text-text-2 md:max-w-none">Upload your resume and I’ll send the crew out. Or watch us work on a demo profile first.</p>
            <div className="mt-6 flex flex-col justify-center gap-3 sm:flex-row md:justify-start">
              <Link href="/register" className={buttonClass({ variant: "primary", size: "lg", className: "w-full sm:w-auto" })}>
                Start free <ArrowRight />
              </Link>
              <Button size="lg" className="w-full sm:w-auto" onClick={demo.start} loading={demo.loading}>
                {!demo.loading && <Play className="fill-current" />} Watch the crew work
              </Button>
            </div>
          </div>
        </div>
      </Reveal>
    </Wrap>
  );
}


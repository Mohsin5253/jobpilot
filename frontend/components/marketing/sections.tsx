"use client";

import { ArrowRight, BadgeCheck, Ban, Check, CircleAlert, GitBranch, Mail, Pencil, Play, Puzzle, Send, ShieldAlert, ShieldCheck, Trophy, Undo2, X } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import Link from "next/link";
import type { ReactNode } from "react";

import { AgentAvatar, AgentHero } from "@/components/agents/agent-avatar";
import { Badge } from "@/components/ui/badge";
import { Button, buttonClass } from "@/components/ui/button";
import { ScoreRing } from "@/components/ui/score-ring";
import { StatusPill } from "@/components/ui/status-dot";
import type { AgentKey } from "@/config/agents";
import { useStartDemo } from "@/lib/demo";
import { cn } from "@/lib/utils";
import { CAMPUS_PER_STUDENT_INR } from "@/lib/campus-pricing";

// The one place the plan numbers live. Payments aren't live yet: Pro is switched on by hand during the beta.
const FREE_SENDS_DEFAULT = 5;
const FREE_SENDS_MAX = 10;
const PRO_INR = 299;
const WEEK_PASS_INR = 79;
const YEAR_PASS_INR = 2499;

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

const Sample = ({ children = "Sample with fictional companies." }: { children?: ReactNode }) => <p className="mt-4 text-[12.5px] text-text-3">{children}</p>;

function Ticks({ items, className }: { items: ReactNode[]; className?: string }) {
  return (
    <ul className={cn("space-y-3 text-[15px] text-text-2", className)}>
      {items.map((t, i) => (
        <li key={i} className="flex gap-2.5">
          <Check className="mt-0.5 size-4 shrink-0 text-cobalt-text" /> <span>{t}</span>
        </li>
      ))}
    </ul>
  );
}

/* ───────────────────── 1. Safety: Verifier + Scam Shield ───────────────────── */

const VERDICTS = [
  {
    tone: "danger" as const,
    label: "Blocked",
    icon: Ban,
    job: "Data Entry Intern · QuickHire Solutions",
    quote: "Pay a ₹1,999 refundable training fee and WhatsApp us to confirm your seat.",
    reasons: ["Asks you to pay for training, a kit or a certificate", "Hiring happens over WhatsApp or Telegram, not an application"],
  },
  {
    tone: "warning" as const,
    label: "Needs care",
    icon: CircleAlert,
    job: "Marketing Intern · Northwind Labs",
    reasons: ["The recruiter uses a personal email address"],
  },
  {
    tone: "success" as const,
    label: "Verified",
    icon: ShieldCheck,
    job: "ML Intern · Acme AI",
    reasons: ["Listed on the company’s careers system", "Apply link opened and the job is open"],
  },
];

export function Safety() {
  return (
    <Wrap id="safety">
      <SectionHead
        eyebrow="Safety first"
        title="Scams never reach your queue."
        sub="Fake internships that charge a “training fee” are everywhere. Verifier checks every posting before you see it, and anything that asks for money is blocked, not just flagged."
      />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
        <Reveal>
          <div className="panel p-4 md:p-5" role="img" aria-label="Example Verifier verdicts: one blocked, one needing care, one verified">
            <div className="mb-4 flex items-center gap-2.5">
              <AgentAvatar agent="verifier" size={32} decorative />
              <div className="text-[14px] font-semibold">Verifier</div>
              <span className="text-[13px] text-text-3">3 postings checked</span>
            </div>
            <ul className="space-y-3">
              {VERDICTS.map((v) => (
                <li key={v.job} className="card p-3.5">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-[14px] font-medium">{v.job}</span>
                    <Badge tone={v.tone}>
                      <v.icon /> {v.label}
                    </Badge>
                  </div>
                  {v.quote && <p className="mt-2 rounded-[var(--radius-control)] border border-border bg-elevated px-3 py-2 text-[13px] text-text-2 italic">“{v.quote}”</p>}
                  <ul className="mt-2 space-y-1 text-[13px] text-text-2">
                    {v.reasons.map((r) => (
                      <li key={r} className="flex gap-2">
                        <span aria-hidden className="mt-[7px] size-1 shrink-0 rounded-full bg-text-3" /> {r}
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          </div>
          <Sample />
        </Reveal>
        <Reveal delay={0.08} className="flex flex-col gap-4">
          <div className="card p-5 md:p-6">
            <h3 className="text-[17px] font-semibold tracking-[-0.015em]">What every posting is checked for</h3>
            <Ticks
              className="mt-4 text-[14px]"
              items={[
                "A named employer, not “a leading MNC”",
                "No fees: training, kit, certificate or “refundable” deposits",
                "A real application, not WhatsApp- or Telegram-only hiring",
                "A live apply link, ideally on the company’s own careers system",
                "A recruiter email on the company’s domain",
                "Pressure tactics, guarantees and implausible pay",
                "Ghost jobs: old, reposted or unverifiable listings",
              ]}
            />
          </div>
          <div className="card p-5 md:p-6">
            <div className="flex flex-wrap items-center gap-2">
              <ShieldAlert className="size-4 text-cobalt-text" />
              <h3 className="text-[17px] font-semibold tracking-[-0.015em]">Scam Shield</h3>
              <Badge tone="success">Free</Badge>
            </div>
            <p className="mt-2 text-[14px] leading-relaxed text-text-2">
              Got an offer on WhatsApp or Telegram? Paste it, a link or the offer letter and get a verdict with the evidence, in English, Hindi or Marathi. No
              sign-in, and nothing you paste is stored.
            </p>
            <Link href="/scam-check" className={buttonClass({ variant: "primary", className: "mt-3" })}>
              Check an offer <ArrowRight />
            </Link>
            <p className="mt-3 text-[13px] leading-relaxed text-text-2">
              Never pay to get an internship. If someone has asked you to, report it at{" "}
              <a href="https://cybercrime.gov.in" target="_blank" rel="noopener noreferrer" className="text-cobalt-text underline-offset-2 hover:underline">
                cybercrime.gov.in
              </a>{" "}
              or call <b className="text-text">1930</b>.
            </p>
          </div>
        </Reveal>
      </div>
    </Wrap>
  );
}

/* ───────────────────── 2. Honesty: the no-fabrication guard ───────────────────── */

const Ins = ({ children }: { children: ReactNode }) => <ins className="rounded-[3px] bg-cobalt-subtle px-0.5 text-text no-underline">{children}</ins>;
const Del = ({ children }: { children: ReactNode }) => <del className="text-text-3">{children}</del>;
const Flag = ({ children }: { children: ReactNode }) => (
  <mark className="rounded-[3px] px-0.5 text-text" style={{ background: "color-mix(in oklab, var(--error) 18%, transparent)" }}>
    {children}
  </mark>
);

export function Honesty() {
  return (
    <Wrap id="honesty" className="grid items-start gap-10 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      <div>
        <SectionHead
          eyebrow="Honesty"
          title="Your resume, sharper. Never invented."
          sub="Tailor rewrites your bullets for each job. A guard then checks every line against your original, and anything you haven’t done is reverted before you ever see it."
        />
        <Ticks
          className="-mt-4"
          items={[
            "A new tool, skill or number that isn’t in your resume is reverted",
            "So is a tool moved from one project into another",
            "Every revert is logged with its reason",
            "You review the diff against your original before anything is sent",
          ]}
        />
      </div>
      <Reveal>
        <div className="panel p-4 md:p-5" role="img" aria-label="Example: one rewritten bullet kept, one reverted for adding skills and a number that aren't on the resume">
          <div className="mb-4 flex items-center gap-2.5">
            <AgentAvatar agent="tailor" size={32} decorative />
            <div className="text-[14px] font-semibold">Tailor + guard</div>
          </div>
          <div className="eyebrow mb-1.5">Your original</div>
          <p className="card px-3.5 py-3 text-[14px] leading-relaxed">Built a churn model with scikit-learn that raised recall by 12%.</p>

          <div className="mt-4 mb-1.5 flex items-center justify-between gap-2">
            <span className="eyebrow">Rewrite 1</span>
            <Badge tone="success">
              <Check /> Kept
            </Badge>
          </div>
          <p className="card px-3.5 py-3 text-[14px] leading-relaxed text-text-2">
            <Del>Built</Del> <Ins>Developed</Ins> a churn model with scikit-learn <Del>that raised</Del> <Ins>, raising</Ins> recall by 12%.
          </p>

          <div className="mt-4 mb-1.5 flex items-center justify-between gap-2">
            <span className="eyebrow">Rewrite 2</span>
            <Badge tone="danger">
              <Undo2 /> Reverted
            </Badge>
          </div>
          <p className="card px-3.5 py-3 text-[14px] leading-relaxed text-text-2">
            Deployed the churn model on <Flag>Docker</Flag> and <Flag>AWS</Flag>, cutting churn by <Flag>30%</Flag>.
          </p>
          <p className="mt-2 text-[13px] text-text-2">
            Docker and AWS aren’t on your resume, and 30% isn’t in the original bullet. Your original line is used instead.
          </p>
        </div>
      </Reveal>
    </Wrap>
  );
}

/* ───────────────────── 3. Control: approve every send ───────────────────── */

const QUEUE = [
  { score: 86, company: "Acme AI", title: "Machine Learning Intern", active: true },
  { score: 78, company: "Northwind Labs", title: "Generative AI Trainee" },
  { score: 71, company: "Lumen Analytics", title: "Data Analyst Intern" },
];

const PILLARS = [
  { icon: Send, title: "You approve every send", text: "Each email waits in your queue. Read it, edit it, or reject it. Nothing goes out in bulk or on a timer." },
  { icon: Mail, title: "From your own Gmail", text: "Approved emails go from your address, with your tailored resume attached. Replies come straight to you." },
  { icon: Ban, title: "Never LinkedIn", text: "JobPilot never logs in to, automates or scrapes LinkedIn or any job-board account. It gives you links you open yourself." },
  { icon: Puzzle, title: "Autofill, you click Submit", text: "The browser extension fills application forms. It never presses Submit for you." },
];

export function Control() {
  return (
    <Wrap id="control">
      <SectionHead
        eyebrow="You stay in control"
        title="Every send waits for your yes."
        sub="Read the draft, compare the tailored resume with your original, and see why the job matched. Then approve, edit or reject."
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
                    <Badge tone="success" className="ml-auto">
                      <ShieldCheck /> Verified posting
                    </Badge>
                  </div>
                  <div className="card text-[13px]">
                    <div className="space-y-1 border-b border-border px-3.5 py-2.5 text-text-2">
                      <div>
                        <span className="inline-block w-14 text-text-3">To</span>
                        <span className="num">careers@acme.example</span>
                      </div>
                      <div>
                        <span className="inline-block w-14 text-text-3">Subject</span>
                        <span className="font-medium text-text">ML Intern, recommendations team</span>
                      </div>
                    </div>
                    <p className="px-3.5 py-3 leading-relaxed text-text-2">
                      Hello, I’m a final-year student who built a churn model with scikit-learn that raised recall by 12%. Your recommendations internship looks like a close fit…
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
          <Sample />
        </Reveal>
        <Reveal delay={0.08}>
          <ul className="grid gap-3">
            {PILLARS.map(({ icon: Icon, title, text }) => (
              <li key={title} className="card flex gap-3.5 p-4">
                <span className="grid size-9 shrink-0 place-items-center rounded-[var(--radius-control)] bg-cobalt-subtle text-cobalt-text">
                  <Icon className="size-4" />
                </span>
                <span>
                  <span className="block text-[15px] font-semibold">{title}</span>
                  <span className="mt-0.5 block text-[13.5px] leading-relaxed text-text-2">{text}</span>
                </span>
              </li>
            ))}
          </ul>
        </Reveal>
      </div>
    </Wrap>
  );
}

/* ───────────────────── 4. Credibility: the proof page ───────────────────── */

export function Credibility() {
  return (
    <Wrap id="proof" className="grid items-center gap-10 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
      <Reveal className="order-2 lg:order-1">
        <div className="panel p-5 md:p-6" role="img" aria-label="Example proof page for a student, with verified GitHub, Codeforces rating, projects and a self-reported certificate">
          <div className="eyebrow">Proof of work</div>
          <div className="mt-2 font-display text-[32px] leading-none">Aarav Sharma</div>
          <div className="mt-1.5 text-[13px] text-text-2">B.Tech Computer Science · class of 2027</div>
          <div className="mt-5 grid gap-2 sm:grid-cols-2">
            <div className="card flex items-center gap-3 p-3">
              <GitBranch className="size-4 text-text-2" />
              <div className="min-w-0">
                <div className="text-[13px] font-medium">GitHub · 14 public repos</div>
                <div className="text-[12px] text-done">Ownership verified</div>
              </div>
            </div>
            <div className="card flex items-center gap-3 p-3">
              <Trophy className="size-4 text-text-2" />
              <div className="min-w-0">
                <div className="num text-[13px] font-medium">Codeforces · 1,624</div>
                <div className="text-[12px] text-text-3">From the official API</div>
              </div>
            </div>
          </div>
          <ul className="mt-3 divide-y divide-border rounded-[var(--radius-card)] border border-border">
            {[
              { t: "Churn prediction model", s: "Python · scikit-learn", b: <Badge tone="success"><BadgeCheck /> Repo linked</Badge> },
              { t: "Campus canteen ordering app", s: "React · Firebase", b: <Badge tone="success"><BadgeCheck /> Repo linked</Badge> },
              { t: "Machine Learning certificate", s: "Online course", b: <Badge tone="outline">Self-reported</Badge> },
            ].map((x) => (
              <li key={x.t} className="flex items-center justify-between gap-3 px-3.5 py-2.5">
                <span className="min-w-0">
                  <span className="block truncate text-[13.5px] font-medium">{x.t}</span>
                  <span className="block text-[12px] text-text-3">{x.s}</span>
                </span>
                {x.b}
              </li>
            ))}
          </ul>
        </div>
        <Sample>Sample with a fictional student.</Sample>
      </Reveal>
      <div className="order-1 lg:order-2">
        <SectionHead
          eyebrow="Credibility"
          title="Proof a recruiter can check in a minute."
          sub="Your proof page puts your real work on one link: GitHub you’ve proven you own, your Codeforces rating, projects and certificates. Anything we couldn’t verify is labelled self-reported."
        />
        <Ticks
          className="-mt-4"
          items={["Published only if you switch it on, and you can unpublish it any time", "No email, phone number or resume on the page", "Linked from the drafts you approve"]}
        />
      </div>
    </Wrap>
  );
}

/* ───────────────────── 5. Outcomes ───────────────────── */

/* ───────────────────── Get interview-ready: resume & ATS, mock interviews, one-click apply ───────────────────── */

export function InterviewReady() {
  const cards = [
    {
      agent: "tailor" as AgentKey,
      eyebrow: "Resume & ATS",
      title: "See your resume the way an ATS does, then fix it in one click.",
      points: [
        "ATS score by industry: 12 fields, from software and data to marketing, finance and core engineering",
        "Gap report, missing keywords and improvements ranked by points gained",
        "Improve with AI: stronger bullets and a summary from your own facts, nothing invented",
        "Clean one-page PDF or Word file with proper page breaks",
      ],
      preview: (
        <div className="card flex flex-wrap items-center gap-x-4 gap-y-3 p-4">
          <ScoreRing score={62} size={56} stroke={5} />
          <ArrowRight className="size-4 text-text-3" />
          <ScoreRing score={84} size={56} stroke={5} />
          <div className="min-w-[180px] flex-1 text-[12.5px] text-text-2">
            <div className="font-medium text-text">+22 for Data Analyst Intern</div>
            <div>SQL and Power BI now shown in bullets · summary added</div>
          </div>
        </div>
      ),
    },
    {
      agent: "interviewer" as AgentKey,
      eyebrow: "AI mock interviews",
      title: "A real 30 to 60 minute interview for each job, with a coding round for tech roles.",
      points: [
        "A 3D interviewer (choose a male or female voice) runs the rounds your field really uses",
        "Coding round in Python, JavaScript, Java or C++, judged by an AI code reviewer: correct or not, complexity, bugs, fixes",
        "Answer out loud: accurate speech-to-text tuned for Indian English",
        "A report on every round against your field's bar, with gaps and a 7-day plan",
      ],
      preview: (
        <div className="card p-4 text-[12.5px]">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium text-text">Code review · Valid Brackets</span>
            <Badge tone="success">correct</Badge>
          </div>
          <div className="mt-1 text-text-3">7/7 tests passed · O(n) time, O(n) space · optimal</div>
          <div className="mt-2 text-text-2">Coding round: Above bar · Project deep-dive: add one measurable result</div>
        </div>
      ),
    },
    {
      agent: "outreach" as AgentKey,
      eyebrow: "Apply in one click",
      title: "Your tailored resume and a short email to the recruiter, sent when you say so.",
      points: [
        "Prepare application: a resume tailored to the job description and a draft written to your field's norms",
        "See the uploaded and tailored versions side by side, with the ATS score for both",
        "Send from your own Gmail with the PDF attached, after you confirm",
      ],
      preview: (
        <div className="card p-4 text-[12.5px]">
          <div className="flex items-center gap-2 font-medium text-text">
            <Send className="size-3.5" /> To hr@acme.example
          </div>
          <div className="mt-1 text-text-3">Tailored resume (PDF) attached · ATS 70 (+8)</div>
        </div>
      ),
    },
  ];
  return (
    <Wrap id="interview-ready">
      <SectionHead center eyebrow="Get interview-ready" title="From resume to offer: practise like it's real." sub="Everything between finding a job and getting the offer, built to Indian industry norms for interns and freshers." />
      <div className="grid gap-4 lg:grid-cols-3">
        {cards.map((c, i) => (
          <Reveal key={c.eyebrow} delay={i * 0.06}>
            <div className="card flex h-full flex-col gap-4 p-6">
              <div className="flex items-center gap-3">
                <AgentAvatar agent={c.agent} size={40} decorative />
                <div className="eyebrow text-cobalt-text">{c.eyebrow}</div>
              </div>
              <h3 className="text-[19px] leading-snug font-semibold tracking-[-0.01em]">{c.title}</h3>
              <Ticks className="text-[14px]" items={c.points} />
              <div className="mt-auto">{c.preview}</div>
            </div>
          </Reveal>
        ))}
      </div>
      <Sample>Sample numbers.</Sample>
    </Wrap>
  );
}

export function Outcomes() {
  const board: [string, number][] = [
    ["Applied", 12],
    ["Replied", 4],
    ["Interview", 2],
    ["Offer", 1],
  ];
  return (
    <Wrap id="outcomes" className="grid items-center gap-10 lg:grid-cols-2">
      <div>
        <SectionHead
          eyebrow="Outcomes"
          title="Measured by interviews, not by emails sent."
          sub="Tracker keeps every application on one board, reminds you to follow up after seven days, and shows your interview rate so you can see what’s working."
        />
        <Ticks className="-mt-4" items={["Interview rate and reply rate from your own applications", "Internship-to-PPO tracking: eligible, offered, converted", "A reminder for one polite follow-up, never a spam sequence"]} />
      </div>
      <Reveal>
        <div className="panel p-5 md:p-6" role="img" aria-label="Example tracker: 12 applied, 4 replied, 2 interviews, 1 offer; interview rate 17 percent">
          <div className="flex items-center gap-2.5">
            <AgentAvatar agent="tracker" size={32} decorative />
            <div className="text-[14px] font-semibold">Tracker</div>
          </div>
          <div className="mt-4 grid grid-cols-4 gap-2 text-center">
            {board.map(([l, n]) => (
              <div key={l} className="rounded-[var(--radius-control)] border border-border bg-elevated px-1 py-2.5">
                <div className="num text-[20px] font-semibold">{n}</div>
                <div className="text-[11.5px] text-text-3">{l}</div>
              </div>
            ))}
          </div>
          <div className="mt-4 grid grid-cols-2 gap-2">
            <div className="card p-3">
              <div className="text-[12px] text-text-3">Interview rate</div>
              <div className="num mt-0.5 text-[22px] font-semibold">17%</div>
              <div className="text-[12px] text-text-3">2 of 12 applications</div>
            </div>
            <div className="card p-3">
              <div className="text-[12px] text-text-3">Summer internship</div>
              <div className="mt-1.5">
                <Badge tone="accent">PPO offered</Badge>
              </div>
              <div className="mt-1.5 text-[12px] text-text-3">Decision due 30 Nov</div>
            </div>
          </div>
        </div>
        <Sample>Sample numbers.</Sample>
      </Reveal>
    </Wrap>
  );
}

/* ───────────────────── 6. How it works: the trace ───────────────────── */

const TRACE: { agent: AgentKey; step: string; ms: string; cost: string }[] = [
  { agent: "scout", step: "142 openings checked", ms: "14.2s", cost: "₹0.00" },
  { agent: "verifier", step: "48 verified, 1 blocked", ms: "3.9s", cost: "₹0.01" },
  { agent: "matcher", step: "48 scored, 4 strong", ms: "41.8s", cost: "₹0.27" },
  { agent: "interviewer", step: "1 question asked", ms: "6.1s", cost: "₹0.04" },
  { agent: "tailor", step: "4 resumes tailored", ms: "33.5s", cost: "₹0.18" },
  { agent: "outreach", step: "4 drafts written", ms: "20.4s", cost: "₹0.12" },
];

export function TraceSample({ costPerRun }: { costPerRun: string | null }) {
  return (
    <Wrap id="trace" className="grid items-center gap-10 pt-0 md:pt-0 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      <div>
        <div className="eyebrow mb-3">The run trace</div>
        <h3 className="font-display text-[clamp(28px,3.4vw,40px)] leading-[1.06]">Every step, timed and costed in rupees.</h3>
        <p className="mt-4 text-[16px] leading-relaxed text-text-2">
          Each run records which agent did what, how long it took, the tokens it used and what it cost.
          {costPerRun ? ` Across real beta runs, the average is ${costPerRun} a run.` : ""} The trace keeps timings and costs, not your prompts or the AI’s replies.
        </p>
      </div>
      <Reveal>
        <div className="panel p-4 md:p-5" aria-label="Example run trace" role="img">
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
                <span className="num w-14 text-right text-[12px]">{t.cost}</span>
              </li>
            ))}
          </ul>
          <div className="num mt-4 flex flex-wrap gap-x-3 gap-y-1 border-t border-border pt-3 text-[12px] text-text-3">
            <span className="text-text">₹0.62</span>
            <span>2m 00s</span>
            <span>15 LLM calls</span>
            <span>21.4k tokens</span>
          </div>
        </div>
        <Sample>Sample run.</Sample>
      </Reveal>
    </Wrap>
  );
}

/* ───────────────────── 7. Pricing ───────────────────── */

type Plan = { name: string; price: string; note: string; items: { t: string; soon?: boolean }[]; cta: ReactNode; highlight?: boolean; badge?: string };

export function Pricing() {
  const plans: Plan[] = [
    {
      name: "Free",
      price: "₹0",
      note: "forever",
      items: [
        { t: "The whole crew of ten" },
        { t: `${FREE_SENDS_DEFAULT} approved sends a day by default, up to ${FREE_SENDS_MAX} if you choose` },
        { t: "Scam and ghost-job checks on every posting" },
        { t: "Proof page and tracker" },
        { t: "Send from your own Gmail" },
        { t: "Resume & ATS check, builder and AI improvement" },
        { t: "AI mock interviews with a coding round" },
      ],
      cta: (
        <Link href="/register" className={buttonClass({ size: "lg", className: "w-full" })}>
          Start free
        </Link>
      ),
    },
    {
      name: "Week Pass",
      price: `₹${WEEK_PASS_INR}`,
      note: "one week of Pro, UPI · no renewal",
      items: [{ t: "Everything in Pro for 7 days" }, { t: "For a placement week or an application sprint" }, { t: "Pay once, nothing renews" }],
      cta: (
        <Link href="/billing?plan=week_pass" className={buttonClass({ size: "lg", className: "w-full" })}>
          Get the Week Pass
        </Link>
      ),
    },
    {
      name: "Pro",
      price: `₹${PRO_INR}`,
      note: "per month · UPI AutoPay or card · cancel anytime",
      items: [
        { t: "Everything in Free" },
        { t: "10× the AI budget: more tailoring, code reviews and interview feedback each day" },
        { t: "Up to 50 tailored applications and 20 on-demand runs a day (Free: 10 and 3)" },
        { t: "New-job alerts every minute (Free: every 15)" },
        { t: "Proof Link analytics", soon: true },
        { t: "Priority verification", soon: true },
      ],
      cta: (
        <Link href="/billing?plan=pro" className={buttonClass({ variant: "primary", size: "lg", className: "w-full" })}>
          Get Pro
        </Link>
      ),
      highlight: true,
    },
    {
      name: "Year Pass",
      price: `₹${YEAR_PASS_INR.toLocaleString("en-IN")}`,
      note: `per year · ≈ ₹${Math.round(YEAR_PASS_INR / 12)}/month · UPI, pay once`,
      items: [
        { t: "Everything in Pro for 365 days" },
        { t: `Save ₹${(PRO_INR * 12 - YEAR_PASS_INR).toLocaleString("en-IN")} vs paying monthly` },
        { t: "Covers the whole placement season" },
        { t: "Pay once, nothing renews" },
      ],
      badge: "Best value",
      cta: (
        <Link href="/billing?plan=year_pass" className={buttonClass({ size: "lg", className: "w-full" })}>
          Get the Year Pass
        </Link>
      ),
    },
    {
      name: "Campus",
      price: `₹${CAMPUS_PER_STUDENT_INR}`,
      note: "per student / year for a whole college · free pilot for one season",
      items: [
        { t: "TPO, HOD and faculty accounts with department scope" },
        { t: "Live placement pipeline, round by round" },
        { t: "AI job matches your staff approve" },
        { t: "Student data shared only with consent" },
      ],
      cta: (
        <Link href="/campus-pricing" className={buttonClass({ size: "lg", className: "w-full" })}>
          See campus plans
        </Link>
      ),
    },
  ];
  return (
    <Wrap id="pricing">
      <SectionHead center eyebrow="Pricing" title="Free to start. Pay in rupees when you want more depth." sub={`Pro is about better applications, not more of them. Pay by UPI QR, UPI, card or netbanking: ₹${WEEK_PASS_INR} a week, ₹${PRO_INR} a month, or ₹${YEAR_PASS_INR.toLocaleString("en-IN")} a year.`} />
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        {plans.map((p, i) => (
          <Reveal key={p.name} delay={i * 0.05}>
            <div className={cn("card flex h-full flex-col p-6", p.highlight && "border-[color-mix(in_oklab,var(--cobalt)_45%,transparent)] shadow-[0_0_0_1px_color-mix(in_oklab,var(--cobalt)_25%,transparent),var(--shadow-2)]")}>
              <div className="flex items-center justify-between">
                <h3 className="eyebrow">{p.name}</h3>
                {p.highlight && <Badge tone="accent">Beta</Badge>}
                {p.badge && <Badge tone="success">{p.badge}</Badge>}
              </div>
              <div className="mt-4">
                <span className="num text-[40px] leading-none font-semibold tracking-[-0.03em]">{p.price}</span>
                <p className="mt-2 text-[13px] text-text-3">{p.note}</p>
              </div>
              <div className="my-5 h-px bg-border" />
              <ul className="mb-8 space-y-2.5 text-[14px]">
                {p.items.map((it) => (
                  <li key={it.t} className="flex gap-2.5 text-text-2">
                    <Check className="mt-0.5 size-4 shrink-0 text-cobalt-text" />
                    <span>
                      {it.t}
                      {it.soon && (
                        <Badge tone="outline" className="ml-1.5 align-[1px]">
                          Soon
                        </Badge>
                      )}
                    </span>
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

/* ───────────────────── 8. Campus ───────────────────── */

export function Campus() {
  return (
    <Wrap id="campus" className="grid items-center gap-10 lg:grid-cols-2">
      <div>
        <SectionHead
          eyebrow="For colleges"
          title="Campus mode for placement cells."
          sub="Built for tier-2 and tier-3 colleges: on-campus drives and off-campus applications on one timeline, with eligibility checked against each student’s academics."
        />
        <Ticks
          className="-mt-4"
          items={[
            "Eligibility checked against CGPA, branch, backlogs and year",
            "Round-by-round prep for aptitude, coding, technical and HR",
            "Internship-to-PPO tracking",
            "A cohort dashboard for officers; student rows only with their consent",
            "TPO, HOD and faculty roles; AI job matches staff approve",
          ]}
        />
        <Link href="/campus-pricing" className={buttonClass({ variant: "secondary", className: "mt-6" })}>
          Campus plans and pricing <ArrowRight />
        </Link>
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
        </div>
        <Sample>Sample drive with a fictional company.</Sample>
      </Reveal>
    </Wrap>
  );
}

/* ───────────────────── 9. FAQ ───────────────────── */

export function Faq({ costPerRun }: { costPerRun: string | null }) {
  const faq: [string, ReactNode][] = [
    [
      "Is it really free?",
      `Yes. Free includes the whole crew, scam checks on every posting, and up to ${FREE_SENDS_DEFAULT} approved sends a day (you can raise it to ${FREE_SENDS_MAX}). Pro adds depth, not volume.`,
    ],
    ["Does it apply for me automatically?", "No, on purpose. The crew prepares everything and you approve each one. Emails go from your own address, and the extension fills forms but never submits."],
    ["How do you spot scam internships?", "Verifier checks every posting for fee demands, WhatsApp-only hiring, unnamed employers, personal-email recruiters, dead links and ghost-job signals. Postings that ask for money are blocked before they reach you."],
    [
      "How real are the mock interviews?",
      "They follow the rounds your field actually uses (screening, technical or case, coding for tech roles, project, HR) and run 30, 45 or 60 minutes. Coding answers run in your browser against hidden tests, and an AI code reviewer says whether they're correct and how to improve. The report grades each round against the bar for interns or freshers. Questions refresh weekly from what's rising in real job postings.",
    ],
    [
      "Is the ATS score accurate?",
      "No ATS publishes its formula, so the score models how they work: whether your file parses, how well you match the job's keywords (weighted the way recruiters filter), the impact of your bullets, and what recruiters in your field expect. The same resume always gets the same score, and every point lost comes with the fix.",
    ],
    ["Will it get my LinkedIn banned?", "No. JobPilot never logs in to or automates LinkedIn, or any other job board. It only gives you links, like an alumni search, that you open yourself."],
    ["Who does it email?", "Only people and inboxes a company lists publicly, or a contact provider that cites its sources. Never guessed addresses."],
    [
      "What does a run cost?",
      costPerRun
        ? `About ${costPerRun} in AI calls on average across real beta runs in the last 30 days. Every run shows its exact cost in the trace.`
        : "A fraction of a rupee in AI calls, usually. Every run shows its exact cost in rupees in the trace.",
    ],
    [
      "What happens to my data?",
      <>
        It’s used only for your applications, under consent you can withdraw. You can export or delete everything in Settings. The{" "}
        <Link href="/trust" className="text-cobalt-text hover:underline">
          Trust page
        </Link>{" "}
        lists what we store and what we never do.
      </>,
    ],
  ];
  return (
    <Wrap id="faq" className="grid gap-10 lg:grid-cols-[minmax(0,4fr)_minmax(0,7fr)]">
      <SectionHead eyebrow="FAQ" title="Questions, answered." sub="Anything else? The live demo shows the whole crew at work." />
      <div className="card divide-y divide-border">
        {faq.map(([q, a]) => (
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

import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import { GrievanceForm } from "@/components/grievance-form";
import { CONTACT_EMAIL, GRIEVANCE_EMAIL, GRIEVANCE_OFFICER } from "@/components/legal";
import { API_URL } from "@/lib/server-api";

type NoticeItem = { purpose: string; description: string; data: string; why: string; retention: string; withdraw: string };

async function getNotice(): Promise<{ version: string; purposes: NoticeItem[] } | null> {
  try {
    const r = await fetch(`${API_URL}/api/consents/notice`, { next: { revalidate: 3600 }, signal: AbortSignal.timeout(4000) });
    return r.ok ? r.json() : null;
  } catch {
    return null;
  }
}

export const metadata: Metadata = {
  title: "Trust",
  description: "What JobPilot checks, what it never does, the data it stores, your rights under India's DPDP Act, and who processes data for us.",
  alternates: { canonical: "/trust" },
};

const UPDATED = "10 November 2026";  // bump with the consent notice version

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-h`} className="scroll-mt-20 border-t border-border py-10 first:border-t-0 first:pt-0">
      <h2 id={`${id}-h`} className="text-[22px] font-semibold tracking-[-0.02em]">
        {title}
      </h2>
      <div className="mt-4 space-y-4 text-[15px] leading-relaxed text-text-2">{children}</div>
    </section>
  );
}

const List = ({ items }: { items: ReactNode[] }) => (
  <ul className="space-y-2">
    {items.map((t, i) => (
      <li key={i} className="flex gap-2.5">
        <span aria-hidden className="mt-[9px] size-1.5 shrink-0 rounded-full bg-cobalt" />
        <span>{t}</span>
      </li>
    ))}
  </ul>
);

const TOC = [
  ["checks", "What we check"],
  ["never", "What we never do"],
  ["data", "Data we store"],
  ["consent", "Consent notice"],
  ["rights", "Your rights"],
  ["grievance", "Grievance contact"],
  ["subprocessors", "Who processes data for us"],
] as const;

const SUBPROCESSORS: [string, string, string][] = [
  ["Render", "Runs the API, the agents and the Postgres database", "Singapore"],
  ["Vercel", "Hosts the website", "Global edge network"],
  ["Groq", "AI model provider: reads your resume and job descriptions to score fit and write drafts", "United States"],
  ["Adzuna, JSearch, Hunter.io", "Job listings and public company contacts. They receive search terms and company names, never your resume", "Various"],
  ["GitHub, Codeforces", "Public profile data for your proof page. They receive only the handle you link", "United States, Russia"],
  ["Our transactional email provider", "Password resets and match alerts", "Depends on the provider"],
  ["Sentry", "Error monitoring, configured not to receive personal data", "United States"],
  ["Google (Gmail API)", "Only if you connect Gmail: sends the applications you approve. Send-only access; we can’t read your mail", "Global"],
  ["Meta (WhatsApp Cloud API)", "Only if you turn on the WhatsApp digest: your number and the digest text", "Global"],
];

export const revalidate = 3600;

export default async function TrustPage() {
  const notice = await getNotice();
  return (
    <article className="mx-auto max-w-3xl px-4 py-16 sm:px-6">
      <div className="eyebrow mb-3">Trust</div>
      <h1 className="font-display text-[clamp(36px,6vw,56px)] leading-[1.04]">How JobPilot keeps you safe.</h1>
      <p className="mt-4 text-[17px] leading-relaxed text-text-2">
        JobPilot finds real internships, blocks the scams, and sends only applications you approve, each one backed by proof a recruiter can check. This page says how.
      </p>
      <p className="mt-2 text-[13px] text-text-3">Last updated {UPDATED}. JobPilot is in beta.</p>

      <nav aria-label="On this page" className="mt-8 mb-12 flex flex-wrap gap-2">
        {TOC.map(([id, label]) => (
          <a key={id} href={`#${id}`} className="inline-flex min-h-9 items-center rounded-full border border-border px-3 text-[13px] text-text-2 hover:border-border-strong hover:text-text">
            {label}
          </a>
        ))}
      </nav>

      <Section id="checks" title="What we check">
        <p>
          Before a posting reaches you, Verifier checks it with the same rules as our free{" "}
          <Link href="/scam-check" className="text-cobalt-text hover:underline">
            Scam Shield
          </Link>
          . Postings with a red flag are blocked: they’re never matched to anyone and can’t be approved. Others with a warning show the reason.
        </p>
        <List
          items={[
            "The employer is named, not “a leading MNC” or “our client”.",
            "No money is asked for: training, kit or certificate fees, or “refundable” deposits.",
            "Hiring happens through an application, not only over WhatsApp or Telegram.",
            "The apply link opens and the job is still open, ideally on the company’s own careers system.",
            "The recruiter’s email is on the company’s domain, not a personal address.",
            "No pressure tactics, placement guarantees or implausible pay for an internship.",
            "Ghost-job signals: listings that are old, keep being reposted or can’t be verified.",
          ]}
        />
        <p>
          Before an application reaches you, a guard checks every rewritten resume line against your original. A tool, skill or number you didn’t write is reverted, and the revert is
          logged. Outreach goes only to people and inboxes a company lists publicly, or to a contact provider that cites its sources.
        </p>
      </Section>

      <Section id="never" title="What we never do">
        <List
          items={[
            "Send anything without your approval of that specific item.",
            "Log in to, automate or scrape LinkedIn, or any job-board account (Internshala, Naukri, Unstop, Indeed and the rest).",
            "Press Submit on an application form. The browser extension fills forms; you submit them.",
            "Invent resume content: skills, tools, numbers or experience you didn’t give us.",
            "Guess email addresses, or email anyone a company doesn’t list publicly.",
            "Read your inbox. Gmail access is limited to sending, and every send needs your approval.",
            "Store your prompts or the AI’s replies in run traces. Traces keep timings, token counts and cost.",
            "Sell your data, or use your resume to train AI models.",
          ]}
        />
      </Section>

      <Section id="data" title="Data we store">
        <List
          items={[
            "Your account: name, email address and a hashed password.",
            "Your resume, the skills you confirm, and your search preferences.",
            "What the agents make for you: matches, tailored resumes, drafts and your application tracker.",
            "Your mailbox connection, if you add one: for Gmail, a Google token that can only send email; for other providers, an app password. Either is encrypted with a key kept outside the database, and used only to send what you approve, at least 90 seconds apart.",
            "Your consents: each purpose you agreed to, when, and which version of the notice you saw.",
            "Run traces and AI usage records: which agent ran, how long it took, tokens and cost.",
            "Proof Link opens: the time and browser family only (for example “chrome-mobile”), counted on our server. No IP addresses, cookies or tracking pixels.",
          ]}
        />
        <p>
          We keep your data while your account is open. AI usage records are deleted after 90 days and notifications after 60. Demo accounts are deleted after 24 hours. Accounts nobody has used for 12 months are deleted, after an email notice 30 days before. When you delete your
          account, everything in it is deleted. More detail is in the{" "}
          <Link href="/privacy" className="text-cobalt-text hover:underline">
            privacy policy
          </Link>
          .
        </p>
      </Section>

      <Section id="consent" title="Consent notice">
        <p>
          JobPilot is for students aged 18 or older. Each use of your data is a separate consent you can give or withdraw on its own in Settings → Privacy & consent;
          withdrawing is as easy as agreeing and stops that use at once. We record what you agreed to, when, how, and which version of this notice you saw.
        </p>
        {notice ? (
          <div className="space-y-3">
            {notice.purposes.map((p) => (
              <div key={p.purpose} className="card p-4">
                <div className="text-[15px] font-semibold text-text">{p.description}</div>
                <dl className="mt-2 grid gap-1.5 text-[14px] sm:grid-cols-[110px_1fr]">
                  <dt className="text-text-3">Data used</dt>
                  <dd>{p.data}</dd>
                  <dt className="text-text-3">Why</dt>
                  <dd>{p.why}</dd>
                  <dt className="text-text-3">How long</dt>
                  <dd>{p.retention}</dd>
                  <dt className="text-text-3">To withdraw</dt>
                  <dd>{p.withdraw}</dd>
                </dl>
              </div>
            ))}
            <p className="text-[13px] text-text-3">Notice version {notice.version}.</p>
          </div>
        ) : (
          <p>The itemized notice is shown at sign-up and in Settings → Privacy & consent.</p>
        )}
      </Section>

      <Section id="rights" title="Your rights under the DPDP Act">
        <p>India’s Digital Personal Data Protection Act, 2023 gives you these rights. Most take one click in Settings.</p>
        <List
          items={[
            <>
              <b className="text-text">Access and portability:</b> Settings → Your data → Export downloads everything we hold about you.
            </>,
            <>
              <b className="text-text">Correction:</b> edit your resume, skills and preferences in Settings at any time.
            </>,
            <>
              <b className="text-text">Erasure:</b> Settings → Your data → Delete account removes it all at once.
            </>,
            <>
              <b className="text-text">Withdraw consent:</b> Settings → Privacy & consent. Withdrawing is as easy as agreeing, and switches that feature off at once.
            </>,
            <>
              <b className="text-text">Grievance:</b> use Settings → Your data rights, the form below, or write to the contact below. We aim to reply within 30 days.
            </>,
            <>
              <b className="text-text">Nomination:</b> you can name someone to exercise these rights for you if you die or become unable to. Write to us to set this up.
            </>,
          ]}
        />
      </Section>

      <Section id="grievance" title="Grievance contact">
        <div className="card p-5">
          {GRIEVANCE_OFFICER && <div className="text-[15px] font-semibold text-text">{GRIEVANCE_OFFICER}, Grievance Officer</div>}
          <a href={`mailto:${GRIEVANCE_EMAIL}`} className="mt-1 inline-block text-[15px] text-cobalt-text hover:underline">
            {GRIEVANCE_EMAIL}
          </a>
          <p className="mt-2 text-[14px] text-text-2">
            For privacy questions, complaints or a rights request. If you’re not satisfied with our answer, you can complain to the Data Protection Board of India.
          </p>
        </div>
        {GRIEVANCE_EMAIL !== CONTACT_EMAIL && <p className="text-[14px]">Anything else: {CONTACT_EMAIL}.</p>}
        <div className="card p-5">
          <h3 className="mb-3 text-[15px] font-semibold text-text">Send a request without an account</h3>
          <GrievanceForm />
        </div>
      </Section>

      <Section id="subprocessors" title="Who processes data for us">
        <p>These services process data on our behalf, only to run JobPilot. Sending from your own Gmail goes through your mail provider, under your account with them.</p>
        <div className="card overflow-hidden">
          <table className="w-full text-left text-[14px]">
            <caption className="sr-only">Subprocessors</caption>
            <thead className="border-b border-border bg-elevated text-[12.5px] text-text-3">
              <tr>
                <th scope="col" className="px-4 py-2.5 font-medium">
                  Service
                </th>
                <th scope="col" className="px-4 py-2.5 font-medium">
                  What for
                </th>
                <th scope="col" className="hidden px-4 py-2.5 font-medium sm:table-cell">
                  Where
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {SUBPROCESSORS.map(([name, what, where]) => (
                <tr key={name} className="align-top">
                  <th scope="row" className="px-4 py-3 font-medium text-text">
                    {name}
                  </th>
                  <td className="px-4 py-3">
                    {what}
                    <span className="mt-1 block text-[12.5px] text-text-3 sm:hidden">{where}</span>
                  </td>
                  <td className="hidden px-4 py-3 sm:table-cell">{where}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
    </article>
  );
}

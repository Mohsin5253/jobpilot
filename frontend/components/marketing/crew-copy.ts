import type { AgentKey, CrewKey } from "@/config/agents";

/**
 * Landing-page copy for each crew member: what they do and an example of their output.
 * Sample outputs are illustrative and use fictional companies; the live demo shows real postings.
 */
export const CREW_STORY: { key: AgentKey; job: string; sample: string }[] = [
  { key: "pilot", job: "Leads the crew and tells you the one thing that needs you.", sample: "We found 4 strong matches and drafted 4 emails. Nothing goes out until you approve." },
  { key: "researcher", job: "Finds companies that hire people with your profile and adds their career boards.", sample: "+3 boards to watch · Acme AI, Northwind Labs, Lumen Analytics" },
  { key: "scout", job: "Watches company boards and official job APIs for live openings.", sample: "142 live openings checked · 18 new since yesterday" },
  { key: "verifier", job: "Checks every new job is real: the employer, the apply link, the recruiter and any request for money.", sample: "48 checked · 46 verified · 1 needs care · 1 blocked (training fee)" },
  { key: "matcher", job: "Scores every job against your resume and explains the fit.", sample: "86/100 · Strong: Python, scikit-learn · Missing: Docker" },
  { key: "interviewer", job: "Asks about skills you might have when a job is a near miss.", sample: "“Have you used Docker? It would unlock 3 jobs you nearly match.”" },
  { key: "tailor", job: "Rewrites your bullets for each job. A guard blocks anything you haven’t done.", sample: "4 bullets rewritten · 1 reverted: “Docker” isn’t on your resume" },
  { key: "outreach", job: "Drafts a short email and a referral request to real, public contacts.", sample: "To the hiring lead · 5 lines · referral note ready" },
  { key: "dispatch", job: "Sends only what you approve, from your own mailbox.", sample: "Sent from you@college.edu · tailored resume attached" },
  { key: "tracker", job: "Tracks every application and reminds you to follow up.", sample: "Applied 7 days ago · follow-up ready to review" },
];

/** What happens at each stage of a run, for the scroll-driven flight path. */
export const RUN_STAGES: Record<CrewKey, string> = {
  researcher: "Researcher finds companies that hire for your profile and adds their career boards to the watch list.",
  scout: "Scout pulls fresh openings from company boards and official job APIs, and drops dead links and scams.",
  verifier: "Verifier checks each job is real: a named employer, a live apply link, no fees or chat-only hiring. Scams never reach you.",
  matcher: "Matcher scores every posting against your resume, then explains the fit and the gaps.",
  interviewer: "Interviewer asks about one missing skill when a job is a near miss, then re-scores.",
  tailor: "Tailor rewrites your bullets for the best fits. The guard reverts anything that isn’t on your resume.",
  outreach: "Outreach drafts a short email and a referral request to real, publicly listed people.",
  you: "Your turn. You read, edit and approve each draft. Nothing is sent before this.",
  dispatch: "Dispatch sends what you approved, from your own mailbox, with the tailored resume attached.",
  tracker: "Tracker files it on your board and reminds you to follow up after seven days.",
  pilot: "",
};

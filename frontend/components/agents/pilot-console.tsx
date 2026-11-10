"use client";

import { ArrowRight, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { AgentHero, type AgentStatus } from "@/components/agents/agent-avatar";
import { RunButton } from "@/components/shell";
import { Button, buttonClass } from "@/components/ui/button";
import { StatusPill } from "@/components/ui/status-dot";
import { isActive, useRetryRun } from "@/lib/queries";
import type { Overview, Run } from "@/lib/types";
import { ago, ms, usd } from "@/lib/utils";

/** While a stage runs, Pilot relays what that agent is doing, in the crew's voice. */
const WORKING_LINES: Record<string, string> = {
  researcher: "Researcher is looking for companies that hire people with your profile, and checking their career boards.",
  scout: "Scout is pulling fresh openings from career boards and job feeds, keeping only live, recent roles.",
  matcher: "Matcher is reading every posting against your resume and scoring the fit.",
  interviewer: "Interviewer is working out which skills would unlock the jobs you nearly match.",
  tailor: "Tailor is rewriting your bullets for the best matches. Only things you’ve actually done.",
  outreach: "Outreach is drafting short, specific emails to the recruiters.",
  dispatch: "Dispatch is sending the applications you approved.",
  tracker: "Tracker is updating your board and lining up follow-up reminders.",
};

/** How the latest run reads as a status pill. */
export const RUN_STATUS: Record<Run["status"], { status: AgentStatus; label: string }> = {
  queued: { status: "idle", label: "Queued" },
  running: { status: "running", label: "Running" },
  resume_queued: { status: "running", label: "Resuming" },
  awaiting_approval: { status: "your-turn", label: "Needs you" },
  completed: { status: "done", label: "Completed" },
  failed: { status: "error", label: "Failed" },
};

interface Speech {
  status: AgentStatus;
  text: string;
  action?: ReactNode;
}

const cta = (href: string, label: string) => (
  <Link href={href} className={buttonClass({ variant: "primary", className: "h-11 w-full sm:h-9 sm:w-auto" })}>
    {label} <ArrowRight />
  </Link>
);

function speech(o: Overview | undefined, firstName: string, retry: ReactNode): Speech {
  const hi = firstName ? `Hi ${firstName}. ` : "Hi. ";
  const run = o?.last_run;
  if (!o) return { status: "idle", text: "Checking in with the crew…" };
  if (!run && !o.pending_approvals && !o.open_questions) {
    return {
      status: "idle",
      text: `${hi}I’m Pilot. My crew finds real internships, scores how well each one fits you, tailors your resume and drafts the emails. Nothing goes out until you say so. Shall we start?`,
      action: (
        <div className="[&>button]:h-11 [&>button]:w-full sm:[&>button]:h-9 sm:[&>button]:w-auto">
          <RunButton />
        </div>
      ),
    };
  }
  if (run?.status === "queued" || run?.status === "resume_queued") return { status: "running", text: "Getting the crew ready. This takes a few seconds." };
  if (run?.status === "running") return { status: "running", text: WORKING_LINES[run.current_step ?? ""] ?? "The crew is working on it." };
  if (run?.status === "failed") {
    return {
      status: "error",
      text: `Something broke during ${run?.current_step ?? "the run"}. I saved our progress, so a retry picks up where we stopped.`,
      action: retry,
    };
  }
  if (run?.status === "awaiting_approval" || o.pending_approvals) {
    const n = o.pending_approvals;
    return {
      status: "your-turn",
      text: `We found ${o.strong_matches} strong match${o.strong_matches === 1 ? "" : "es"} and drafted ${n} email${n === 1 ? "" : "s"} with tailored resumes. Nothing goes out until you approve it.`,
      action: cta("/approvals", `Review ${n} draft${n === 1 ? "" : "s"}`),
    };
  }
  if (o.open_questions) {
    return {
      status: "your-turn",
      text: `Interviewer has ${o.open_questions} quick question${o.open_questions === 1 ? "" : "s"} about your skills. Answering could unlock jobs you nearly match.`,
      action: cta("/skills", "Answer questions"),
    };
  }
  if (!run) return { status: "idle", text: "The crew is standing by." };
  const s = run.stats ?? {};
  const found = s.new_jobs ?? 0;
  const strong = s.strong_matches ?? 0;
  const added = s.boards_added ?? 0;
  const parts = [
    `We checked ${s.jobs_fetched ?? 0} live openings ${ago(run.finished_at ?? run.created_at)}`,
    found ? `${found} new` : "nothing new since last time",
    strong ? `${strong} strong match${strong === 1 ? "" : "es"}` : "",
    added ? `and ${added} new compan${added === 1 ? "y" : "ies"} to watch` : "",
  ].filter(Boolean);
  return {
    status: strong ? "done" : "idle",
    text: `${parts.join(", ")}. I’ll keep watching and tell you when something that fits opens up.`,
    action: strong ? cta("/jobs", "See matches") : undefined,
  };
}

const SEEN_KEY = "jp-pilot-seen";

/** New messages stream in; a message you've already read appears at once. Reduced motion never streams. */
function useStream(text: string) {
  const [shown, setShown] = useState(text);
  useEffect(() => {
    let seen: string | null = null;
    try {
      seen = sessionStorage.getItem(SEEN_KEY);
      sessionStorage.setItem(SEEN_KEY, text);
    } catch {}
    if (seen === text || matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setShown(text);
      return;
    }
    setShown("");
    let i = 0;
    const timer = setInterval(() => {
      i += 3;
      setShown(text.slice(0, i));
      if (i >= text.length) clearInterval(timer);
    }, 28);
    return () => clearInterval(timer);
  }, [text]);
  return { shown, done: shown.length >= text.length };
}

/**
 * Pilot on the left, facing right toward the speech bubble: the latest message, one primary action,
 * and the run's mono meta row with a link to its trace. The view's one large character.
 */
export function PilotConsole({ overview, firstName }: { overview?: Overview; firstName: string }) {
  const retryRun = useRetryRun();
  const run = overview?.last_run;
  const retry = run ? (
    <div className="flex flex-col gap-2 sm:flex-row">
      <Button variant="primary" className="h-11 w-full sm:h-9 sm:w-auto" loading={retryRun.isPending} onClick={() => retryRun.mutate(run.id)}>
        {!retryRun.isPending && <RotateCcw className="size-4" />} Retry from {run.current_step ?? "the last step"}
      </Button>
      <Link href={`/runs/${run.id}`} className={buttonClass({ variant: "ghost", className: "h-11 w-full sm:h-9 sm:w-auto" })}>
        See what happened
      </Link>
    </div>
  ) : null;
  const s = useMemo(() => speech(overview, firstName, retry), [overview, firstName, retry]);
  const { shown, done } = useStream(s.text);
  const meta = run ? RUN_STATUS[run.status] : null;

  return (
    <div className="grid grid-cols-[96px_minmax(0,1fr)] items-start gap-x-4 gap-y-4 p-4 sm:grid-cols-[112px_minmax(0,1fr)] md:grid-cols-[160px_minmax(0,1fr)] md:gap-x-6 md:p-6 xl:grid-cols-[184px_minmax(0,1fr)]">
      <div className="aspect-square w-full">
        <AgentHero agent="pilot" status={isActive(run) ? "running" : s.status} size={184} fluid sizes="(min-width: 1280px) 184px, (min-width: 768px) 160px, 112px" />
      </div>

      <div className="min-w-0 md:pt-2">
        <div className="mb-2 flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
          <span className="text-[14px] font-semibold">Pilot</span>
          <span className="text-[12.5px] text-text-3">
            Leads your crew
            {run ? ` · ${run.trigger === "scheduled" || run.trigger === "research" ? "auto run" : "run"} ${ago(run.created_at)}` : ""}
          </span>
        </div>
        {/* The bubble's tail points back at Pilot. */}
        <div className="relative rounded-[var(--radius-card)] border border-border-strong bg-elevated px-4 py-3 md:px-5 md:py-4">
          <span aria-hidden className="absolute top-5 -left-[7px] size-3 rotate-45 border-b border-l border-border-strong bg-elevated" />
          <p aria-live="polite" className="text-[14px] leading-relaxed text-text md:text-[15px]">
            <span className="sr-only">{s.text}</span>
            <span aria-hidden>
              {shown}
              {!done && <span className="ml-0.5 inline-block h-4 w-[2px] translate-y-0.5 animate-pulse-soft bg-cobalt" />}
            </span>
          </p>
        </div>
      </div>

      {/* Action and meta span the full width on phones (thumb-sized CTA), sit under the bubble from 640px. */}
      {(s.action || meta) && (
        <div className="col-span-2 space-y-3 sm:col-span-1 sm:col-start-2 sm:-mt-1">
          {s.action && <div className={done ? "animate-[fade-in_var(--dur-base)_var(--ease)]" : "invisible"}>{s.action}</div>}
          {run && meta && (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[12.5px] text-text-3">
              <StatusPill status={meta.status}>{meta.label}</StatusPill>
              <span className="num">{usd(Number(run.cost_usd), 2)}</span>
              <span aria-hidden>·</span>
              <span className="num">{ms(run.stats?.active_ms)}</span>
              <span aria-hidden>·</span>
              <span className="num">
                {run.llm_calls} LLM call{run.llm_calls === 1 ? "" : "s"}
              </span>
              <Link href={`/runs/${run.id}`} className="ml-auto inline-flex min-h-11 items-center gap-1 rounded-[6px] font-medium text-cobalt-text hover:underline md:min-h-0">
                Trace <ArrowRight className="size-3.5" />
              </Link>
            </div>
          )}
          {run?.status === "failed" && run.error && (
            <pre className="num overflow-x-auto rounded-[var(--radius-control)] border border-[color-mix(in_oklab,var(--error)_30%,transparent)] bg-[color-mix(in_oklab,var(--error)_8%,transparent)] px-3 py-2 text-[12px] whitespace-pre-wrap text-[var(--error)]">
              {run.error}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

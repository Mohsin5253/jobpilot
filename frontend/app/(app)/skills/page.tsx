"use client";

import { ArrowRight, Check, ShieldCheck, Sparkles, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useState } from "react";

import { AgentHero } from "@/components/agents/agent-avatar";
import { Badge } from "@/components/ui/badge";
import { Button, buttonClass } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Textarea } from "@/components/ui/input";
import { EmptyState, PageHeader, Skeleton } from "@/components/ui/misc";
import { useAnswerQuestions, useDismissQuestion, useQuestions } from "@/lib/queries";
import type { SkillQuestion } from "@/lib/types";
import { cn } from "@/lib/utils";

const MIN_DETAILS = 15;

type Draft = { has: boolean | null; details: string };

function QuestionCard({ q, value, onChange, onDismiss, i }: { q: SkillQuestion; value: Draft; onChange: (v: Draft) => void; onDismiss: () => void; i: number }) {
  const tooShort = value.has === true && value.details.trim().length < MIN_DETAILS;
  return (
    <motion.li layout initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, x: -30 }} transition={{ delay: i * 0.04, duration: 0.22 }}>
      <Card className={cn("p-5 transition-colors duration-[var(--dur-base)]", value.has === true && "border-[color-mix(in_oklab,var(--done)_40%,transparent)]", value.has === false && "opacity-70")}>
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <Badge tone="accent">{q.skill}</Badge>
              <span className="num inline-flex items-center gap-1 rounded-full bg-[color-mix(in_oklab,var(--done)_12%,transparent)] px-2 py-0.5 text-[12px] font-medium text-done">
                +{q.unlocks} job{q.unlocks === 1 ? "" : "s"} if yes
              </span>
            </div>
            <p className="text-[15px] leading-relaxed font-medium">{q.question}</p>
            {!!q.jobs.length && <p className="mt-1.5 text-[13px] text-text-2">For: {q.jobs.join(" · ")}</p>}
          </div>
          <button type="button" onClick={onDismiss} className="min-h-9 shrink-0 rounded-[var(--radius-control)] px-2 text-[12.5px] text-text-3 hover:bg-elevated hover:text-text" title="Don’t ask about this skill again">
            Skip
          </button>
        </div>

        <div role="radiogroup" aria-label={`Do you have ${q.skill}?`} className="mt-4 flex gap-2">
          <Button role="radio" aria-checked={value.has === true} className="h-11 md:h-8" size="sm" variant={value.has === true ? "success" : "secondary"} onClick={() => onChange({ ...value, has: true })}>
            <Check /> Yes, I have
          </Button>
          <Button role="radio" aria-checked={value.has === false} className="h-11 md:h-8" size="sm" variant={value.has === false ? "danger" : "secondary"} onClick={() => onChange({ ...value, has: false })}>
            <X /> Not yet
          </Button>
        </div>

        <AnimatePresence>
          {value.has === true && (
            <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} className="overflow-hidden">
              <Textarea
                autoFocus
                value={value.details}
                onChange={(e) => onChange({ ...value, details: e.target.value })}
                placeholder={`e.g. "Containerized my Flask movie recommender with ${q.skill} for a college project and deployed it to a VM."`}
                className="mt-3 min-h-20"
                aria-label={`How you’ve used ${q.skill}`}
              />
              <p className={cn("mt-1 text-[12.5px]", tooShort ? "text-your-turn" : "text-text-3")}>
                {tooShort ? "Add one concrete sentence. Tailor can only use what you write here." : "Saved to your profile in your words. Tailor may rephrase it, never embellish it."}
              </p>
            </motion.div>
          )}
        </AnimatePresence>
      </Card>
    </motion.li>
  );
}

export default function SkillsPage() {
  const { data: questions, isLoading } = useQuestions();
  const answer = useAnswerQuestions();
  const dismiss = useDismissQuestion();
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});

  const get = (id: string): Draft => drafts[id] ?? { has: null, details: "" };
  const ready = (questions ?? []).filter((q) => {
    const d = get(q.id);
    return d.has === false || (d.has === true && d.details.trim().length >= MIN_DETAILS);
  });
  const unlocks = ready.filter((q) => get(q.id).has).reduce((n, q) => n + q.unlocks, 0);

  const submit = () =>
    answer.mutate(
      ready.map((q) => ({ id: q.id, has_skill: !!get(q.id).has, details: get(q.id).details.trim() })),
      { onSuccess: () => setDrafts({}) },
    );

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title="Skill check" description="Your resume nearly fits these jobs. Interviewer asks about the gaps instead of giving up on them." />

      {/* Interviewer asks: the page's one large character. */}
      {!!questions?.length && (
        <div className="mb-6 flex items-start gap-4 md:gap-6">
          <div className="hidden shrink-0 sm:block">
            <AgentHero agent="interviewer" size={120} />
          </div>
          <div className="relative min-w-0 flex-1 rounded-[var(--radius-card)] border border-border-strong bg-elevated px-4 py-3 md:px-5 md:py-4">
            <span aria-hidden className="absolute top-6 -left-[7px] hidden size-3 rotate-45 border-b border-l border-border-strong bg-elevated sm:block" />
            <div className="mb-1 text-[13px] font-semibold">Interviewer</div>
            <p className="text-[14.5px] leading-relaxed">
              I have {questions.length} quick question{questions.length === 1 ? "" : "s"}. Say yes only for skills you’ve really used, in one sentence. Then I re-score the jobs each one unlocks, and Tailor prepares any that now fit.
            </p>
          </div>
        </div>
      )}

      <div className="mb-5 flex items-start gap-3 rounded-[var(--radius-card)] border border-border bg-elevated px-4 py-3 text-[13px] text-text-2">
        <ShieldCheck className="mt-0.5 size-4 shrink-0 text-done" />
        <span>A yes adds the skill to your profile in your own words. Nothing is added that you didn’t write.</span>
      </div>

      {isLoading ? (
        <Skeleton agent="interviewer" className="min-h-64" />
      ) : !questions?.length ? (
        <Card>
          <EmptyState
            agent="interviewer"
            action={
              <Link href="/jobs" className={buttonClass({ variant: "secondary" })}>
                Browse matches <ArrowRight />
              </Link>
            }
          />
        </Card>
      ) : (
        <>
          <ul className="space-y-3">
            <AnimatePresence initial={false}>
              {questions.map((q, i) => (
                <QuestionCard key={q.id} q={q} i={i} value={get(q.id)} onChange={(v) => setDrafts((d) => ({ ...d, [q.id]: v }))} onDismiss={() => dismiss.mutate(q.id)} />
              ))}
            </AnimatePresence>
          </ul>
          {/* Sticky from 768px; on phones it sits after the list, clear of the tab bar and Run button. */}
          <div className="md:sticky md:bottom-4 mt-6 flex flex-col gap-3 rounded-[var(--radius-panel)] border border-border bg-surface/95 p-3 shadow-[var(--shadow-2)] backdrop-blur sm:flex-row sm:items-center sm:justify-between sm:pl-5">
            <span className="text-[13.5px] text-text-2">
              {ready.length ? (
                <>
                  {ready.length} answer{ready.length === 1 ? "" : "s"} ready{unlocks ? ` · re-checks up to ${unlocks} job${unlocks === 1 ? "" : "s"}` : ""}
                </>
              ) : (
                "Answer one or more questions"
              )}
            </span>
            <Button variant="primary" className="h-11 md:h-9" disabled={!ready.length} loading={answer.isPending} onClick={submit}>
              {!answer.isPending && <Sparkles />} Submit and re-check jobs
            </Button>
          </div>
        </>
      )}
    </div>
  );
}

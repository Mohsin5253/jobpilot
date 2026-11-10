"use client";

import { ArrowUpRight, Check, CircleSlash, Copy, ExternalLink, FileDown, Globe2, MapPin, ShieldAlert, ShieldCheck, Sparkles, Star } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { ResumeDiff } from "@/components/approvals/resume-diff";
import { QualityGate } from "@/components/jobs/quality-gate";
import { MatchRow, SkillChips, STAGE_META } from "@/components/match-row";
import { RecipientCard } from "@/components/recipient-card";
import { RecipientField, SendActions } from "@/components/send-actions";
import { Badge } from "@/components/ui/badge";
import { Button, buttonClass } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Textarea } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/misc";
import { ScoreBar, ScoreRing } from "@/components/ui/score-ring";
import { reserveTab, sendTo, SOURCE_LABEL } from "@/lib/compose";
import { isActive, useApply, useEditDraft, useEvidence, useInsights, useMatch, useOverview, usePrepare, useSetOutcome, useSimilar, useUpdateMatch } from "@/lib/queries";
import type { Match, Outcome, Stage } from "@/lib/types";
import { ago, cn, salary } from "@/lib/utils";

const FLOW: Stage[] = ["found", "shortlisted", "applied", "interview", "offer", "rejected", "archived"];

function copy(text: string, what: string) {
  navigator.clipboard.writeText(text).then(() => toast.success(`${what} copied`));
}

/** Pill choices (stage, outcome, PPO): the selected one is solid cobalt. */
function Pill({ on, onClick, children, className }: { on: boolean; onClick: () => void; children: React.ReactNode; className?: string }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={cn(
        "min-h-9 rounded-full border px-3 text-[13px] transition-colors duration-[var(--dur-fast)] md:min-h-8",
        on ? "border-transparent bg-cobalt font-medium text-on-cobalt" : "border-border text-text-2 hover:border-border-strong hover:text-text",
        className,
      )}
    >
      {children}
    </button>
  );
}

const OUTCOME_LABEL: { v: Outcome; label: string }[] = [
  { v: "replied", label: "They replied" },
  { v: "interview", label: "Interview" },
  { v: "offer", label: "Offer" },
  { v: "rejected", label: "Rejected" },
  { v: "no_reply", label: "No reply" },
];

/** The feedback loop: what happened after you applied. Interviews, offers and rejections also move the card. */
function OutcomeBar({ m }: { m: Match }) {
  const set = useSetOutcome();
  const { data: ins } = useInsights();
  const [why, setWhy] = useState(false);
  const isIntern = /intern/i.test(m.job.title);
  const update = useUpdateMatch();
  return (
    <div className="mt-5 rounded-[var(--radius-card)] border border-border bg-elevated p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="eyebrow mr-1">What happened?</span>
        {OUTCOME_LABEL.map((o) => (
          <Pill key={o.v} on={m.outcome === o.v} onClick={() => (o.v === "rejected" ? setWhy(true) : set.mutate({ id: m.id, outcome: o.v }))}>
            {o.label}
          </Pill>
        ))}
        <span className="num ml-auto text-[12px] text-text-3">Resume version {m.resume_variant}</span>
      </div>
      {why && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {(ins?.reason_options ?? []).map((r) => (
            <Pill key={r} on={false} onClick={() => (set.mutate({ id: m.id, outcome: "rejected", rejection_reason: r }), setWhy(false))}>
              {r}
            </Pill>
          ))}
        </div>
      )}
      {m.outcome === "rejected" && m.rejection_reason && <div className="mt-2 text-[12.5px] text-text-3">Reason: {m.rejection_reason}</div>}
      {isIntern && (m.outcome === "offer" || m.ppo_status !== "none") && (
        <div className="mt-3 flex flex-wrap items-center gap-2 text-[13px]">
          <span className="text-text-2">Pre-placement offer:</span>
          {(["eligible", "offered", "converted"] as const).map((p) => (
            <Pill key={p} on={m.ppo_status === p} onClick={() => update.mutate({ id: m.id, ppo_status: p })} className="capitalize">
              {p}
            </Pill>
          ))}
        </div>
      )}
    </div>
  );
}

/** Skills on this job that your proof pack backs with evidence. */
function Evidenced({ strengths }: { strengths: string[] }) {
  const { data: ev } = useEvidence();
  const proven = new Set((ev?.skills ?? []).map((s) => s.toLowerCase()));
  const hits = strengths.filter((s) => proven.has(s.toLowerCase()));
  if (!hits.length) return null;
  return (
    <p className="mt-2 inline-flex flex-wrap items-center gap-1.5 text-[12.5px] text-text-2">
      <ShieldCheck className="size-3.5 text-cobalt-text" /> Evidenced by your proof pack: <b className="text-text">{hits.join(", ")}</b>
    </p>
  );
}

/**
 * Everything about one match. It lays itself out from its own width (container query), so the same view
 * works as a full page and inside the Matches side sheet.
 */
export function MatchDetail({ id, compact = false }: { id: string; compact?: boolean }) {
  const { data: m, isLoading } = useMatch(id);
  const { data: similar } = useSimilar(id);
  const update = useUpdateMatch();
  const editDraft = useEditDraft();
  const applyMut = useApply();
  const prepare = usePrepare();
  const { data: overview } = useOverview();
  const busy = isActive(overview?.last_run);
  const [to, setTo] = useState("");
  const [notes, setNotes] = useState("");
  const [showAll, setShowAll] = useState(false);

  useEffect(() => setNotes(m?.notes ?? ""), [m?.notes]);
  const lastDraft = m?.drafts.at(-1);
  useEffect(() => setTo(lastDraft?.to_email ?? ""), [lastDraft?.id, lastDraft?.to_email]);

  if (isLoading || !m) return <Skeleton agent="matcher" className="min-h-80" />;

  const { job } = m;

  // Company ATSs have no public "submit" API: open the real application page with the tailored
  // bullets on the clipboard, and record the application here.
  const applyNow = () => {
    const tab = reserveTab();
    const bullets = m.tailored?.bullets.map((b) => `• ${b.rewritten}`).join("\n");
    if (bullets) navigator.clipboard?.writeText(bullets).catch(() => {});
    const go = () => {
      sendTo(tab, job.url);
      if (bullets) toast.message("Tailored bullets copied", { description: "Paste them into the application form." });
    };
    if (m.stage === "applied") return go();
    applyMut.mutate(m.id, { onSuccess: go, onError: () => tab?.close() });
  };
  const pay = salary(job.salary_min, job.salary_max);
  const draft = m.drafts.at(-1);
  const preparing = busy && overview?.last_run?.trigger === "prepare";

  return (
    <div className="@container/md space-y-5">
      <Card className={cn("p-5", !compact && "md:p-6")}>
        <div className="flex flex-col gap-5 @2xl/md:flex-row @2xl/md:items-start">
          <div className="flex min-w-0 flex-1 gap-4">
            <ScoreRing score={m.score} size={compact ? 64 : 80} stroke={6} />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className={cn("font-display leading-tight break-words", compact ? "text-[22px]" : "text-[clamp(24px,3vw,32px)]")}>{job.title}</h1>
                <Badge tone={STAGE_META[m.stage].tone}>{STAGE_META[m.stage].label}</Badge>
              </div>
              <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13.5px] text-text-2">
                <span className="font-medium text-text">{job.company}</span>
                <span className="inline-flex items-center gap-1">
                  {job.remote ? <Globe2 className="size-3.5" /> : <MapPin className="size-3.5" />}
                  {job.remote ? `Remote${job.location ? ` · ${job.location}` : ""}` : job.location}
                </span>
                {pay && <span className="num">₹{pay}</span>}
                <span>Posted {ago(job.posted_at)}</span>
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                <Badge tone={job.track === "technical" ? "accent" : "neutral"}>{job.track === "technical" ? "Technical" : "Non-technical"}</Badge>
                {job.link_status === "ok" ? (
                  <Badge tone="success">
                    <ShieldCheck /> Link checked{job.verified_at ? ` ${ago(job.verified_at)}` : ""}
                  </Badge>
                ) : job.link_status === "unverified" ? (
                  <Badge tone="outline" title="The site blocks automated checks; the posting was indexed recently">
                    Listed recently · site blocks auto-checks
                  </Badge>
                ) : null}
                {job.ghost_risk !== "low" && (
                  <Badge tone={job.ghost_risk === "high" ? "danger" : "warning"} title={job.ghost_reasons.join(" · ")}>
                    <ShieldAlert /> {job.ghost_risk === "high" ? "Likely ghost job" : "Check before applying"}
                  </Badge>
                )}
                {job.url && (
                  <a href={job.url} target="_blank" rel="noreferrer" className="inline-flex items-center px-1 text-[12.5px] text-text-3 hover:text-text hover:underline">
                    via {job.publisher ?? SOURCE_LABEL[job.source] ?? job.source}
                  </a>
                )}
              </div>
            </div>
          </div>
          <div className="flex flex-col gap-2 @2xl/md:w-48">
            {job.url && (
              <>
                <Button variant="primary" className="h-11 w-full md:h-9" onClick={applyNow} loading={applyMut.isPending}>
                  {m.stage === "applied" ? "Open application" : "Apply now"} <ArrowUpRight />
                </Button>
                <a href={job.url} target="_blank" rel="noreferrer" className="text-center text-[12.5px] text-text-3 hover:text-text">
                  View posting only
                </a>
              </>
            )}
            <div className="flex items-center justify-center" role="group" aria-label="Rate this match">
              {[1, 2, 3, 4, 5].map((n) => (
                <button key={n} type="button" onClick={() => update.mutate({ id, user_rating: n })} aria-label={`Rate ${n} of 5`} aria-pressed={(m.user_rating ?? 0) >= n} className="grid size-9 place-items-center md:size-7">
                  <Star className={cn("size-4", (m.user_rating ?? 0) >= n ? "fill-[var(--your-turn-fill)] text-[var(--your-turn-fill)]" : "text-border-strong hover:text-[var(--your-turn-fill)]")} />
                </button>
              ))}
            </div>
            <span className="text-center text-[11.5px] text-text-3">Rate the fit · improves scoring</span>
          </div>
        </div>

        <div className="mt-5 flex gap-3 rounded-[var(--radius-card)] border border-border bg-elevated p-4">
          <AgentAvatar agent="matcher" size={32} decorative />
          <p className="text-[14px] leading-relaxed text-text">
            <span className="mr-1 font-semibold">Matcher:</span>
            {m.explanation}
          </p>
        </div>

        {job.legit_status && (
          <div
            className={cn(
              "mt-3 flex gap-3 rounded-[var(--radius-card)] border p-4",
              job.legit_status === "verified" ? "border-border bg-elevated" : job.legit_status === "caution" ? "border-[color-mix(in_oklab,var(--your-turn-fill)_35%,transparent)] bg-[color-mix(in_oklab,var(--your-turn-fill)_8%,transparent)]" : "border-[color-mix(in_oklab,var(--error)_35%,transparent)] bg-[color-mix(in_oklab,var(--error)_8%,transparent)]",
            )}
          >
            <AgentAvatar agent="verifier" size={32} status={job.legit_status === "verified" ? "done" : job.legit_status === "caution" ? "your-turn" : "error"} decorative />
            <div className="min-w-0 text-[14px] leading-relaxed">
              <span className="mr-1 font-semibold">Verifier:</span>
              {job.legit_status === "verified" ? "This job checks out." : job.legit_status === "caution" ? "Worth a closer look before you apply." : "This looks like a scam. I kept it out of your matches."}
              {job.legit_reasons.length > 0 && (
                <ul className="mt-1.5 space-y-0.5 text-[13px] text-text-2">
                  {job.legit_reasons.map((r) => (
                    <li key={r} className="flex gap-2">
                      {job.legit_status === "verified" ? <Check className="mt-1 size-3.5 shrink-0 text-done" aria-hidden /> : <ShieldAlert className="mt-1 size-3.5 shrink-0" aria-hidden />}
                      {r}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}

        {job.apply_links.length > 1 && (
          <div className="mt-5 flex flex-wrap items-center gap-2">
            <span className="text-[13px] text-text-2">Also listed on:</span>
            {job.apply_links.map((a) => (
              <a key={a.url} href={a.url} target="_blank" rel="noreferrer" className={buttonClass({ size: "sm", variant: a.direct ? "primary" : "secondary" })}>
                {a.direct ? "Company site" : `Apply on ${a.publisher ?? "board"}`} <ArrowUpRight />
              </a>
            ))}
          </div>
        )}

        {m.applied_at && <OutcomeBar m={m} />}

        <div className="mt-5 border-t border-border pt-5">
          <div className="eyebrow mb-2">Stage</div>
          <div className="flex flex-wrap items-center gap-1.5">
            {FLOW.map((s) => (
              <Pill key={s} on={m.stage === s} onClick={() => update.mutate({ id, stage: s })}>
                {STAGE_META[s].label}
              </Pill>
            ))}
            {m.follow_up_at && <span className="ml-auto text-[12.5px] text-text-3">Follow up {ago(m.follow_up_at)}</span>}
          </div>
        </div>
      </Card>

      <div className="grid gap-5 @4xl/md:grid-cols-3 [&>*]:min-w-0">
        <div className="space-y-5 @4xl/md:col-span-2">
          <Card className="p-5">
            {!m.tailored ? (
              <div className="flex flex-col items-center gap-3 py-6 text-center">
                <AgentAvatar agent="tailor" size={48} status={preparing ? "running" : "idle"} decorative />
                <p className="max-w-sm text-[13.5px] text-text-2">
                  {preparing ? "Tailor is rewriting your bullets and Outreach is drafting the email…" : "I tailor automatically for jobs above your minimum fit score. Want this one anyway?"}
                </p>
                <Button variant="primary" onClick={() => prepare.mutate(m.id)} loading={prepare.isPending || preparing} disabled={busy}>
                  <Sparkles /> Prepare application
                </Button>
              </div>
            ) : (
              <>
                <ResumeDiff match={m} matchId={m.id} editable />
                <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-border pt-4">
                  <a href={`/api/matches/${m.id}/resume?format=docx`} download className={buttonClass({ size: "sm" })}>
                    <FileDown /> DOCX
                  </a>
                  <Button size="sm" variant="ghost" onClick={() => copy(m.tailored!.bullets.map((b) => `• ${b.declined || b.reverted ? b.original : b.rewritten}`).join("\n"), "All bullets")}>
                    <Copy /> Copy all bullets
                  </Button>
                </div>
              </>
            )}
          </Card>

          <Card>
            <CardHeader title="Job description" />
            <div className="p-5 pt-3">
              <div className={cn("prose-job relative text-[14px] text-text-2", !showAll && "max-h-72 overflow-hidden")}>
                {job.description}
                {!showAll && <div className="absolute inset-x-0 bottom-0 h-20 bg-gradient-to-t from-[var(--surface)] to-transparent" />}
              </div>
              <button type="button" onClick={() => setShowAll((v) => !v)} className="mt-2 min-h-9 text-[13px] font-medium text-cobalt-text hover:underline">
                {showAll ? "Show less" : "Show full description"}
              </button>
            </div>
          </Card>
        </div>

        <div className="space-y-5">
          <Card>
            <CardHeader title="Why this score" description="A blend of three independent signals" />
            <div className="space-y-4 p-5">
              <ScoreBar label="Semantic similarity" value={m.semantic_score} />
              <ScoreBar label="Skill coverage" value={m.skill_score} />
              <ScoreBar label="LLM recruiter review" value={m.llm_score} hint="offline" />
              <div className="border-t border-border pt-4">
                <SkillChips strengths={m.strengths} gaps={m.gaps} max={10} />
                <p className="mt-2 text-[12px] text-text-3">Green: you have it · dashed: a gap</p>
                <Evidenced strengths={m.strengths} />
              </div>
            </div>
          </Card>

          <QualityGate m={m} />

          <Card>
            <CardHeader
              title="Outreach"
              description={draft ? `Draft ${draft.status}` : "No draft for this job yet"}
              action={
                draft?.status === "pending" && (
                  <Link href={`/approvals?draft=${draft.id}`} className="inline-flex min-h-9 items-center text-[13px] font-medium text-cobalt-text hover:underline">
                    Review
                  </Link>
                )
              }
            />
            {draft && (
              <div className="space-y-3 p-5">
                <RecipientCard matchId={m.id} draftId={draft.id} contactId={draft.contact_id} toEmail={draft.to_email} ccEmail={draft.cc_email} editable={draft.status === "pending" || draft.status === "approved"} />
                <div className="rounded-[var(--radius-card)] border border-border bg-elevated p-4">
                  <div className="mb-2 text-[13.5px] font-semibold">{draft.subject}</div>
                  <p className="text-[13.5px] leading-relaxed whitespace-pre-line text-text-2">{draft.email_body}</p>
                </div>
                {(draft.status === "approved" || draft.status === "sent") && (
                  <div className="space-y-3">
                    <RecipientField
                      value={to}
                      onChange={setTo}
                      found={job.recruiter_email}
                      disabled={draft.status === "sent"}
                      onCommit={() => to.trim() !== (draft.to_email ?? "") && editDraft.mutate({ id: draft.id, to_email: to.trim() })}
                    />
                    <SendActions
                      mail={{ to, cc: draft.cc_email, subject: draft.subject, body: draft.email_body }}
                      draftId={draft.id}
                      matchId={m.id}
                      jobUrl={job.url}
                      bullets={m.tailored?.bullets.map((b) => b.rewritten)}
                      sent={draft.status === "sent"}
                    />
                    <div className="flex flex-wrap gap-2">
                      <Button size="sm" variant="ghost" onClick={() => copy(draft.email_body, "Email")}>
                        <Copy /> Copy email
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => copy(draft.linkedin_note, "LinkedIn note")}>
                        <Copy /> LinkedIn note
                      </Button>
                      {draft.status === "sent" && (
                        <Badge tone="success" className="self-center">
                          <Check /> Sent {ago(draft.sent_at)}
                        </Badge>
                      )}
                    </div>
                  </div>
                )}
                {draft.status === "rejected" && (
                  <p className="inline-flex items-center gap-1.5 text-[13px] text-text-3">
                    <CircleSlash className="size-3.5" /> You rejected this draft
                  </p>
                )}
              </div>
            )}
          </Card>

          <Card>
            <CardHeader title="Notes" />
            <div className="p-5 pt-3">
              <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Recruiter name, referral, interview prep…" aria-label="Notes" />
              {notes !== (m.notes ?? "") && (
                <Button size="sm" variant="primary" className="mt-2" onClick={() => update.mutate({ id, notes }, { onSuccess: () => toast.success("Notes saved") })}>
                  Save notes
                </Button>
              )}
            </div>
          </Card>

          {!!similar?.length && (
            <Card>
              <CardHeader title="Similar roles" description="Nearest neighbours by meaning" />
              <div className="p-2">
                {similar.map((s) => (
                  <MatchRow key={s.id} m={s} />
                ))}
              </div>
            </Card>
          )}

          {job.url && (
            <a href={job.url} target="_blank" rel="noreferrer" className="flex min-h-9 items-center justify-center gap-1.5 text-[12.5px] text-text-3 hover:text-text">
              <ExternalLink className="size-3.5" /> {new URL(job.url).hostname}
            </a>
          )}
        </div>
      </div>
    </div>
  );
}

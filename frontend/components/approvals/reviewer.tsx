"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowUpRight, Check, ChevronDown, ChevronUp, Eye, FileDown, Linkedin, Mail, MoreHorizontal, Paperclip, Pencil, RefreshCw, Send, ShieldAlert, ShieldCheck, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { ResumeDiff } from "@/components/approvals/resume-diff";
import { GateRules } from "@/components/jobs/quality-gate";
import { RecipientCard } from "@/components/recipient-card";
import { GmailIcon, RecipientField, SendActions } from "@/components/send-actions";
import { Badge } from "@/components/ui/badge";
import { Button, buttonClass } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent } from "@/components/ui/dialog";
import { Input, Textarea } from "@/components/ui/input";
import { Kbd, Segmented, Skeleton } from "@/components/ui/misc";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ScoreBar, ScoreRing } from "@/components/ui/score-ring";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip } from "@/components/ui/tooltip";
import { api } from "@/lib/api";
import { SOURCE_LABEL } from "@/lib/compose";
import { useMatch, usePrepare, useProfile } from "@/lib/queries";
import type { DraftWithJob, MatchDetail } from "@/lib/types";
import { ago, cn } from "@/lib/utils";

export type ApproveWith = "send" | "gmail" | "mail";
export type DraftEdits = { to_email?: string; subject?: string; email_body?: string; linkedin_note?: string };

interface Props {
  draft: DraftWithJob;
  index: number;
  total: number;
  onMove: (delta: number) => void;
  onApprove: (how: ApproveWith, edits: DraftEdits) => void;
  onReject: () => void;
  busy: boolean;
  smtp: boolean;
  /** Full-screen on phones: a back button, swipe between drafts, and a bottom action bar. */
  onClose?: () => void;
}

const typing = (t: EventTarget | null) => {
  const el = t as HTMLElement | null;
  return !!el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));
};

const WORTH: Record<string, string> = { fit: "Fit (of 40)", verification: "Verified posting (of 25)", not_ghost: "Not a ghost job (of 15)", completeness: "Complete application (of 20)" };

/** Verifier v2 verdict, with its evidence on hover / focus. */
function VerifyBadge({ draft }: { draft: DraftWithJob }) {
  if (!draft.legit_status) return null;
  const tone = draft.legit_status === "verified" ? "success" : draft.legit_status === "caution" ? "warning" : "danger";
  const label = draft.legit_status === "verified" ? "Verified posting" : draft.legit_status === "caution" ? "Suspicious" : "Likely scam";
  const reasons = draft.legit_reasons ?? [];
  return (
    <Tooltip
      side="bottom"
      label={
        <span className="block max-w-72 text-left">
          {reasons.length ? reasons.map((r) => <span key={r} className="block">· {r}</span>) : "Checked by Verifier"}
          {draft.ghost_score != null && <span className="mt-1 block text-text-3">Ghost-job score {draft.ghost_score}/100</span>}
        </span>
      }
    >
      <button type="button" className="rounded-full focus-visible:outline-2" aria-label={`${label}: ${reasons.join("; ")}`}>
        <Badge tone={tone}>
          {draft.legit_status === "verified" ? <ShieldCheck /> : <ShieldAlert />} {label}
        </Badge>
      </button>
    </Tooltip>
  );
}

/** Referrals go to people who know the company: a plain LinkedIn people search, nothing automated. */
function AlumniLink({ company }: { company: string }) {
  const { data: profile } = useProfile();
  const school = profile?.resume.education[0]?.school ?? "";
  const q = encodeURIComponent([company, school].filter(Boolean).join(" "));
  return (
    <a href={`https://www.linkedin.com/search/results/people/?keywords=${q}`} target="_blank" rel="noreferrer" className="font-medium text-cobalt-text hover:underline">
      Find {school ? "alumni" : "people"} at {company}
    </a>
  );
}

function SectionVoice({ agent, name, children, action }: { agent: "outreach" | "matcher"; name: string; children: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="flex min-w-0 items-start gap-3">
        <AgentAvatar agent={agent} size={32} decorative />
        <div className="min-w-0">
          <div className="text-[14px] font-semibold">{name}</div>
          <p className="text-[13px] text-text-2">{children}</p>
        </div>
      </div>
      {action}
    </div>
  );
}

function WhyTab({ match }: { match?: MatchDetail }) {
  if (!match) return <Skeleton agent="matcher" className="min-h-64" />;
  return (
    <div className="space-y-5">
      <SectionVoice agent="matcher" name="Matcher">
        I scored this <span className="num font-medium text-text">{Math.round(match.score)}</span> out of 100 against your resume.
      </SectionVoice>
      <p className="text-[14px] leading-relaxed text-text">{match.explanation}</p>
      <div className="grid gap-5 md:grid-cols-[auto_minmax(0,1fr)] md:items-center">
        <ScoreRing score={match.score} size={72} stroke={6} />
        <div className="space-y-3">
          <ScoreBar label="Semantic similarity" value={match.semantic_score} />
          <ScoreBar label="Skill coverage" value={match.skill_score} />
          <ScoreBar label="LLM recruiter review" value={match.llm_score} hint="offline" />
        </div>
      </div>
      {(match.strengths.length > 0 || match.gaps.length > 0) && (
        <div className="space-y-2">
          <div className="eyebrow">Skills</div>
          <div className="flex flex-wrap gap-1.5">
            {match.strengths.map((s) => (
              <span key={`s-${s}`} className="inline-flex items-center gap-1 rounded-[6px] px-2 py-1 text-[12.5px] font-medium text-done" style={{ background: "color-mix(in oklab, var(--done) 12%, transparent)" }}>
                <Check className="size-3.5" aria-label="You have" /> {s}
              </span>
            ))}
            {match.gaps.map((s) => (
              <span key={`g-${s}`} className="rounded-[6px] border border-dashed border-border-strong px-2 py-1 text-[12.5px] text-text-2">
                <span className="sr-only">Missing: </span>
                {s}
              </span>
            ))}
          </div>
        </div>
      )}
      <div className="space-y-2">
        <div className="eyebrow">Why it passed the gate</div>
        <GateRules m={match} />
      </div>
      <Link href={`/jobs/${match.id}`} className="inline-flex min-h-11 items-center gap-1 text-[13px] font-medium text-cobalt-text hover:underline md:min-h-0">
        Open the full job <ArrowUpRight className="size-3.5" />
      </Link>
    </div>
  );
}

/**
 * One draft, reviewed: Email draft | Tailored resume | Why this match, with sticky actions.
 * Shortcuts while a pending draft is open: J/K move · A approve · E edit · R reject · ⌘↵ approve while editing.
 */
export function Reviewer({ draft, index, total, onMove, onApprove, onReject, busy, smtp, onClose }: Props) {
  const { data: match } = useMatch(draft.match_id);
  const prepare = usePrepare();
  const mobile = !!onClose;
  const pending = draft.status === "pending";
  const approved = draft.status === "approved" || draft.status === "sent";

  const [tab, setTab] = useState("email");
  const [channel, setChannel] = useState<"email" | "linkedin">("email");
  const [editing, setEditing] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [regen, setRegen] = useState(false);
  const [to, setTo] = useState(draft.to_email ?? "");
  const [subject, setSubject] = useState(draft.subject);
  const [body, setBody] = useState(draft.email_body);
  const [note, setNote] = useState(draft.linkedin_note);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setTo(draft.to_email ?? "");
    setSubject(draft.subject);
    setBody(draft.email_body);
    setNote(draft.linkedin_note);
  }, [draft.id, draft.to_email, draft.subject, draft.email_body, draft.linkedin_note]);
  useEffect(() => {
    setEditing(false);
    setTab("email");
    scroller.current?.scrollTo({ top: 0 });
  }, [draft.id]);

  const edits = useCallback(
    (): DraftEdits => ({
      ...(to.trim() !== (draft.to_email ?? "") && { to_email: to.trim() }),
      ...(subject !== draft.subject && { subject }),
      ...(body !== draft.email_body && { email_body: body }),
      ...(note !== draft.linkedin_note && { linkedin_note: note }),
    }),
    [to, subject, body, note, draft],
  );
  const edited = Object.keys(edits()).length > 0;
  const primary: ApproveWith = smtp && to.trim() ? "send" : "gmail";
  const secondary: ApproveWith = primary === "send" ? "gmail" : "mail";
  const approve = useCallback((how: ApproveWith) => onApprove(how, edits()), [onApprove, edits]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (rejecting || regen) return;
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && pending) {
        e.preventDefault();
        approve(primary);
        return;
      }
      if (e.metaKey || e.ctrlKey || e.altKey || typing(e.target)) return;
      const k = e.key.toLowerCase();
      if (k === "j") onMove(1);
      else if (k === "k") onMove(-1);
      else if (!pending) return;
      else if (k === "a") (e.preventDefault(), approve(primary));
      else if (k === "e") (e.preventDefault(), setTab("email"), setEditing((v) => !v));
      else if (k === "r") (e.preventDefault(), setRejecting(true));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [approve, primary, pending, onMove, rejecting, regen]);

  // Phones: swipe left or right on the draft to move through the queue.
  const touch = useRef<{ x: number; y: number } | null>(null);
  const swipe = mobile
    ? {
        onTouchStart: (e: React.TouchEvent) => (touch.current = { x: e.touches[0].clientX, y: e.touches[0].clientY }),
        onTouchEnd: (e: React.TouchEvent) => {
          const s = touch.current;
          touch.current = null;
          if (!s || editing) return;
          const dx = e.changedTouches[0].clientX - s.x;
          const dy = e.changedTouches[0].clientY - s.y;
          if (Math.abs(dx) > 72 && Math.abs(dx) > Math.abs(dy) * 1.6) onMove(dx < 0 ? 1 : -1);
        },
      }
    : {};

  const source = SOURCE_LABEL[draft.job_source] ?? draft.job_source;
  const lines = body.split("\n").filter((l) => l.trim()).length;
  const approveLabel = (how: ApproveWith) => (how === "send" ? "Approve & send" : how === "gmail" ? "Approve & open Gmail" : "Approve & mail app");
  const approveIcon = (how: ApproveWith) => (how === "send" ? <Send /> : how === "gmail" ? <GmailIcon className={primary === how ? "[&_path]:fill-[var(--on-cobalt)]" : undefined} /> : <Mail />);

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Header */}
      {/* Phones: back · counter · arrows on one row, the full title on the next. */}
      <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b border-border px-4 py-2 md:flex-nowrap md:items-start md:px-5 md:py-4">
        {mobile && (
          <button type="button" onClick={onClose} aria-label="Back to the queue" className="-ml-2 grid size-11 shrink-0 place-items-center rounded-[var(--radius-control)] text-text-2 hover:bg-elevated hover:text-text">
            <ArrowLeft className="size-5" />
          </button>
        )}
        <div className={cn("flex min-w-0 items-start gap-3 md:flex-1", mobile && "order-last w-full pb-1 md:order-none md:w-auto md:pb-0")}>
        <ScoreRing score={draft.score} size={mobile ? 40 : 48} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <h2 className="text-[15px] leading-snug font-semibold break-words md:text-[16px]">{draft.title}</h2>
            {draft.kind === "referral" && <Badge tone="accent">Referral request</Badge>}
            {edited && <Badge tone="warning">Edited</Badge>}
            <VerifyBadge draft={draft} />
            {draft.send_worthiness != null && (
              <Tooltip
                side="bottom"
                label={
                  <span className="block text-left">
                    Send-worthiness {draft.send_worthiness}/100
                    {Object.entries(draft.worthiness_parts ?? {}).map(([k, v]) => (
                      <span key={k} className="block text-text-3">
                        {WORTH[k] ?? k}: {v}
                      </span>
                    ))}
                  </span>
                }
              >
                <button type="button" className="rounded-full" aria-label={`Send-worthiness ${draft.send_worthiness} out of 100`}>
                  <Badge tone={draft.send_worthiness >= 70 ? "success" : draft.send_worthiness >= 50 ? "outline" : "warning"}>Worth sending · {draft.send_worthiness}</Badge>
                </button>
              </Tooltip>
            )}
          </div>
          <div className="mt-0.5 flex flex-wrap gap-x-2 text-[13px] text-text-2">
            <span className="font-medium text-text">{draft.company}</span>
            <a href={draft.job_url} target="_blank" rel="noreferrer" className="hover:text-text hover:underline">
              via {source}
            </a>
            {draft.kind === "referral" && <AlumniLink company={draft.company} />}
          </div>
          {(draft.legit_status === "caution" || draft.legit_status === "suspicious") && (
            <div role="alert" className="mt-2 rounded-[var(--radius-control)] border border-[color-mix(in_oklab,var(--error)_35%,transparent)] bg-[color-mix(in_oklab,var(--error)_10%,transparent)] px-3 py-2 text-[12.5px]">
              <div className="flex items-center gap-1.5 font-semibold text-[var(--error)]">
                <ShieldAlert className="size-3.5" /> {draft.legit_status === "suspicious" ? "Likely scam: this can’t be approved" : "Suspicious: check before you approve"}
              </div>
              <ul className="mt-1 space-y-0.5 text-text-2">
                {(draft.legit_reasons ?? []).map((r) => (
                  <li key={r}>· {r}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
        </div>
        <div className="ml-auto flex shrink-0 items-center gap-1">
          <span className="num mr-1 text-[12px] text-text-3">
            {index + 1} of {total}
          </span>
          <Tooltip label={<span className="flex items-center gap-2">Previous <Kbd>K</Kbd></span>} side="bottom">
            <button type="button" onClick={() => onMove(-1)} disabled={index === 0} aria-label="Previous draft" className="grid size-11 place-items-center rounded-[var(--radius-control)] text-text-2 hover:bg-elevated hover:text-text disabled:opacity-40 md:size-8">
              <ChevronUp className="size-4" />
            </button>
          </Tooltip>
          <Tooltip label={<span className="flex items-center gap-2">Next <Kbd>J</Kbd></span>} side="bottom">
            <button type="button" onClick={() => onMove(1)} disabled={index >= total - 1} aria-label="Next draft" className="grid size-11 place-items-center rounded-[var(--radius-control)] text-text-2 hover:bg-elevated hover:text-text disabled:opacity-40 md:size-8">
              <ChevronDown className="size-4" />
            </button>
          </Tooltip>
        </div>
      </div>

      <Tabs value={tab} onValueChange={setTab} className="flex min-h-0 flex-1 flex-col">
        <TabsList className="shrink-0 px-2 md:px-3">
          <TabsTrigger value="email">
            <Mail />
            <span>
              Email<span className="hidden sm:inline"> draft</span>
            </span>
          </TabsTrigger>
          <TabsTrigger value="resume">
            <FileDown /> <span className="sm:hidden">Resume</span><span className="hidden sm:inline">Tailored resume</span>
          </TabsTrigger>
          <TabsTrigger value="why">
            <ShieldCheck />
            <span>
              Why<span className="hidden sm:inline"> this match</span>
            </span>
          </TabsTrigger>
        </TabsList>

        <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto overscroll-contain" {...swipe}>
          <TabsContent value="email" className="space-y-4 p-4 md:p-5">
            <SectionVoice
              agent="outreach"
              name="Outreach"
              action={
                <Segmented
                  value={channel}
                  onChange={setChannel}
                  options={[
                    { value: "email", label: <span className="inline-flex items-center gap-1.5"><Mail className="size-3.5" />Email</span> },
                    { value: "linkedin", label: <span className="inline-flex items-center gap-1.5"><Linkedin className="size-3.5" />LinkedIn note</span> },
                  ]}
                />
              }
            >
              Drafted {ago(draft.created_at)}. Checked against your resume, so it never claims a skill you don’t have.
            </SectionVoice>

            {channel === "email" && (pending || draft.status === "approved") && (
              <RecipientCard matchId={draft.match_id} draftId={draft.id} contactId={draft.contact_id} toEmail={draft.to_email} ccEmail={draft.cc_email} editable />
            )}

            {channel === "email" ? (
              editing ? (
                <div className="space-y-3">
                  <RecipientField value={to} onChange={setTo} found={draft.recruiter_email} />
                  <Input value={subject} onChange={(e) => setSubject(e.target.value)} className="font-medium" aria-label="Subject" />
                  <Textarea value={body} onChange={(e) => setBody(e.target.value)} className="min-h-72 text-[14px] leading-relaxed" aria-label="Email body" />
                  <div className="num flex justify-between text-[12px] text-text-3">
                    <span>{lines} lines · aim for 4–5</span>
                    <span>{body.length} chars</span>
                  </div>
                  <div className="card overflow-hidden">
                    <ResumeAttachment matchId={draft.match_id} onOpen={() => setTab("resume")} />
                  </div>
                </div>
              ) : (
                <article className="card overflow-hidden">
                  <dl className="space-y-1.5 border-b border-border px-4 py-3 text-[13px]">
                    <div className="flex gap-3">
                      <dt className="w-14 shrink-0 text-text-3">To</dt>
                      <dd className="min-w-0 break-all">
                        {to.trim() ? (
                          <span className="num">{to}</span>
                        ) : (
                          <button type="button" disabled={!pending} onClick={() => setEditing(true)} className="font-medium text-your-turn hover:underline disabled:no-underline">
                            No recipient yet. Pick a contact above or add one.
                          </button>
                        )}
                      </dd>
                    </div>
                    {draft.cc_email && (
                      <div className="flex gap-3">
                        <dt className="w-14 shrink-0 text-text-3">Cc</dt>
                        <dd className="num min-w-0 break-all">{draft.cc_email}</dd>
                      </div>
                    )}
                    <div className="flex gap-3">
                      <dt className="w-14 shrink-0 text-text-3">Subject</dt>
                      <dd className="min-w-0 font-medium">{subject}</dd>
                    </div>
                  </dl>
                  <div className="px-4 py-4 text-[14px] leading-relaxed whitespace-pre-wrap text-text">{body}</div>
                  <ResumeAttachment matchId={draft.match_id} onOpen={() => setTab("resume")} />
                </article>
              )
            ) : editing ? (
              <div className="space-y-2">
                <Textarea value={note} onChange={(e) => setNote(e.target.value.slice(0, 300))} className="min-h-40 text-[14px]" aria-label="LinkedIn note" />
                <div className={cn("num text-right text-[12px]", note.length > 280 ? "text-your-turn" : "text-text-3")}>{note.length}/300</div>
              </div>
            ) : (
              <article className="card px-4 py-4 text-[14px] leading-relaxed whitespace-pre-wrap">
                {note || <span className="text-text-3">No LinkedIn note for this draft.</span>}
                <div className="num mt-3 text-right text-[12px] text-text-3">{note.length}/300 · paste it into a connection request yourself</div>
              </article>
            )}
          </TabsContent>

          <TabsContent value="resume" className="p-4 md:p-5">
            <ResumeDiff match={match} matchId={draft.match_id} editable={pending || draft.status === "approved"} />
          </TabsContent>

          <TabsContent value="why" className="p-4 md:p-5">
            <WhyTab match={match} />
          </TabsContent>
        </div>
      </Tabs>

      {/* Sticky actions */}
      {pending ? (
        <div className="shrink-0 border-t border-border bg-surface px-3 py-3 pb-[calc(12px+env(safe-area-inset-bottom))] md:px-4 md:pb-3">
          {/* Phones: three thumb-sized actions, the rest under More. */}
          <div className="flex items-center gap-2 md:hidden">
            <Button variant="danger" size="lg" className="px-3.5" onClick={() => setRejecting(true)} disabled={busy} aria-label="Reject">
              <X />
            </Button>
            <Button size="lg" className="px-3.5" onClick={() => (setTab("email"), setEditing((v) => !v))} aria-pressed={editing} aria-label={editing ? "Done editing" : "Edit"}>
              {editing ? <Check /> : <Pencil />}
            </Button>
            <Popover>
              <PopoverTrigger asChild>
                <Button size="lg" className="px-3.5" aria-label="More actions">
                  <MoreHorizontal />
                </Button>
              </PopoverTrigger>
              <PopoverContent side="top" align="start" label="More actions" className="w-64 p-1.5">
                <button type="button" onClick={() => approve(secondary)} className="flex h-11 w-full items-center gap-2 rounded-[var(--radius-control)] px-3 text-[14px] hover:bg-elevated [&_svg]:size-4">
                  {approveIcon(secondary)} {approveLabel(secondary)}
                </button>
                <button type="button" onClick={() => setRegen(true)} className="flex h-11 w-full items-center gap-2 rounded-[var(--radius-control)] px-3 text-[14px] hover:bg-elevated">
                  <RefreshCw className="size-4" /> Regenerate draft
                </button>
                <a href={`/api/matches/${draft.match_id}/resume?format=pdf`} download className="flex h-11 w-full items-center gap-2 rounded-[var(--radius-control)] px-3 text-[14px] hover:bg-elevated">
                  <FileDown className="size-4" /> Resume PDF
                </a>
              </PopoverContent>
            </Popover>
            <Button variant="primary" size="lg" className="flex-1" onClick={() => approve(primary)} loading={busy}>
              {!busy && approveIcon(primary)} {primary === "send" ? "Approve & send" : "Approve"}
            </Button>
          </div>

          <div className="hidden flex-wrap items-center gap-2 md:flex">
            <Button variant="danger" onClick={() => setRejecting(true)} disabled={busy}>
              <X /> Reject <span className="hidden xl:inline-flex"><Kbd>R</Kbd></span>
            </Button>
            <Button onClick={() => setRegen(true)} disabled={busy || prepare.isPending}>
              <RefreshCw /> Regenerate
            </Button>
            <Button onClick={() => (setTab("email"), setEditing((v) => !v))} aria-pressed={editing}>
              {editing ? <Check /> : <Pencil />} {editing ? "Done" : "Edit"} <span className="hidden xl:inline-flex"><Kbd>E</Kbd></span>
            </Button>
            <div className="ml-auto flex flex-wrap items-center gap-2">
              <Button variant="ghost" onClick={() => approve(secondary)} disabled={busy}>
                {approveIcon(secondary)} {approveLabel(secondary)}
              </Button>
              <Button variant="primary" onClick={() => approve(primary)} loading={busy}>
                {!busy && approveIcon(primary)} {approveLabel(primary)} <span className="hidden xl:inline-flex"><Kbd>A</Kbd></span>
              </Button>
            </div>
          </div>
          {!smtp && (
            <p className="mt-2 hidden text-[12px] text-text-3 md:block">
              <Link href="/settings#mail" className="font-medium text-cobalt-text hover:underline">
                Connect your email
              </Link>{" "}
              to send straight from your mailbox with the tailored resume attached.
            </p>
          )}
        </div>
      ) : approved ? (
        <div className="shrink-0 space-y-2 border-t border-border bg-surface p-3 pb-[calc(12px+env(safe-area-inset-bottom))] md:p-4">
          <div className="flex flex-wrap items-center gap-2">
            {smtp && draft.status === "approved" && to.trim() && (
              <Button size="sm" variant="primary" onClick={() => onApprove("send", { to_email: to.trim() })} loading={busy}>
                <Send /> Send with resume
              </Button>
            )}
            <SendActions mail={{ to, cc: draft.cc_email, subject: draft.subject, body: draft.email_body }} draftId={draft.id} matchId={draft.match_id} jobUrl={draft.job_url} sent={draft.status === "sent"} />
            <a href={`/api/matches/${draft.match_id}/resume?format=pdf`} download className={buttonClass({ size: "sm", variant: "ghost" })}>
              <FileDown /> Resume PDF
            </a>
          </div>
          <p className="text-[12px] text-text-3">
            {draft.status === "sent" ? `Sent ${ago(draft.sent_at)}` : `Approved ${ago(draft.decided_at)}. Nothing leaves JobPilot until you press send in your mail app.`}
          </p>
        </div>
      ) : (
        <div className="shrink-0 border-t border-border px-4 py-3 text-[13px] text-text-2">You rejected this draft {ago(draft.decided_at)}.</div>
      )}

      <Dialog open={rejecting} onOpenChange={setRejecting}>
        <DialogContent title={`Reject the draft for ${draft.company}?`} description="Outreach won’t send it. You can prepare a new one later from the job page.">
          <div className="flex justify-end gap-2">
            <DialogClose asChild>
              <Button>Cancel</Button>
            </DialogClose>
            <Button
              variant="danger"
              autoFocus
              onClick={() => {
                setRejecting(false);
                onReject();
              }}
            >
              <X /> Reject
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={regen} onOpenChange={setRegen}>
        <DialogContent title="Regenerate this draft?" description={`Tailor and Outreach will rewrite the resume and email for ${draft.company}. This uses one run, and edits you haven’t approved are lost.`}>
          <div className="flex justify-end gap-2">
            <DialogClose asChild>
              <Button>Cancel</Button>
            </DialogClose>
            <Button
              variant="primary"
              loading={prepare.isPending}
              onClick={() => prepare.mutate(draft.match_id, { onSettled: () => setRegen(false) })}
            >
              <RefreshCw /> Regenerate
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}


/** The tailored resume this application sends, shown as the email's attachment: its file, its ATS score for the
 * job against your target, and ways to open it. It's the exact file attached when you send. */
function ResumeAttachment({ matchId, onOpen }: { matchId: string; onOpen?: () => void }) {
  const { data } = useQuery({
    queryKey: ["ats-target", matchId],
    queryFn: () => api.get<{ score: number; target: number; ok: boolean; tailored: boolean; filename: string }>(`/matches/${matchId}/ats-target`),
  });
  return (
    <div className="space-y-2.5 border-t border-border bg-surface-2/40 px-4 py-3">
      <div className="flex items-center gap-3">
      <div className="flex size-9 shrink-0 items-center justify-center rounded-[var(--radius-control)] border border-border bg-surface text-[10.5px] font-semibold text-[var(--error)]">PDF</div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5 text-[13px] font-medium">
          <Paperclip className="size-3.5 shrink-0 text-text-3" />
          <span className="break-all">{data?.filename ?? "Tailored resume.pdf"}</span>
        </div>
        <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[12px] text-text-3">
          <span>{data?.tailored ? "Tailored for this job" : "Your resume (not tailored yet)"}</span>
          {data && (
            <>
              <span>·</span>
              <span className="num">ATS {data.score}</span>
              {data.target ? (
                <Badge tone={data.ok ? "success" : "warning"}>{data.ok ? `target ${data.target} reached` : `below target ${data.target}: won't send`}</Badge>
              ) : null}
            </>
          )}
        </div>
      </div>
      </div>
      <div className="flex flex-wrap gap-1.5 pl-12">
        <a href={`/api/matches/${matchId}/resume?format=pdf&inline=true`} target="_blank" rel="noreferrer" className={buttonClass({ size: "sm", variant: "secondary" })}>
          <Eye /> View
        </a>
        <a href={`/api/matches/${matchId}/resume?format=pdf`} download className={buttonClass({ size: "sm", variant: "ghost" })}>
          <FileDown /> PDF
        </a>
        <a href={`/api/matches/${matchId}/resume?format=docx`} download className={buttonClass({ size: "sm", variant: "ghost" })}>
          <FileDown /> Word
        </a>
        {onOpen && (
          <Button size="sm" variant="ghost" onClick={onOpen}>
            What changed
          </Button>
        )}
      </div>
    </div>
  );
}

"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, FileText, Mail, Send, ShieldAlert, Sparkles } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { GmailIcon } from "@/components/send-actions";
import { Badge } from "@/components/ui/badge";
import { Button, buttonClass } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/input";
import { ScoreRing } from "@/components/ui/score-ring";
import { api } from "@/lib/api";
import type { AtsCompare } from "@/lib/ats-types";
import { gmailUrl, reserveTab, sendTo } from "@/lib/compose";
import { useApply, useMailAccount, usePrepare, useSendApplication } from "@/lib/queries";
import type { MatchDetail } from "@/lib/types";

/**
 * Apply = one confirmation that sends the tailored resume (PDF attached) and the drafted email to the company's
 * recruiter or HR contact, from the student's own Gmail. Nothing goes out until they press Send: this click is
 * the per-application approval. Company application forms have no public submit API, so the dialog can also
 * open that page alongside.
 */
export function ApplyDialog({ m, open, onOpenChange }: { m: MatchDetail; open: boolean; onOpenChange: (v: boolean) => void }) {
  const { job } = m;
  const draft = [...m.drafts].reverse().find((d) => d.kind !== "referral");
  const { data: mail } = useMailAccount();
  const { data: cmp } = useQuery({ queryKey: ["ats-compare", m.id], queryFn: () => api.get<AtsCompare>(`/matches/${m.id}/ats-compare`), enabled: open, retry: false });
  const send = useSendApplication();
  const prepare = usePrepare();
  const markApplied = useApply();
  const [to, setTo] = useState("");
  const [alsoForm, setAlsoForm] = useState(true);
  useEffect(() => setTo(draft?.to_email || job.recruiter_email || ""), [draft?.id, draft?.to_email, job.recruiter_email]);

  const scam = job.legit_status === "suspicious";
  const validTo = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(to.trim());
  const sent = draft?.status === "sent";
  const submit = () => {
    if (!draft) return;
    const tab = alsoForm && job.url ? reserveTab() : null;
    send.mutate(
      { id: draft.id, to_email: to.trim() },
      {
        onSuccess: () => {
          if (tab) sendTo(tab, job.url);
          onOpenChange(false);
        },
        onError: () => tab?.close(),
      },
    );
  };
  const formOnly = () => {
    const tab = reserveTab();
    markApplied.mutate(m.id, { onSuccess: () => sendTo(tab, job.url), onError: () => tab?.close() });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={`Apply to ${job.company}`} description={job.title} className="max-w-[560px]">
        {scam ? (
          <p className="flex gap-2 text-[13.5px] text-[var(--error)]">
            <ShieldAlert className="size-4 shrink-0" /> This posting was flagged as a likely scam. JobPilot won't send anything to it.
          </p>
        ) : sent ? (
          <div className="space-y-3 text-[13.5px]">
            <p>
              Your tailored resume was already sent to <span className="font-medium">{draft?.to_email}</span>.
            </p>
            {job.url && (
              <Button onClick={formOnly} loading={markApplied.isPending}>
                Open the application page <ArrowUpRight />
              </Button>
            )}
          </div>
        ) : !draft ? (
          <div className="space-y-3 text-[13.5px] text-text-2">
            <p>To apply by email, JobPilot first tailors your resume to this job and drafts a short email to the recruiter. It takes a few seconds, and you review both before anything is sent.</p>
            <div className="flex flex-wrap gap-2">
              <Button variant="primary" onClick={() => prepare.mutate(m.id)} loading={prepare.isPending}>
                <Sparkles /> Tailor resume & draft email
              </Button>
              {job.url && (
                <Button onClick={formOnly} loading={markApplied.isPending}>
                  Apply on company site only <ArrowUpRight />
                </Button>
              )}
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="flex items-center gap-3 rounded-[var(--radius-card)] border border-border bg-elevated p-3">
              <FileText className="size-5 shrink-0 text-cobalt-text" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-[13.5px] font-medium">Tailored resume (PDF) attached</div>
                <a href={`/api/matches/${m.id}/resume?format=pdf`} className="text-[12.5px] text-cobalt-text hover:underline">
                  Preview the exact file
                </a>
              </div>
              {cmp && (
                <div className="flex items-center gap-2" title={`ATS score for this job: uploaded ${cmp.original.score} → tailored ${cmp.tailored.score}`}>
                  <ScoreRing score={cmp.tailored.score} size={40} stroke={4} />
                  {cmp.delta !== 0 && (
                    <Badge tone={cmp.delta > 0 ? "success" : "danger"} className="num">
                      {cmp.delta > 0 ? "+" : ""}
                      {cmp.delta}
                    </Badge>
                  )}
                </div>
              )}
            </div>
            <Field label="To (recruiter or HR)" hint={job.recruiter_email && to !== job.recruiter_email ? `Found on the posting: ${job.recruiter_email}` : "Only public business contacts. Check it's right."}>
              <Input type="email" value={to} onChange={(e) => setTo(e.target.value)} placeholder="hr@company.com" />
            </Field>
            <div className="rounded-[var(--radius-card)] border border-border p-3">
              <div className="text-[13.5px] font-semibold">{draft.subject}</div>
              <p className="mt-1.5 line-clamp-6 text-[13px] whitespace-pre-line text-text-2">{draft.email_body}</p>
              <Link href={`/approvals?draft=${draft.id}`} className="mt-2 inline-block text-[12.5px] text-cobalt-text hover:underline">
                Edit the email first
              </Link>
            </div>
            {job.url && (
              <label className="flex items-center gap-2 text-[13px] text-text-2">
                <input type="checkbox" checked={alsoForm} onChange={(e) => setAlsoForm(e.target.checked)} className="size-4 accent-[var(--cobalt)]" />
                Also open the company's application page (some companies only accept applications there)
              </label>
            )}
            {mail?.connected ? (
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="primary" onClick={submit} loading={send.isPending} disabled={!validTo}>
                  <Send /> Send application
                </Button>
                <span className="text-[12px] text-text-3">From {mail.from_email}. Counts toward today's send limit.</span>
              </div>
            ) : (
              <div className="space-y-2">
                <p className="text-[13px] text-text-2">
                  Connect your Gmail to send in one click, with the resume attached, from your own address.{" "}
                  <Link href="/settings#mail" className="text-cobalt-text hover:underline">
                    Connect in Settings
                  </Link>
                </p>
                <div className="flex flex-wrap gap-2">
                  <a href={`/api/matches/${m.id}/resume?format=pdf`} className={buttonClass({ size: "sm" })}>
                    <FileText /> Download resume
                  </a>
                  <Button size="sm" onClick={() => sendTo(reserveTab(), gmailUrl({ to, cc: draft.cc_email, subject: draft.subject, body: draft.email_body }))}>
                    <GmailIcon /> Open in Gmail
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => (window.location.href = `mailto:${to}`)}>
                    <Mail /> Mail app
                  </Button>
                </div>
              </div>
            )}
            <p className="text-[12px] text-text-3">Nothing is sent until you press Send. One follow-up at most, after 7 days, and only if you approve it.</p>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

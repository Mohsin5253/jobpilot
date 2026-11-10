"use client";

import { ArrowUpRight, AtSign, Check, Mail } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { gmailUrl, mailtoUrl, reserveTab, sendTo, type Mail as MailContent } from "@/lib/compose";
import { useApply, useMarkSent } from "@/lib/queries";
import { cn } from "@/lib/utils";

export function GmailIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={cn("size-4", className)} aria-hidden>
      <path fill="#EA4335" d="M5 19V9.3L12 14l7-4.7V19h1.5c.8 0 1.5-.7 1.5-1.5V6.8L12 13.3 2 6.8v10.7c0 .8.7 1.5 1.5 1.5z" />
      <path fill="#FBBC04" d="M22 6.5v.3l-10 6.5-10-6.5v-.3C2 5.1 3.6 4.3 4.7 5.1L12 10l7.3-4.9c1.1-.8 2.7 0 2.7 1.4z" />
    </svg>
  );
}

/** Recipient field. Pre-filled when the posting lists a recruiter email; otherwise the user adds one. */
export function RecipientField({ value, onChange, onCommit, found, disabled }: { value: string; onChange: (v: string) => void; onCommit?: () => void; found?: string | null; disabled?: boolean }) {
  return (
    <div className="space-y-1">
      <div className="relative">
        <AtSign className="pointer-events-none absolute top-1/2 left-3 size-3.5 -translate-y-1/2 text-subtle" />
        <Input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onBlur={onCommit}
          disabled={disabled}
          type="email"
          placeholder="Recruiter or hiring email (to)"
          aria-label="Recipient email"
          className="pl-8 font-mono text-[13px]"
        />
      </div>
      <p className="text-[11.5px] text-subtle">
        Sending to this address. Pick a contact above, or type any address you trust{found ? ` (the posting lists ${found})` : ""}.
      </p>
    </div>
  );
}

/** Open the drafted email in Gmail or the default mail app, apply on the company site, mark sent. */
export function SendActions({
  mail,
  draftId,
  matchId,
  jobUrl,
  bullets,
  sent,
  size = "sm",
}: {
  mail: MailContent;
  draftId?: string;
  matchId: string;
  jobUrl: string;
  bullets?: string[];
  sent?: boolean;
  size?: "sm" | "md";
}) {
  const apply = useApply();
  const markSent = useMarkSent();

  const openApply = () => {
    const tab = reserveTab();
    if (bullets?.length) navigator.clipboard?.writeText(bullets.map((b) => `• ${b}`).join("\n")).catch(() => {});
    apply.mutate(matchId, {
      onSuccess: () => {
        sendTo(tab, jobUrl);
        if (bullets?.length) toast.message("Tailored bullets copied", { description: "Paste them into the application form." });
      },
      onError: () => tab?.close(),
    });
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button size={size} variant="primary" onClick={() => sendTo(reserveTab(), gmailUrl(mail))} title={mail.to ? `To ${mail.to}` : "Opens Gmail with an empty To field"}>
        <GmailIcon className="[&_path]:fill-[var(--on-accent)]" /> Open in Gmail
      </Button>
      <Button size={size} onClick={() => (window.location.href = mailtoUrl(mail))}>
        <Mail className="size-3.5" /> Mail app
      </Button>
      {jobUrl && (
        <Button size={size} onClick={openApply} loading={apply.isPending}>
          Apply on site <ArrowUpRight className="size-3.5" />
        </Button>
      )}
      {draftId && !sent && (
        <Button size={size} variant="success" onClick={() => markSent.mutate(draftId)}>
          <Check className="size-3.5" /> I sent it
        </Button>
      )}
    </div>
  );
}

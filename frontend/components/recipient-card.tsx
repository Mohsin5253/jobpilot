"use client";

import { BadgeCheck, ChevronDown, ExternalLink, Globe, Linkedin, Loader2, Search, ShieldQuestion, UserRound } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useContacts, useEditDraft, useFindContacts } from "@/lib/queries";
import type { Contact } from "@/lib/types";
import { cn } from "@/lib/utils";

const SOURCE_LABEL: Record<Contact["source"], string> = {
  posting: "Listed in the job posting",
  website: "On the company's website",
  hunter: "Found on public web pages (Hunter.io)",
};

function displayName(c: Contact) {
  return c.kind === "person" && c.first_name ? `${c.first_name} ${c.last_name}`.trim() : c.email.split("@")[0].replace(/[._-]/g, " ");
}

function Verification({ status, source }: { status: string; source: Contact["source"] }) {
  if (source !== "hunter" && !status)
    return (
      <Badge tone="success">
        <BadgeCheck className="size-3" /> Published by company
      </Badge>
    );
  if (status === "valid")
    return (
      <Badge tone="success">
        <BadgeCheck className="size-3" /> Verified
      </Badge>
    );
  if (status === "accept_all") return <Badge tone="warning">Domain accepts all</Badge>;
  return (
    <Badge tone="outline">
      <ShieldQuestion className="size-3" /> Not verified
    </Badge>
  );
}

function ContactLine({ c, selected, onPick, disabled }: { c: Contact; selected: boolean; onPick?: () => void; disabled?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={cn("rounded-[var(--radius-card)] border p-3 transition-colors", selected ? "border-accent/40 bg-accent-soft/60" : "border-border bg-surface-2/40")}>
      <div className="flex items-start gap-3">
        <div
          className={cn(
            "grid size-9 shrink-0 place-items-center rounded-full text-[13px] font-semibold",
            c.kind === "person" ? "foil text-on-accent" : "bg-surface-3 text-muted",
          )}
        >
          {c.kind === "person" ? (c.first_name[0] ?? "?") + (c.last_name[0] ?? "") : <Globe className="size-4" />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[13.5px] font-semibold capitalize">{displayName(c)}</span>
            {c.seniority && <Badge tone="accent" className="capitalize">{c.seniority}</Badge>}
            <Verification status={c.verification} source={c.source} />
          </div>
          {c.position && <div className="text-[12.5px] text-muted">{c.position}</div>}
          <div className="font-mono text-[12px] text-fg/80">{c.email}</div>
          <button type="button" onClick={() => setOpen((v) => !v)} className="mt-1 inline-flex items-center gap-1 text-[11.5px] text-subtle hover:text-fg">
            {SOURCE_LABEL[c.source]} · {c.sources.length} source{c.sources.length === 1 ? "" : "s"}
            <ChevronDown className={cn("size-3 transition-transform", open && "rotate-180")} />
          </button>
          {open && (
            <ul className="mt-1 space-y-0.5">
              {c.sources.map((s) => (
                <li key={s.uri}>
                  <a href={s.uri} target="_blank" rel="noreferrer" className="inline-flex max-w-full items-center gap-1 truncate text-[11.5px] text-accent hover:underline">
                    <ExternalLink className="size-3 shrink-0" />
                    <span className="truncate">{s.uri}</span>
                    {s.last_seen_on && <span className="shrink-0 text-subtle">· seen {s.last_seen_on}</span>}
                  </a>
                </li>
              ))}
              {c.linkedin && (
                <li>
                  <a href={c.linkedin} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-[11.5px] text-accent hover:underline">
                    <Linkedin className="size-3" /> LinkedIn profile
                  </a>
                </li>
              )}
            </ul>
          )}
        </div>
        {onPick && !selected && (
          <Button size="sm" onClick={onPick} disabled={disabled}>
            Use
          </Button>
        )}
      </div>
    </div>
  );
}

/** Who the email goes to: the chosen real contact, where it was found, and the alternatives. */
export function RecipientCard({
  matchId,
  draftId,
  contactId,
  toEmail,
  ccEmail,
  editable,
}: {
  matchId: string;
  draftId: string;
  contactId: string | null;
  toEmail: string | null;
  ccEmail?: string | null;
  editable: boolean;
}) {
  const { data } = useContacts(matchId);
  const find = useFindContacts(matchId);
  const edit = useEditDraft();
  const [showAll, setShowAll] = useState(false);
  const contacts = data?.contacts ?? [];
  const selected = contacts.find((c) => c.id === contactId) ?? contacts.find((c) => c.email === toEmail) ?? null;
  const others = contacts.filter((c) => c.id !== selected?.id);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-[12px] font-medium tracking-wide text-subtle uppercase">
          <UserRound className="size-3.5" /> Recipient {data?.domain && <span className="normal-case tracking-normal">· {data.domain}</span>}
        </div>
        <button
          type="button"
          onClick={() => find.mutate(contacts.length > 0)}
          disabled={find.isPending}
          className="inline-flex items-center gap-1 text-[12px] text-accent hover:underline disabled:opacity-50"
        >
          {find.isPending ? <Loader2 className="size-3 animate-spin" /> : <Search className="size-3" />}
          {contacts.length ? "Refresh contacts" : "Find contacts"}
        </button>
      </div>

      {selected ? (
        <ContactLine c={selected} selected />
      ) : (
        <div className="rounded-[var(--radius-card)] border border-dashed border-border-strong px-3 py-2.5 text-[12.5px] text-muted">
          {toEmail ? `Sending to ${toEmail} (typed by you).` : "No public contact found yet — search, or type the recruiter's email below."}
        </div>
      )}

      {ccEmail && (
        <div className="flex items-center gap-2 rounded-lg border border-border bg-surface-2/50 px-3 py-1.5 text-[12.5px]">
          <span className="font-medium text-muted">CC</span>
          <span className="font-mono text-[12px]">{ccEmail}</span>
          <span className="text-subtle">· the company&apos;s published hiring address</span>
          {editable && (
            <button type="button" onClick={() => edit.mutate({ id: draftId, cc_email: "" })} className="ml-auto text-subtle hover:text-danger" aria-label="Remove CC">
              ×
            </button>
          )}
        </div>
      )}

      {!!others.length && (
        <div>
          <button type="button" onClick={() => setShowAll((v) => !v)} className="inline-flex items-center gap-1 text-[12.5px] text-muted hover:text-fg">
            {showAll ? "Hide" : "Show"} {others.length} other real contact{others.length === 1 ? "" : "s"} at this company
            <ChevronDown className={cn("size-3.5 transition-transform", showAll && "rotate-180")} />
          </button>
          {showAll && (
            <div className="mt-2 space-y-2">
              {others.map((c) => (
                <ContactLine key={c.id} c={c} selected={false} disabled={!editable || edit.isPending} onPick={editable ? () => edit.mutate({ id: draftId, contact_id: c.id }) : undefined} />
              ))}
            </div>
          )}
        </div>
      )}

      {data && !data.hunter_enabled && (
        <p className="text-[11.5px] leading-4 text-subtle">
          To find senior people (e.g. the ML lead) add a free Hunter.io key: run <code className="font-mono">backend/scripts/set_hunter.py</code>. Only addresses found on public pages are ever used.
        </p>
      )}
    </div>
  );
}

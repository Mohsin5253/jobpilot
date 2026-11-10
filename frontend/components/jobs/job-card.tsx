"use client";

import { Check, Globe2, MapPin, ShieldAlert, ShieldCheck, ShieldX, Sparkles, X } from "lucide-react";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { STAGE_META } from "@/components/match-row";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ScoreRing } from "@/components/ui/score-ring";
import { useJustArrived } from "@/lib/live";
import { usePrepare, useUpdateMatch } from "@/lib/queries";
import type { Match } from "@/lib/types";
import { ago, cn, salary } from "@/lib/utils";

const NEW_FOR_MS = 24 * 3600_000;

/** A company initial in a tinted squircle (no logos: we don't have rights to companies' marks). */
function Initial({ name }: { name: string }) {
  const hue = [...name].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);
  return (
    <span
      aria-hidden
      className="grid size-10 shrink-0 place-items-center rounded-[var(--radius-avatar)] text-[15px] font-semibold [corner-shape:squircle]"
      style={{ background: `oklch(0.42 0.06 ${hue} / 0.28)`, color: `oklch(0.82 0.08 ${hue})` }}
    >
      {name.trim()[0]?.toUpperCase() ?? "?"}
    </span>
  );
}

/** "Why 82?": Matcher's explanation in a popover; a tap target on phones, never hover-only. */
function WhyScore({ m }: { m: Match }) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button type="button" className="relative z-10 inline-flex min-h-9 shrink-0 items-center gap-1.5 rounded-full pr-2 pl-0.5 text-[12.5px] font-medium whitespace-nowrap text-text-2 hover:bg-elevated hover:text-text md:min-h-7">
          <AgentAvatar agent="matcher" size={24} decorative />
          Why {Math.round(m.score)}?
        </button>
      </PopoverTrigger>
      <PopoverContent side="top" align="start" label={`Why ${Math.round(m.score)}`} className="w-[min(340px,calc(100vw-24px))] p-4">
        <div className="mb-2 flex items-center gap-2">
          <AgentAvatar agent="matcher" size={32} decorative />
          <span className="text-[14px] font-semibold">Matcher</span>
        </div>
        <p className="text-[13.5px] leading-relaxed text-text-2">{m.explanation}</p>
      </PopoverContent>
    </Popover>
  );
}

/**
 * One match: initial, role, company, place, stipend, posted time, score ring, status tags,
 * matched (✓) and missing (outlined) skills, and Open · Tailor · Skip.
 * The title is a stretched button, so the whole card opens the job; the actions sit above it.
 */
export function JobCard({ m, onOpen, layout = "list" }: { m: Match; onOpen: () => void; layout?: "list" | "grid" }) {
  const prepare = usePrepare();
  const update = useUpdateMatch();
  const arrived = useJustArrived().has(m.id);
  const fresh = arrived || Date.now() - new Date(m.created_at).getTime() < NEW_FOR_MS;
  const pay = salary(m.job.salary_min, m.job.salary_max);
  const grid = layout === "grid";
  const skipped = m.stage === "archived" || m.stage === "rejected";

  return (
    <article
      className={cn(
        "card group relative flex gap-4 p-4 transition-colors duration-[var(--dur-fast)] hover:border-border-strong",
        grid ? "h-full flex-col" : "flex-col md:flex-row md:items-start",
        arrived && "animate-arrive",
        skipped && "opacity-70",
      )}
    >
      <div className="flex min-w-0 flex-1 gap-3.5">
        <Initial name={m.job.company} />
        <div className="min-w-0 flex-1">
          <h3 className="text-[15px] leading-snug font-semibold">
            <button type="button" onClick={onOpen} className="text-left after:absolute after:inset-0 after:rounded-[var(--radius-card)] after:content-[''] hover:text-cobalt-text">
              {m.job.title}
            </button>
          </h3>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[13px] text-text-2">
            <span className="font-medium text-text">{m.job.company}</span>
            <span className="inline-flex items-center gap-1">
              {m.job.remote ? <Globe2 className="size-3.5" /> : <MapPin className="size-3.5" />}
              {m.job.remote ? "Remote" : m.job.location || "Location not listed"}
            </span>
            {pay && <span className="num">₹{pay}</span>}
            <span className="text-text-3">{ago(m.job.posted_at ?? m.created_at)}</span>
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {fresh && <Badge tone="accent">New</Badge>}
            {m.stage !== "found" && <Badge tone={STAGE_META[m.stage].tone}>{STAGE_META[m.stage].label}</Badge>}
            {m.pending_draft && <Badge tone="warning">Draft ready</Badge>}
            {m.job.track === "non_technical" && <Badge tone="outline">Non-tech</Badge>}
            {m.job.legit_status === "verified" && (
              <Badge tone="success" title={m.job.legit_reasons.join(" · ")}>
                <ShieldCheck /> Verified
              </Badge>
            )}
            {m.job.legit_status === "caution" && (
              <Badge tone="warning" title={m.job.legit_reasons.join(" · ")}>
                <ShieldAlert /> Check this job
              </Badge>
            )}
            {m.job.legit_status === "suspicious" && (
              <Badge tone="danger" title={m.job.legit_reasons.join(" · ")}>
                <ShieldX /> Suspicious
              </Badge>
            )}
            {m.job.ghost_risk === "high" && <Badge tone="danger">Likely ghost job</Badge>}
          </div>
          <ul className="mt-3 flex flex-wrap gap-1.5" aria-label="Skills">
            {m.strengths.slice(0, grid ? 3 : 4).map((s) => (
              <li key={`s-${s}`} title={s} className="inline-flex max-w-[26ch] items-center gap-1 rounded-[6px] px-1.5 py-0.5 text-[12px] font-medium text-done" style={{ background: "color-mix(in oklab, var(--done) 12%, transparent)" }}>
                <Check className="size-3 shrink-0" aria-label="You have" />
                <span className="truncate">{s}</span>
              </li>
            ))}
            {m.gaps.slice(0, 2).map((s) => (
              <li key={`g-${s}`} title={s} className="max-w-[26ch] truncate rounded-[6px] border border-dashed border-border-strong px-1.5 py-0.5 text-[12px] text-text-2">
                <span className="sr-only">Missing: </span>
                {s}
              </li>
            ))}
          </ul>
        </div>
        {grid ? null : <ScoreRing score={m.score} size={52} className="md:hidden" />}
        {grid && <ScoreRing score={m.score} size={48} />}
      </div>

      <div className={cn("flex items-center gap-2", grid ? "mt-auto flex-wrap" : "flex-wrap md:shrink-0 md:flex-col md:items-end")}>
        {!grid && <ScoreRing score={m.score} size={52} className="hidden md:block" />}
        <div className={cn("flex w-full items-center gap-1.5", !grid && "md:w-auto md:justify-end")}>
          <WhyScore m={m} />
          <span className="ml-auto flex shrink-0 items-center gap-1.5">
            <Button
              size="sm"
              className="relative z-10 h-9 md:h-8"
              onClick={() => prepare.mutate(m.id)}
              loading={prepare.isPending}
              disabled={m.has_tailored}
              title={m.has_tailored ? "Already tailored" : "Tailor the resume and draft outreach for this job"}
            >
              {m.has_tailored ? <Check /> : <Sparkles />} {m.has_tailored ? "Tailored" : "Tailor"}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="relative z-10 h-9 md:h-8"
              onClick={() => update.mutate({ id: m.id, stage: skipped ? "found" : "archived" })}
              aria-label={skipped ? `Restore ${m.job.title}` : `Skip ${m.job.title}`}
            >
              <X /> {skipped ? "Restore" : "Skip"}
            </Button>
          </span>
        </div>
      </div>
    </article>
  );
}

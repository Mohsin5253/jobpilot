"use client";

import { BadgeCheck, Globe2, MapPin } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { ScoreRing } from "@/components/ui/score-ring";
import type { Match, Stage } from "@/lib/types";
import { SOURCE_LABEL } from "@/lib/compose";
import { ago, cn } from "@/lib/utils";
import { useJustArrived } from "@/lib/live";

export const STAGE_META: Record<Stage, { label: string; tone: "neutral" | "accent" | "success" | "warning" | "danger" | "outline" }> = {
  found: { label: "Found", tone: "neutral" },
  shortlisted: { label: "Shortlisted", tone: "accent" },
  applied: { label: "Applied", tone: "warning" },
  interview: { label: "Interview", tone: "success" },
  offer: { label: "Offer", tone: "success" },
  rejected: { label: "Rejected", tone: "danger" },
  archived: { label: "Archived", tone: "outline" },
};

export function SkillChips({ strengths, gaps, max = 4 }: { strengths: string[]; gaps: string[]; max?: number }) {
  return (
    <div className="flex flex-wrap gap-1">
      {strengths.slice(0, max).map((s) => (
        <span key={`s-${s}`} className="rounded-md bg-success/10 px-1.5 py-0.5 text-[11.5px] font-medium text-success">
          {s}
        </span>
      ))}
      {gaps.slice(0, Math.max(1, max - 2)).map((s) => (
        <span key={`g-${s}`} className="rounded-md border border-dashed border-border-strong px-1.5 py-0.5 text-[11.5px] text-subtle">
          {s}
        </span>
      ))}
    </div>
  );
}

const NEW_FOR_MS = 24 * 3600_000;

export function MatchRow({ m, className }: { m: Match; className?: string }) {
  const meta = STAGE_META[m.stage];
  const arrived = useJustArrived().has(m.id);
  const fresh = arrived || Date.now() - new Date(m.created_at).getTime() < NEW_FOR_MS;
  return (
    <Link
      href={`/jobs/${m.id}`}
      className={cn(
        "group flex items-center gap-4 rounded-[var(--radius-card)] px-3 py-3 transition-colors hover:bg-surface-2/70",
        arrived && "animate-arrive bg-accent-soft/60",
        className,
      )}
    >
      <ScoreRing score={m.score} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="truncate text-[14px] font-semibold group-hover:text-accent">{m.job.title}</span>
          {fresh && <Badge tone="accent">New</Badge>}
          {m.stage !== "found" && <Badge tone={meta.tone}>{meta.label}</Badge>}
          {m.pending_draft && <Badge tone="warning">Draft ready</Badge>}
          {m.job.track === "non_technical" && <Badge tone="outline">Non-tech</Badge>}
        </div>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[12.5px] text-muted">
          <span className="font-medium text-fg/80">{m.job.company}</span>
          <span className="inline-flex items-center gap-1">
            {m.job.remote ? <Globe2 className="size-3" /> : <MapPin className="size-3" />}
            {m.job.remote ? "Remote" : m.job.location || "—"}
          </span>
          <span className="text-subtle">{ago(m.job.posted_at ?? m.created_at)}</span>
          <span className="inline-flex items-center gap-1 text-subtle">
            via {m.job.publisher ?? SOURCE_LABEL[m.job.source] ?? m.job.source}
            {m.job.apply_links.length > 1 && <span>+{m.job.apply_links.length - 1}</span>}
            {m.job.link_status === "ok" && <BadgeCheck className="size-3 text-success" aria-label="Apply link checked" />}
          </span>
        </div>
      </div>
      <div className="hidden max-w-[320px] md:block">
        <SkillChips strengths={m.strengths} gaps={m.gaps} />
      </div>
    </Link>
  );
}

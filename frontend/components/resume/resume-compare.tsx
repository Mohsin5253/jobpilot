"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, FileDiff, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { WordDiff } from "@/components/resume/word-diff";
import { Badge } from "@/components/ui/badge";
import { buttonClass } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Segmented, Skeleton } from "@/components/ui/misc";
import { ScoreRing } from "@/components/ui/score-ring";
import { api } from "@/lib/api";
import type { AtsCompare } from "@/lib/ats-types";

/** Uploaded resume vs the one tailored for this job: both ATS-scored against this job, and every change shown. */
export function ResumeCompare({ matchId }: { matchId: string }) {
  const { data, isLoading, error } = useQuery({ queryKey: ["ats-compare", matchId], queryFn: () => api.get<AtsCompare>(`/matches/${matchId}/ats-compare`), retry: false });
  const [view, setView] = useState<"changes" | "side">("changes");
  if (isLoading) return <Skeleton agent="tailor" className="min-h-48" />;
  if (error || !data) return null;
  const { original: a, tailored: b } = data;
  const changed = data.bullets.filter((x) => x.changed);
  const kept = data.bullets.filter((x) => x.reverted);
  return (
    <Card>
      <CardHeader
        icon={<FileDiff className="size-4" />}
        title="Your resume vs the tailored resume"
        description={`Both scored against this job with ${data.industry_name.toLowerCase()} ATS rules.`}
        action={
          <Link href={`/resume?match=${matchId}`} className={buttonClass({ size: "sm", variant: "ghost" })}>
            Full ATS report <ArrowRight />
          </Link>
        }
      />
      <div className="space-y-5 p-5 pt-3">
        <div className="flex flex-wrap items-center gap-4 sm:gap-6">
          <div className="flex items-center gap-3">
            <ScoreRing score={a.score} size={64} stroke={5} />
            <div>
              <div className="text-[12px] text-text-3">Uploaded</div>
              <div className="text-[14px] font-medium">{a.grade}</div>
            </div>
          </div>
          <ArrowRight className="size-4 text-text-3" />
          <div className="flex items-center gap-3">
            <ScoreRing score={b.score} size={64} stroke={5} />
            <div>
              <div className="text-[12px] text-text-3">Tailored for this job</div>
              <div className="text-[14px] font-medium">{b.grade}</div>
            </div>
          </div>
          <Badge tone={data.delta > 0 ? "success" : data.delta < 0 ? "danger" : "neutral"} className="num text-[13px]">
            {data.delta > 0 ? "+" : ""}
            {data.delta} points
          </Badge>
        </div>
        {!data.tailored_ready && <p className="text-[13px] text-text-2">The Tailor hasn't rewritten bullets for this job yet, so only the skill order differs. Use "Prepare" on this page to tailor it.</p>}

        <div className="grid gap-3 sm:grid-cols-3">
          <KeywordList title="Now matched" items={data.keywords_gained} tone="success" empty="No new keywords: the Tailor only rephrases what you wrote." />
          <KeywordList title="Now shown in a bullet" items={data.keywords_now_in_context} tone="accent" empty="—" />
          <KeywordList title="Still missing" items={data.keywords_still_missing} tone="outline" empty="Nothing missing." />
        </div>

        <div>
          <div className="mb-2 text-[12.5px] font-medium text-text-2">Skills order</div>
          <div className="flex flex-wrap gap-1.5">
            {data.skills.tailored_first.map((s) => (
              <Badge key={s} tone="accent">
                {s}
              </Badge>
            ))}
            {data.skills.tailored_rest.map((s) => (
              <Badge key={s} tone="outline">
                {s}
              </Badge>
            ))}
          </div>
          <p className="mt-1.5 text-[12px] text-text-3">Skills this job asks for move to the front (highlighted). Sections: {data.sections.tailored.join(" → ")}.</p>
        </div>

        {!!data.bullets.length && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="text-[12.5px] font-medium text-text-2">
                {changed.length} bullet{changed.length === 1 ? "" : "s"} rewritten{kept.length ? ` · ${kept.length} kept as written by the no-fabrication guard` : ""}
              </div>
              <Segmented value={view} onChange={setView} options={[{ value: "changes", label: "Changes" }, { value: "side", label: "Side by side" }]} />
            </div>
            <ul className="space-y-2">
              {data.bullets.map((x) => (
                <li key={x.source_id} className="rounded-[var(--radius-card)] border border-border p-3">
                  {x.changed ? (
                    view === "changes" ? (
                      <div className="space-y-1.5 text-[13.5px] leading-relaxed">
                        <div className="text-text-2">
                          <WordDiff original={x.original} rewritten={x.rewritten} mode="before" />
                        </div>
                        <div>
                          <WordDiff original={x.original} rewritten={x.rewritten} mode="after" />
                        </div>
                      </div>
                    ) : (
                      <div className="grid gap-3 text-[13.5px] leading-relaxed sm:grid-cols-2">
                        <div>
                          <div className="mb-1 text-[11.5px] text-text-3 uppercase">Uploaded</div>
                          {x.original}
                        </div>
                        <div>
                          <div className="mb-1 text-[11.5px] text-text-3 uppercase">Tailored</div>
                          {x.rewritten}
                        </div>
                      </div>
                    )
                  ) : (
                    <p className="text-[13.5px] text-text-2">{x.original}</p>
                  )}
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    {x.reverted && (
                      <Badge tone="warning" title={x.revert_reason}>
                        <ShieldCheck /> Kept original: {x.revert_reason || "rewrite added something not in your resume"}
                      </Badge>
                    )}
                    {x.keywords.map((k) => (
                      <Badge key={k} tone="accent">
                        {k}
                      </Badge>
                    ))}
                    {!!x.sources.length && <span className="text-[11.5px] text-text-3">Source: {x.sources.join(", ")}</span>}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Card>
  );
}

function KeywordList({ title, items, tone, empty }: { title: string; items: string[]; tone: "success" | "accent" | "outline"; empty: string }) {
  return (
    <div className="rounded-[var(--radius-card)] border border-border p-3">
      <div className="mb-2 text-[12px] font-medium text-text-2">{title}</div>
      <div className="flex flex-wrap gap-1.5">
        {items.length ? (
          items.map((k) => (
            <Badge key={k} tone={tone}>
              {k}
            </Badge>
          ))
        ) : (
          <span className="text-[12.5px] text-text-3">{empty}</span>
        )}
      </div>
    </div>
  );
}

"use client";

import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, CircleAlert, Code2, Lightbulb, Target, TrendingUp } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/misc";
import { ScoreBar } from "@/components/ui/score-ring";
import { api } from "@/lib/api";

type Round = {
  index: number;
  name: string;
  kind: string;
  score: number | null;
  bar: number;
  status: "Above bar" | "Meets bar" | "Below bar" | "Not attempted";
  norm: string;
  components: { key: string; label: string; score: number | null }[];
  strengths: string[];
  gaps: string[];
  improvements: string[];
  answered: number;
  total: number;
  coding?: { title: string; difficulty?: string; verdict: string; tests?: string; complexity?: string; optimal?: boolean | null; summary?: string; language?: string }[];
};
export type Report = {
  industry: string;
  industry_name: string;
  level: string;
  minutes: number | null;
  minutes_used?: number;
  bar: number;
  score: number | null;
  signal: string;
  rounds: Round[];
  focus: { round: string; do: string }[];
  summary: string | null;
  next_week: string[];
};

const STATUS_TONE = { "Above bar": "success", "Meets bar": "accent", "Below bar": "danger", "Not attempted": "outline" } as const;
const SIGNAL_TONE: Record<string, "success" | "accent" | "warning" | "danger" | "outline"> = { "Strong hire": "success", Hire: "accent", "Lean no": "warning", "No hire": "danger", "Ended early": "danger" };
const VERDICT_TONE: Record<string, "success" | "warning" | "danger" | "outline"> = { correct: "success", "partially correct": "warning", incorrect: "danger" };

/** Every round graded against the field's norms at this level, with strengths, gaps and what to practise. */
export function InterviewReport({ id }: { id: string }) {
  const { data: r, isLoading } = useQuery({ queryKey: ["interview-report", id], queryFn: () => api.get<Report>(`/interviews/${id}/report`) });
  if (isLoading || !r) return <Skeleton className="min-h-60" />;
  return (
    <div className="space-y-4">
      <Card className="space-y-4 p-5">
        <div className="flex flex-wrap items-center gap-3">
          <Badge tone={SIGNAL_TONE[r.signal] ?? "outline"} className="text-[13px]">
            {r.signal}
          </Badge>
          <span className="text-[13px] text-text-2">
            Practice grade for a {r.level} {r.industry_name.toLowerCase()} role · bar {r.bar}/5 per round
            {r.minutes ? ` · planned ${r.minutes} min` : ""}
            {r.minutes_used != null ? `, took ${r.minutes_used} min` : ""}
          </span>
        </div>
        {r.summary && <p className="text-[14px] leading-relaxed">{r.summary}</p>}
        {!!r.focus.length && (
          <div>
            <div className="mb-2 flex items-center gap-1.5 text-[13px] font-medium">
              <Target className="size-4" /> Focus first
            </div>
            <ul className="space-y-1.5 text-[13.5px] text-text-2">
              {r.focus.map((f) => (
                <li key={f.round}>
                  <span className="font-medium text-text">{f.round}:</span> {f.do}
                </li>
              ))}
            </ul>
          </div>
        )}
        {!!r.next_week.length && (
          <div>
            <div className="mb-2 flex items-center gap-1.5 text-[13px] font-medium">
              <TrendingUp className="size-4" /> Your next 7 days
            </div>
            <ol className="list-decimal space-y-1 pl-5 text-[13.5px] text-text-2">
              {r.next_week.map((x) => (
                <li key={x}>{x}</li>
              ))}
            </ol>
          </div>
        )}
        <p className="text-[12px] text-text-3">Practice feedback only: it isn't shared with any employer. Grades follow common hiring-panel language and the bar for your level.</p>
      </Card>

      {r.rounds.map((rd) => (
        <Card key={rd.index}>
          <CardHeader
            icon={rd.kind === "coding" ? <Code2 className="size-4" /> : undefined}
            title={
              <span className="flex flex-wrap items-center gap-2">
                {rd.name}
                <Badge tone={STATUS_TONE[rd.status]}>{rd.status}</Badge>
              </span>
            }
            description={`${rd.score != null ? `${rd.score}/5` : "Not attempted"} · bar ${rd.bar}/5 · ${rd.answered}/${rd.total} answered`}
          />
          <div className="space-y-4 p-5 pt-2">
            <p className="text-[12.5px] text-text-3">
              <span className="font-medium text-text-2">What this field expects:</span> {rd.norm}
            </p>
            {!!rd.components.length && (
              <div className="grid gap-3 sm:grid-cols-2">
                {rd.components.map((c) => (
                  <ScoreBar key={c.key} label={c.label} value={c.score == null ? null : c.score * 20} hint={c.score == null ? "n/a" : `${c.score}/5`} />
                ))}
              </div>
            )}
            {rd.coding && (
              <ul className="space-y-2">
                {rd.coding.map((c) => (
                  <li key={c.title} className="rounded-[var(--radius-card)] border border-border p-3 text-[13px]">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium">{c.title}</span>
                      {c.difficulty && <Badge tone="outline">{c.difficulty}</Badge>}
                      <Badge tone={VERDICT_TONE[c.verdict] ?? "outline"}>{c.verdict}</Badge>
                    </div>
                    {c.tests && (
                      <div className="mt-1 text-text-3">
                        {c.tests}
                        {c.complexity ? ` · ${c.complexity}` : ""}
                        {c.optimal === false ? " · not optimal" : ""}
                      </div>
                    )}
                    {c.summary && <p className="mt-1 text-text-2">{c.summary}</p>}
                  </li>
                ))}
              </ul>
            )}
            <div className="grid gap-4 md:grid-cols-3">
              <Section icon={<CheckCircle2 className="size-4 text-[var(--done)]" />} title="Strengths" items={rd.strengths} empty="Nothing above 4/5 yet." />
              <Section icon={<CircleAlert className="size-4 text-[var(--error)]" />} title="Gaps" items={rd.gaps} empty="No gaps against the bar." />
              <Section icon={<Lightbulb className="size-4 text-[var(--your-turn)]" />} title="Improve" items={rd.improvements} empty="—" />
            </div>
          </div>
        </Card>
      ))}
    </div>
  );
}

function Section({ icon, title, items, empty }: { icon: React.ReactNode; title: string; items: string[]; empty: string }) {
  return (
    <div>
      <div className="mb-1.5 flex items-center gap-1.5 text-[13px] font-medium">
        {icon} {title}
      </div>
      {items.length ? (
        <ul className="space-y-1.5 text-[13px] leading-relaxed text-text-2">
          {items.map((x) => (
            <li key={x}>· {x}</li>
          ))}
        </ul>
      ) : (
        <p className="text-[13px] text-text-3">{empty}</p>
      )}
    </div>
  );
}

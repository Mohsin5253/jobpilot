"use client";

import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, CircleAlert, Code2, Download, FileText, Lightbulb, Target, TrendingUp } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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

async function downloadReport(id: string, format: "pdf" | "docx") {
  let res = await fetch(`/api/interviews/${id}/report/download?format=${format}`, { credentials: "include" });
  if (res.status === 502 || res.status === 503 || res.status === 504) {
    // The server was asleep (free hosting): wake it, then try once more.
    await fetch("/wake", { cache: "no-store" }).catch(() => undefined);
    res = await fetch(`/api/interviews/${id}/report/download?format=${format}`, { credentials: "include" });
  }
  if (!res.ok) {
    let msg = "Couldn't build the report";
    try {
      const b = await res.json();
      if (typeof b.detail === "string") msg = b.detail;
    } catch {}
    throw new Error(msg);
  }
  const name = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") ?? "")?.[1] ?? `interview-report.${format}`;
  const url = URL.createObjectURL(await res.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

/** The whole interview as one document: evaluation, every question with how to answer it, and a self-assessment. */
export function ReportDownload({ id }: { id: string }) {
  const [busy, setBusy] = useState<"pdf" | "docx" | null>(null);
  const go = async (f: "pdf" | "docx") => {
    setBusy(f);
    const t = toast.loading("Writing your report: every question and how to answer it. This can take up to a minute the first time…");
    try {
      await downloadReport(id, f);
      toast.success("Report downloaded", { id: t });
    } catch (e) {
      toast.error((e as Error).message, { id: t });
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-card)] border border-border bg-surface-2/40 p-4">
      <div className="flex min-w-0 items-start gap-2.5">
        <FileText className="mt-0.5 size-4 shrink-0 text-cobalt-text" />
        <div>
          <div className="text-[13.5px] font-medium">Download the full report</div>
          <p className="text-[12.5px] text-text-2">Interviewer evaluation (1-5 matrix, strengths, concerns, recommendation), every question with your answer and how to answer it, and a self-assessment. Each part starts on a new page.</p>
        </div>
      </div>
      <div className="flex gap-2">
        <Button variant="primary" onClick={() => go("pdf")} loading={busy === "pdf"} disabled={!!busy}>
          <Download /> PDF
        </Button>
        <Button onClick={() => go("docx")} loading={busy === "docx"} disabled={!!busy}>
          <Download /> Word
        </Button>
      </div>
    </div>
  );
}

/** Every round graded against the field's norms at this level, with strengths, gaps and what to practise. */
export function InterviewReport({ id }: { id: string }) {
  const { data: r, isLoading } = useQuery({ queryKey: ["interview-report", id], queryFn: () => api.get<Report>(`/interviews/${id}/report`) });
  if (isLoading || !r) return <Skeleton className="min-h-60" />;
  return (
    <div className="space-y-4">
      <ReportDownload id={id} />
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

"use client";

import { useMutation } from "@tanstack/react-query";
import { AlertTriangle, Check, CircleX, Copy, Lightbulb, Sparkles, TrendingUp } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { AiImprove } from "@/components/resume/ai-improve";
import { ScoreBar, ScoreRing } from "@/components/ui/score-ring";
import { api } from "@/lib/api";
import type { AtsCheck, AtsReport, BulletRewrite } from "@/lib/ats-types";
import type { Resume } from "@/lib/types";
import { cn } from "@/lib/utils";

const GRADE_TONE = { Excellent: "success", Good: "accent", Fair: "warning", "Needs work": "danger" } as const;
const IMPORTANCE = { required: "Required", preferred: "Nice to have", core: "Core", nice: "Common" } as const;

export function ScoreHeader({ r, title }: { r: AtsReport; title?: string }) {
  return (
    <div className="flex flex-wrap items-center gap-5">
      <ScoreRing score={r.score} size={96} stroke={7} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-[20px] font-semibold tracking-tight">{title ?? "ATS score"}</h2>
          <Badge tone={GRADE_TONE[r.grade]}>{r.grade}</Badge>
        </div>
        <p className="mt-1 text-[13.5px] text-text-2">
          {r.mode === "job" ? (
            <>
              Scored against {r.job?.title ? <span className="font-medium text-text">{r.job.title}</span> : "this job description"}, with {r.industry_name.toLowerCase()} rules.
            </>
          ) : (
            <>Scored with {r.industry_name.toLowerCase()} rules: what recruiters in this field search for and expect.</>
          )}
        </p>
        <p className="mt-1 text-[12.5px] text-text-3">
          {r.stats.words} words · {r.stats.bullets} bullets · {r.stats.quantified_pct}% with a result · {r.keywords.coverage}% keyword coverage
        </p>
      </div>
    </div>
  );
}

function CheckIcon({ s }: { s: AtsCheck["status"] }) {
  return s === "pass" ? <Check className="size-4 shrink-0 text-[var(--done)]" /> : s === "warn" ? <AlertTriangle className="size-4 shrink-0 text-[var(--your-turn)]" /> : <CircleX className="size-4 shrink-0 text-[var(--error)]" />;
}

/** The full report: score parts, gaps, ranked improvements, keywords, every check, and bullets to fix. */
export function AtsReportView({
  r,
  onUseBullet,
  jobTitle,
  jobDescription,
  improve,
}: {
  r: AtsReport;
  onUseBullet?: (id: string, text: string) => void;
  jobTitle?: string;
  jobDescription?: string;
  improve?: { target: Record<string, unknown>; resume?: Resume; onOpenInBuilder?: (r: Resume) => void };
}) {
  const hard = r.keywords.missing.filter((k) => !k.soft);
  const [showPass, setShowPass] = useState(false);
  const failing = r.checks.filter((c) => c.status !== "pass");
  const passing = r.checks.filter((c) => c.status === "pass");
  return (
    <div className="space-y-4">
      <Card className="p-5">
        <ScoreHeader r={r} />
        {improve && (
          <div className="mt-4 flex flex-wrap items-center gap-3 rounded-[var(--radius-card)] border border-[color-mix(in_oklab,var(--cobalt)_30%,transparent)] bg-cobalt-subtle p-3">
            <AiImprove report={r} target={improve.target} resume={improve.resume} onOpenInBuilder={improve.onOpenInBuilder} />
            <span className="text-[12.5px] text-text-2">Applies these fixes to your resume, adds the keywords you confirm, and gives you a clean PDF or Word file.</span>
          </div>
        )}
        <div className="mt-5 grid gap-3 sm:grid-cols-2">
          {r.breakdown.map((b) => (
            <ScoreBar key={b.key} label={`${b.label} · ${b.weight}%`} value={b.score} hint={`${b.points} of ${b.weight} points`} />
          ))}
        </div>
      </Card>

      {!!r.gaps.length && (
        <Card>
          <CardHeader icon={<CircleX className="size-4" />} title="Gaps in this resume" description="What's missing or blocking you, in plain words." />
          <ul className="space-y-2 p-5 pt-3">
            {r.gaps.map((g) => (
              <li key={g} className="flex gap-2 text-[13.5px] leading-relaxed text-text-2">
                <span aria-hidden className="mt-2 size-1.5 shrink-0 rounded-full bg-[var(--error)]" />
                {g}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {!!r.improvements.length && (
        <Card>
          <CardHeader icon={<TrendingUp className="size-4" />} title="Improvement areas" description="Biggest gain first. Each estimate is what the score rises by if you fix only that." />
          <ol className="divide-y divide-border">
            {r.improvements.map((i, n) => (
              <li key={i.title + n} className="flex gap-3 p-4 px-5">
                <span className="num mt-0.5 grid size-6 shrink-0 place-items-center rounded-full bg-elevated text-[12px] font-semibold">{n + 1}</span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[14px] font-medium">{i.title}</span>
                    <Badge tone="success">up to +{i.gain}</Badge>
                  </div>
                  <p className="mt-1 text-[13px] leading-relaxed text-text-2">{i.detail}</p>
                </div>
              </li>
            ))}
          </ol>
        </Card>
      )}

      <Card>
        <CardHeader title="Keywords" description={r.mode === "job" ? "Terms from this job description, weighted the way a recruiter filters: the title and requirement lines count most." : `The terms ${r.industry_name.toLowerCase()} recruiters search for most.`} />
        <div className="space-y-4 p-5 pt-3">
          <div>
            <div className="mb-2 text-[12.5px] font-medium text-text-2">Missing ({hard.length})</div>
            <div className="flex flex-wrap gap-1.5">
              {hard.length ? (
                hard.map((k) => (
                  <Badge key={k.term} tone={k.importance === "required" ? "danger" : "outline"} title={IMPORTANCE[k.importance]}>
                    {k.term}
                    <span className="opacity-70">· {IMPORTANCE[k.importance]}</span>
                  </Badge>
                ))
              ) : (
                <span className="text-[13px] text-text-3">None. You cover every keyword.</span>
              )}
            </div>
            {!!hard.length && <p className="mt-2 text-[12px] text-text-3">Add one only if you've really used it, and show it in a bullet. Recruiters ask about every keyword in the interview.</p>}
          </div>
          <div>
            <div className="mb-2 text-[12.5px] font-medium text-text-2">Matched ({r.keywords.matched.length})</div>
            <div className="flex flex-wrap gap-1.5">
              {r.keywords.matched.map((k) => (
                <Badge key={k.term} tone={k.in_context || k.soft ? "success" : "outline"} title={k.in_context ? "Shown in a bullet" : "Only listed under Skills"}>
                  <Check /> {k.term}
                  {k.via && <span className="opacity-70">via {k.via}</span>}
                </Badge>
              ))}
            </div>
            {!!r.keywords.listed_only.length && <p className="mt-2 text-[12px] text-text-3">Outlined: only listed under Skills. A bullet that shows you using it counts more.</p>}
          </div>
        </div>
      </Card>

      {!!r.weak_bullets.length && (
        <Card>
          <CardHeader icon={<Lightbulb className="size-4" />} title="Bullets to strengthen" description="AI suggestions keep your facts: no new skills or numbers. Fill in the [placeholders] with your real figures." />
          <div className="divide-y divide-border">
            {r.weak_bullets.map((b) => (
              <WeakBullet key={b.id} b={b} onUse={onUseBullet} jobTitle={jobTitle} jobDescription={jobDescription} industry={r.industry} />
            ))}
          </div>
        </Card>
      )}

      <Card>
        <CardHeader title="ATS checks" description={`${failing.length} to fix · ${passing.length} passed`} action={<Button size="sm" variant="ghost" onClick={() => setShowPass((v) => !v)}>{showPass ? "Hide passed" : "Show passed"}</Button>} />
        <ul className="divide-y divide-border">
          {[...failing, ...(showPass ? passing : [])].map((c) => (
            <li key={c.id} className="flex gap-3 p-4 px-5">
              <CheckIcon s={c.status} />
              <div className="min-w-0">
                <div className="text-[13.5px] font-medium">{c.label}</div>
                <p className="mt-0.5 text-[13px] text-text-2">{c.detail}</p>
                {c.status !== "pass" && c.fix && <p className="mt-1 text-[12.5px] text-text-3">Fix: {c.fix}</p>}
              </div>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

function WeakBullet({ b, onUse, jobTitle, jobDescription, industry }: { b: AtsReport["weak_bullets"][number]; onUse?: (id: string, text: string) => void; jobTitle?: string; jobDescription?: string; industry: string }) {
  const suggest = useMutation({
    mutationFn: () => api.post<BulletRewrite>("/resume/improve-bullet", { text: b.text, industry, job_title: jobTitle ?? "", job_description: (jobDescription ?? "").slice(0, 8000) }),
    onError: (e: Error) => toast.error(e.message),
  });
  return (
    <div className="space-y-2 p-4 px-5">
      <p className="text-[13.5px]">{b.text}</p>
      <div className="flex flex-wrap gap-1.5">
        {b.issues.map((i) => (
          <Badge key={i} tone="warning">
            {i}
          </Badge>
        ))}
      </div>
      {b.suggestion && <p className="text-[12.5px] text-text-2">{b.suggestion}</p>}
      {!suggest.data && (
        <Button size="sm" variant="ghost" onClick={() => suggest.mutate()} loading={suggest.isPending}>
          <Sparkles /> Suggest a rewrite
        </Button>
      )}
      {suggest.data && (
        <div className="space-y-2">
          {!suggest.data.options.length && <p className="text-[12.5px] text-text-3">{suggest.data.ai ? "No rewrite passed the no-fabrication check. Use the tip above." : "AI rewrites aren't available right now. Use the tip above."}</p>}
          {suggest.data.options.map((o) => (
            <div key={o.text} className={cn("flex items-start gap-2 rounded-[var(--radius-card)] border border-border bg-elevated p-3")}>
              <p className="flex-1 text-[13px]">{o.text}</p>
              {onUse ? (
                <Button size="sm" onClick={() => onUse(b.id, o.text)}>
                  Use
                </Button>
              ) : (
                <Button size="sm" variant="ghost" aria-label="Copy" onClick={() => navigator.clipboard?.writeText(o.text).then(() => toast.success("Copied"))}>
                  <Copy />
                </Button>
              )}
            </div>
          ))}
          {suggest.data.rejected > 0 && <p className="text-[12px] text-text-3">{suggest.data.rejected} suggestion(s) were dropped because they added a skill or number you didn't write.</p>}
        </div>
      )}
    </div>
  );
}

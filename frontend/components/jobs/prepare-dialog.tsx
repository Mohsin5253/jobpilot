"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Sparkles, Target } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { ScoreRing } from "@/components/ui/score-ring";
import { api } from "@/lib/api";
import { useProfile } from "@/lib/queries";
import type { Resume } from "@/lib/types";

type Boost = {
  resume: Resume;
  before: number;
  after: number;
  reached: boolean;
  target: number;
  note: string;
  plan: { keywords: string[]; figures: string[]; projected: number; reachable: boolean };
  missing_keywords: string[];
  needs_figures: { id: string; text: string; question: string; example: string }[];
  changes: { section: string; after: string; why: string }[];
};
const TARGETS = [80, 85, 90, 95];

/**
 * "Prepare application", target first: pick the ATS score this job's resume must reach, confirm the job's keywords
 * you've really used and add real figures, then the tailored resume and email are prepared from that resume. The
 * application is only sent once the tailored resume reaches the target.
 */
export function PrepareDialog({ matchId, disabled, loading, waiting, onStarted }: { matchId: string; disabled?: boolean; loading?: boolean; waiting?: boolean; onStarted?: () => void }) {
  const { data: profile } = useProfile();
  const [open, setOpen] = useState(false);
  const [goal, setGoal] = useState<number>(profile?.preferences?.ats_target || 90);
  const [picked, setPicked] = useState<string[]>([]);
  const [figures, setFigures] = useState<Record<string, string>>({});
  const [first, setFirst] = useState<number | null>(null);
  const qc = useQueryClient();
  const boost = useMutation({
    mutationFn: (o: { from?: Resume; prev?: number } = {}) =>
      api.post<Boost>("/resume/ai-boost", { match_id: matchId, target: goal, ...(o.from ? { resume: o.from } : {}), confirmed_keywords: picked, figures }),
    onSuccess: (d, o) => {
      const was = o?.prev;
      setFirst((f) => f ?? d.before);
      setPicked([]);
      setFigures({});
      if (!o?.from) return;
      if (d.reached) toast.success(`Re-scored: ${d.after}. Target ${d.target} reached.`);
      else if (was != null && d.after > was) toast.success(`Re-scored: ${was} → ${d.after}. ${d.target - d.after} to go for your target.`);
      else toast.info(`Still ${d.after}: those changes didn't add keywords this job's ATS looks for. Try the ★ skills.`);
    },
    onError: (e: Error) => toast.error(`Couldn't check your resume: ${e.message}`),
  });
  const r = boost.data;
  const prepare = useMutation({
    mutationFn: () => api.post(`/matches/${matchId}/prepare`, { target: goal, ...(r ? { resume: r.resume } : {}) }),
    onSuccess: () => {
      const next = "The tailored resume and email will be in Approvals in about a minute; nothing is sent until you approve.";
      toast.success(
        waiting
          ? "Queued: your agents are finishing another run, and this job goes next."
          : r && r.reached
            ? `Preparing your application: the resume scores ${r.after} for this job.`
            : r
              ? `Preparing your application. Its resume scores ${r.after}, below your target ${r.target}, so it won't be sent until it reaches it.`
              : "Preparing your application.",
        { description: next, duration: 8000 },
      );
      ["overview", "runs", "match", "matches", "profile", "ats-target"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
      setOpen(false);
      onStarted?.();
    },
    onError: (e: Error) => toast.error(`Couldn't start preparing: ${e.message}`),
  });
  const filled = Object.values(figures).filter((v) => /\d/.test(v)).length;
  const toggle = (k: string) => setPicked((p) => (p.includes(k) ? p.filter((x) => x !== k) : [...p, k]));

  return (
    <>
      <Button variant="primary" disabled={disabled} loading={loading} onClick={() => (boost.reset(), setFirst(null), setOpen(true))}>
        <Sparkles /> Prepare application
      </Button>
      {waiting && !loading && <p className="max-w-sm text-[12.5px] text-text-3">Your agents are on another run. You can still prepare this one: it goes next.</p>}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent title="Prepare this application" description="First, the ATS score this job's resume must reach. Nothing is invented: you confirm the skills you've used and add your real figures. The application is only sent once the tailored resume reaches the target." className="max-w-[680px]">
          <div className="space-y-4">
            <div>
              <div className="flex items-center gap-1.5 text-[13.5px] font-medium">
                <Target className="size-4" /> Target ATS score for this job
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {TARGETS.map((t) => (
                  <button key={t} type="button" aria-pressed={goal === t} onClick={() => (setGoal(t), boost.reset(), setFirst(null))} className={`num h-8 rounded-full border px-3.5 text-[13px] ${goal === t ? "border-[var(--cobalt)] bg-cobalt-subtle text-cobalt-text" : "border-border text-text-2 hover:text-text"}`}>
                    {t}
                  </button>
                ))}
              </div>
            </div>
            {!r ? (
              <Button variant="primary" onClick={() => boost.mutate({})} loading={boost.isPending}>
                <Sparkles /> Check my resume against this job
              </Button>
            ) : (
              <>
                <div className="flex flex-wrap items-center gap-3">
                  <ScoreRing score={first ?? r.before} size={48} stroke={4} />
                  <ArrowRight className="size-4 text-text-3" />
                  <ScoreRing score={r.after} size={48} stroke={4} />
                  <Badge tone={r.reached ? "success" : "warning"}>{r.reached ? `Target ${r.target} reached` : `Target ${r.target}: ${r.target - r.after} to go`}</Badge>
                </div>
                <p className="text-[13px]">{r.note}</p>
                {!r.reached && !!r.missing_keywords.length && (
                  <div className="rounded-[var(--radius-card)] border border-border p-3">
                    <div className="text-[13.5px] font-medium">This job&rsquo;s keywords missing from your resume</div>
                    <p className="mt-0.5 text-[12.5px] text-text-3">Tick only what you&rsquo;ve really used; it&rsquo;s added to your resume and the tailored version. ★ = fastest to the target.</p>
                    <div className="mt-2.5 flex flex-wrap gap-1.5">
                      {r.missing_keywords.map((k) => (
                        <button key={k} type="button" aria-pressed={picked.includes(k)} onClick={() => toggle(k)} className={`h-8 rounded-full border px-3 text-[12.5px] ${picked.includes(k) ? "border-[var(--cobalt)] bg-cobalt-subtle text-cobalt-text" : r.plan.keywords.includes(k) ? "border-warning/60 text-text" : "border-border text-text-2 hover:text-text"}`}>
                          {picked.includes(k) ? "✓ " : ""}
                          {k}
                          {r.plan.keywords.includes(k) && !picked.includes(k) ? " ★" : ""}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {!r.reached && !!r.needs_figures.length && (
                  <div className="rounded-[var(--radius-card)] border border-border p-3">
                    <div className="text-[13.5px] font-medium">Your real figures</div>
                    <ul className="mt-2 max-h-[28vh] space-y-2.5 overflow-y-auto pr-1">
                      {r.needs_figures.map((n) => (
                        <li key={n.id} className="space-y-1">
                          <p className="text-[12.5px] text-text-2">
                            {r.plan.figures.includes(n.id) && <span className="mr-1 text-warning">★</span>}
                            {n.text}
                          </p>
                          <input
                            value={figures[n.id] ?? ""}
                            onChange={(e) => setFigures((f) => ({ ...f, [n.id]: e.target.value }))}
                            placeholder={`${n.question} (${n.example})`}
                            aria-label={`Figure for: ${n.text}`}
                            className="h-9 w-full rounded-[var(--radius-control)] border border-border bg-transparent px-3 text-[13px] outline-none focus:border-[var(--cobalt)]"
                          />
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                <div className="flex flex-wrap gap-2 border-t border-border pt-4">
                  {!r.reached && (
                    <Button
                      variant="primary"
                      disabled={!picked.length && !filled}
                      title={!picked.length && !filled ? "Tick a skill you've used, or add a figure with a number, first" : undefined}
                      loading={boost.isPending}
                      onClick={() => boost.mutate({ from: r.resume, prev: r.after })}
                    >
                      <Sparkles /> Apply and re-score
                    </Button>
                  )}
                  <Button variant={r.reached ? "primary" : "secondary"} loading={prepare.isPending} onClick={() => prepare.mutate()}>
                    {r.reached ? "Prepare application" : "Prepare anyway (won't send below target)"}
                  </Button>
                </div>
                {!r.reached && !picked.length && !filled && (r.missing_keywords.length > 0 || r.needs_figures.length > 0) && (
                  <p className="text-[12px] text-text-3">To re-score, tick a skill you&rsquo;ve really used or type a figure with a number (for example &ldquo;200 users&rdquo;).</p>
                )}
                {!r.reached && Object.values(figures).some((v) => v.trim() && !/\d/.test(v)) && (
                  <p className="text-[12px] text-[var(--warning)]">A figure needs a number, like &ldquo;40% faster&rdquo; or &ldquo;3 teams&rdquo;.</p>
                )}
                <p className="text-[12px] text-text-3">Preparing saves this version as your resume (only the skills and figures you confirmed are added), then tailors it for the job and drafts the email for your approval.</p>
              </>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

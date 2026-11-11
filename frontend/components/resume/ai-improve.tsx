"use client";

import { useMutation } from "@tanstack/react-query";
import { ArrowRight, Download, PencilLine, Save, Sparkles, Wand2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { download } from "@/components/resume/builder";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { ScoreRing } from "@/components/ui/score-ring";
import { api } from "@/lib/api";
import type { AtsReport } from "@/lib/ats-types";
import { useSaveProfile } from "@/lib/queries";
import type { Resume } from "@/lib/types";

type Change = { section: string; before: string; after: string; why: string };
type Ask = { id: string; text: string; question: string; example: string };
type Improved = {
  resume: Resume;
  changes: Change[];
  before: number;
  after: number;
  after_report: AtsReport;
  still_missing: string[];
  ai: boolean;
  note: string;
  target: number;
  reached: boolean;
  potential: number;
  needs_figures: Ask[];
  remaining: { title: string; detail: string; gain: number }[];
  industry_name: string;
  track: { key: string; label: string } | null;
  plan: { keywords: string[]; figures: string[]; projected: number; reachable: boolean };
  missing_keywords: string[];
};
const TARGETS = [80, 85, 90, 95];

/**
 * One click from the ATS report to a better resume: stronger bullets (facts kept), a summary from the resume's own
 * facts, and the missing keywords the student ticks as genuinely used. Shows every change and the new score, then
 * downloads it (PDF or Word), saves it, or opens it in the builder.
 */
export function AiImprove({
  report,
  target,
  resume,
  onOpenInBuilder,
  onApply,
  label = "Boost my ATS score with AI",
}: {
  report: AtsReport;
  target: Record<string, unknown>;
  resume?: Resume;
  onOpenInBuilder?: (r: Resume) => void;
  /** In the builder: every round is applied to the draft straight away, so the live score follows. */
  onApply?: (r: Resume) => void;
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  const missing = report.keywords.missing.filter((k) => !k.soft).map((k) => k.term);
  const [picked, setPicked] = useState<string[]>([]);
  const [goal, setGoal] = useState(90);
  const [figures, setFigures] = useState<Record<string, string>>({});
  const [first, setFirst] = useState<number | null>(null);
  const [busy, setBusy] = useState<"pdf" | "docx" | null>(null);
  const save = useSaveProfile();
  const run = useMutation({
    // Each round builds on the last one's resume, so figures and fixes add up.
    mutationFn: (opts: { from?: Resume; figs?: Record<string, string> } = {}) =>
      api.post<Improved>("/resume/ai-boost", {
        ...target,
        ...(opts.from ? { resume: opts.from } : resume ? { resume } : {}),
        confirmed_keywords: picked,
        target: goal,
        figures: opts.figs ?? {},
      }),
    onSuccess: (d) => {
      setFirst((f) => f ?? d.before);
      setFigures({});
      setPicked([]);
      onApply?.(d.resume);
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const r = run.data;
  const filled = Object.values(figures).filter((v) => /\d/.test(v)).length;
  const neededFig = new Set(r?.plan.figures ?? []);
  const dl = async (f: "pdf" | "docx") => {
    if (!r) return;
    setBusy(f);
    try {
      await download(r.resume, f);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(null);
    }
  };
  const toggle = (k: string) => setPicked((p) => (p.includes(k) ? p.filter((x) => x !== k) : [...p, k]));

  return (
    <>
      <Button variant="primary" onClick={() => (run.reset(), setFirst(null), setFigures({}), setOpen(true))}>
        <Wand2 /> {label}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent title="Boost my ATS score" description="Takes your resume toward the score you pick, using your field's grading. Nothing is invented: where a real number is needed, you're asked for it. Nothing is saved until you choose to." className="max-w-[680px]">
          {!r ? (
            <div className="space-y-4">
              <div>
                <div className="text-[13.5px] font-medium">Target score</div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {TARGETS.map((t) => (
                    <button key={t} type="button" aria-pressed={goal === t} onClick={() => setGoal(t)} className={`num h-8 rounded-full border px-3.5 text-[13px] ${goal === t ? "border-[var(--cobalt)] bg-cobalt-subtle text-cobalt-text" : "border-border text-text-2 hover:text-text"}`}>
                      {t}
                    </button>
                  ))}
                </div>
              </div>
              <ul className="space-y-1.5 text-[13.5px] text-text-2">
                <li>· Clean single-column structure with standard headings, as enterprise ATS parsers expect.</li>
                <li>· Weak bullets rewritten with strong action verbs, every fact and number kept.</li>
                <li>· A 2-3 line summary from your own resume; the skills your field searches for first.</li>
                <li>· Then it asks for the real figure behind each bullet without a result, and rewrites it in Google&rsquo;s XYZ form (achieved X, measured by Y, by doing Z).</li>
              </ul>
              {!!missing.length && (
                <div className="rounded-[var(--radius-card)] border border-border p-3">
                  <div className="text-[13.5px] font-medium">Missing keywords: tick the ones you've really used</div>
                  <p className="mt-0.5 text-[12.5px] text-text-3">They'll be added to Skills. Leave out anything you couldn't talk about in an interview.</p>
                  <div className="mt-2.5 flex flex-wrap gap-1.5">
                    {missing.map((k) => (
                      <button
                        key={k}
                        type="button"
                        aria-pressed={picked.includes(k)}
                        onClick={() => toggle(k)}
                        className={`h-8 rounded-full border px-3 text-[12.5px] ${picked.includes(k) ? "border-[var(--cobalt)] bg-cobalt-subtle text-cobalt-text" : "border-border text-text-2 hover:text-text"}`}
                      >
                        {picked.includes(k) ? "✓ " : ""}
                        {k}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              <Button variant="primary" onClick={() => run.mutate({})} loading={run.isPending}>
                <Sparkles /> Boost to {goal}
              </Button>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-3">
                <ScoreRing score={first ?? r.before} size={52} stroke={4} />
                <ArrowRight className="size-4 text-text-3" />
                <ScoreRing score={r.after} size={52} stroke={4} />
                <Badge tone={r.reached ? "success" : "neutral"} className="num">
                  {r.reached ? `Target ${r.target} reached` : `Target ${r.target}`}
                </Badge>
                {!r.reached && r.potential > r.after && (
                  <span className="text-[12.5px] text-text-2">
                    With your figures: <b className="num">≈{r.potential}</b>
                  </span>
                )}
                <span className="w-full text-[12px] text-text-3">
                  Graded as {r.industry_name}
                  {r.track ? ` · ${r.track.label}` : ""} · {r.ai ? "AI rewrites, checked against your resume" : "Rule-based rewrites (AI unavailable)"}
                </span>
              </div>
              {r.note && <p className="text-[13px]">{r.note}</p>}
              {!r.reached && !!r.missing_keywords.length && (
                <div className="rounded-[var(--radius-card)] border border-border p-3">
                  <div className="text-[13.5px] font-medium">Skills recruiters search for{r.track ? ` in ${r.track.label.toLowerCase()} roles` : ""}</div>
                  <p className="mt-0.5 text-[12.5px] text-text-3">Tick only the ones you&rsquo;ve really used. {r.plan.keywords.length ? "The highlighted ones get you to the target fastest." : ""}</p>
                  <div className="mt-2.5 flex flex-wrap gap-1.5">
                    {r.missing_keywords.map((k) => (
                      <button
                        key={k}
                        type="button"
                        aria-pressed={picked.includes(k)}
                        onClick={() => toggle(k)}
                        className={`h-8 rounded-full border px-3 text-[12.5px] ${picked.includes(k) ? "border-[var(--cobalt)] bg-cobalt-subtle text-cobalt-text" : r.plan.keywords.includes(k) ? "border-warning/60 text-text" : "border-border text-text-2 hover:text-text"}`}
                      >
                        {picked.includes(k) ? "✓ " : ""}
                        {k}
                        {r.plan.keywords.includes(k) && !picked.includes(k) ? " ★" : ""}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {!!r.needs_figures.length && (
                <div className="rounded-[var(--radius-card)] border border-border p-3">
                  <div className="text-[13.5px] font-medium">Add your real figures</div>
                  <p className="mt-0.5 text-[12.5px] text-text-3">Leave blank anything you can&rsquo;t back up in an interview. Each one is rewritten in XYZ form using only your bullet and your figure.</p>
                  <ul className="mt-3 max-h-[34vh] space-y-3 overflow-y-auto pr-1">
                    {r.needs_figures.map((n) => (
                      <li key={n.id} className="space-y-1.5">
                        <p className="text-[12.5px] text-text-2">
                          {neededFig.has(n.id) && <span className="mr-1 text-warning">★</span>}
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
              {!r.reached && (
                <Button variant="primary" disabled={!filled && !picked.length} loading={run.isPending} onClick={() => run.mutate({ from: r.resume, figs: figures })}>
                  <Sparkles /> Apply {picked.length ? `${picked.length} skill${picked.length === 1 ? "" : "s"}` : ""}
                  {picked.length && filled ? " + " : ""}
                  {filled ? `${filled} figure${filled === 1 ? "" : "s"}` : ""} and re-score
                </Button>
              )}
              {!!r.remaining.length && !r.reached && (
                <div className="text-[12.5px]">
                  <div className="font-medium">Also worth doing</div>
                  <ul className="mt-1 space-y-1 text-text-2">
                    {r.remaining.map((x) => (
                      <li key={x.title}>
                        · {x.title} <span className="text-success">+{x.gain}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <details>
                <summary className="cursor-pointer text-[13px] font-medium text-cobalt-text">What changed ({r.changes.length})</summary>
                <ul className="mt-2 max-h-[36vh] space-y-2 overflow-y-auto pr-1">
                {r.changes.map((c, i) => (
                  <li key={i} className="rounded-[var(--radius-card)] border border-border p-3 text-[13px]">
                    <div className="mb-1 flex items-center gap-2">
                      <Badge tone="outline">{c.section}</Badge>
                      <span className="text-[12px] text-text-3">{c.why}</span>
                    </div>
                    {c.before && <p className="text-text-3 line-through">{c.before}</p>}
                    <p>{c.after}</p>
                  </li>
                ))}
                {!r.changes.length && <li className="text-[13px] text-text-2">Your resume already follows these fixes. Add your real numbers to bullets for the next gain.</li>}
                </ul>
              </details>
              {!!r.still_missing.length && <p className="text-[12.5px] text-text-3">Still missing (add only if you've used them): {r.still_missing.join(", ")}</p>}
              <div className="flex flex-wrap gap-2 border-t border-border pt-4">
                <Button variant="primary" onClick={() => dl("pdf")} loading={busy === "pdf"}>
                  <Download /> Download PDF
                </Button>
                <Button onClick={() => dl("docx")} loading={busy === "docx"}>
                  <Download /> Download Word
                </Button>
                <Button onClick={() => save.mutate({ resume: r.resume }, { onSuccess: () => setOpen(false) })} loading={save.isPending}>
                  <Save /> Save as my resume
                </Button>
                {onOpenInBuilder && (
                  <Button
                    variant="ghost"
                    onClick={() => {
                      onOpenInBuilder(r.resume);
                      setOpen(false);
                    }}
                  >
                    <PencilLine /> Edit in builder
                  </Button>
                )}
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}

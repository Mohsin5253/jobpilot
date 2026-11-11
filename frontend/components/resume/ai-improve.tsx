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
type Improved = { resume: Resume; changes: Change[]; before: number; after: number; after_report: AtsReport; still_missing: string[]; ai: boolean; note: string };

/**
 * One click from the ATS report to a better resume: stronger bullets (facts kept), a summary from the resume's own
 * facts, and the missing keywords the student ticks as genuinely used. Shows every change and the new score, then
 * downloads it (PDF or Word), saves it, or opens it in the builder.
 */
export function AiImprove({ report, target, resume, onOpenInBuilder }: { report: AtsReport; target: Record<string, unknown>; resume?: Resume; onOpenInBuilder?: (r: Resume) => void }) {
  const [open, setOpen] = useState(false);
  const missing = report.keywords.missing.filter((k) => !k.soft).map((k) => k.term);
  const [picked, setPicked] = useState<string[]>([]);
  const [busy, setBusy] = useState<"pdf" | "docx" | null>(null);
  const save = useSaveProfile();
  const run = useMutation({
    mutationFn: () => api.post<Improved>("/resume/ai-improve", { ...target, ...(resume ? { resume } : {}), confirmed_keywords: picked }),
    onError: (e: Error) => toast.error(e.message),
  });
  const r = run.data;
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
      <Button variant="primary" onClick={() => (run.reset(), setOpen(true))}>
        <Wand2 /> Improve my resume with AI
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent title="Improve my resume" description="Applies the report's fixes to your resume. Nothing is invented, and nothing is saved until you choose to." className="max-w-[640px]">
          {!r ? (
            <div className="space-y-4">
              <ul className="space-y-1.5 text-[13.5px] text-text-2">
                <li>· Rewrites weak bullets with strong verbs, keeping every fact and number.</li>
                <li>· Writes a 2-3 line summary from your own resume, naming your field.</li>
                <li>· Puts the skills recruiters search for first.</li>
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
              <Button variant="primary" onClick={() => run.mutate()} loading={run.isPending}>
                <Sparkles /> Improve now
              </Button>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-3">
                <ScoreRing score={r.before} size={52} stroke={4} />
                <ArrowRight className="size-4 text-text-3" />
                <ScoreRing score={r.after} size={52} stroke={4} />
                <Badge tone={r.after > r.before ? "success" : "neutral"} className="num">
                  {r.after >= r.before ? "+" : ""}
                  {r.after - r.before} points
                </Badge>
                <span className="text-[12px] text-text-3">{r.ai ? "AI rewrites, checked against your resume" : "Rule-based rewrites (AI unavailable)"}</span>
              </div>
              <ul className="max-h-[42vh] space-y-2 overflow-y-auto pr-1">
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
              {r.note && <p className="text-[12.5px] text-text-2">{r.note}</p>}
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

"use client";

import { useMutation } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, Check, Download, FileUp, LayoutList, PencilLine, Save } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { download } from "@/components/resume/builder";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { ScoreRing } from "@/components/ui/score-ring";
import { api } from "@/lib/api";
import { useSaveProfile } from "@/lib/queries";
import type { Resume } from "@/lib/types";

type Restructured = { resume: Resume; ai: boolean; notes: string[]; unplaced: string[]; sections: string[]; before: number; after: number };

/**
 * Rebuilds a messy resume into a proper structure (contact, summary, grouped skills, roles with title · company ·
 * location · dates and their stack, projects, education, certifications) from the student's own words, then shows
 * what changed, any line that didn't fit, and a section-by-section preview before they download or save it.
 */
export function RestructureResume({ hasResume, onOpenInBuilder, variant = "secondary" }: { hasResume: boolean; onOpenInBuilder?: (r: Resume) => void; variant?: "primary" | "secondary" }) {
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState<"pdf" | "docx" | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const save = useSaveProfile();
  const run = useMutation({
    mutationFn: () => {
      const form = new FormData();
      if (file) form.append("file", file);
      return api.post<Restructured>("/resume/restructure", form);
    },
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

  return (
    <>
      <Button variant={variant} onClick={() => (run.reset(), setFile(null), setOpen(true))}>
        <LayoutList /> Restructure with AI
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent title="Restructure my resume" description="Puts your own words into a clean, ATS-friendly structure. Nothing is reworded or invented, and nothing is saved until you choose to." className="max-w-[700px]">
          {!r ? (
            <div className="space-y-4">
              <ul className="space-y-1.5 text-[13.5px] text-text-2">
                <li>· Each role as Title · Company, Location with dates on the right, bullets, then its tech stack.</li>
                <li>· Long project paragraphs split into one bullet per point; stacks moved to a Tech line.</li>
                <li>· Skills kept in labelled groups; certifications and awards under their own heading.</li>
                <li>· Icon symbols and words broken across lines (&ldquo;Kuber-netes&rdquo;) repaired. A summary added if you have none.</li>
              </ul>
              <div className="rounded-[var(--radius-card)] border border-border p-3">
                <div className="text-[13.5px] font-medium">Which resume?</div>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  {hasResume && (
                    <Button size="sm" variant={file ? "ghost" : "secondary"} onClick={() => setFile(null)} aria-pressed={!file}>
                      {!file && <Check />} My uploaded resume
                    </Button>
                  )}
                  <Button size="sm" variant={file ? "secondary" : "ghost"} onClick={() => input.current?.click()}>
                    <FileUp /> {file ? file.name : "Choose a file (PDF, DOCX)"}
                  </Button>
                  <input ref={input} type="file" accept=".pdf,.docx,.txt,.md" className="sr-only" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
                </div>
              </div>
              <Button variant="primary" onClick={() => run.mutate()} loading={run.isPending} disabled={!hasResume && !file}>
                <LayoutList /> Restructure now
              </Button>
              {run.isPending && <p className="text-[12.5px] text-text-3">Reading every line and placing it… this takes 10-30 seconds.</p>}
            </div>
          ) : (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center gap-3">
                <ScoreRing score={r.before} size={52} stroke={4} />
                <ArrowRight className="size-4 text-text-3" />
                <ScoreRing score={r.after} size={52} stroke={4} />
                <Badge tone={r.after > r.before ? "success" : "neutral"} className="num">
                  {r.after >= r.before ? "+" : ""}
                  {r.after - r.before} ATS points
                </Badge>
                <span className="text-[12px] text-text-3">{r.ai ? "AI placement, every line checked against your resume" : "Layout parser (AI unavailable)"}</span>
              </div>
              <div className="flex flex-wrap gap-1.5" aria-label="Sections">
                {r.sections.map((s) => (
                  <Badge key={s} tone="outline">
                    {s}
                  </Badge>
                ))}
              </div>
              <ul className="space-y-1 text-[13px]">
                {r.notes.map((n) => (
                  <li key={n} className="flex gap-2">
                    <Check className="mt-0.5 size-3.5 shrink-0 text-success" />
                    <span>{n}</span>
                  </li>
                ))}
              </ul>
              {!!r.unplaced.length && (
                <div className="rounded-[var(--radius-card)] border border-warning/40 p-3 text-[12.5px]">
                  <div className="flex items-center gap-1.5 font-medium">
                    <AlertTriangle className="size-3.5 text-warning" /> Check these lines: they didn&rsquo;t clearly fit a section
                  </div>
                  <ul className="mt-1.5 space-y-1 text-text-2">
                    {r.unplaced.map((l) => (
                      <li key={l}>· {l}</li>
                    ))}
                  </ul>
                  <p className="mt-1.5 text-text-3">Add them in the builder if they matter.</p>
                </div>
              )}
              <Preview r={r.resume} />
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

/** A compact outline of the new structure, in the order the file prints it. */
function Preview({ r }: { r: Resume }) {
  const H = ({ children }: { children: React.ReactNode }) => <div className="mt-3 border-b border-border pb-0.5 text-[11px] font-semibold tracking-wide text-cobalt-text uppercase first:mt-0">{children}</div>;
  const Role = ({ left, sub, right }: { left: string; sub?: string; right?: string }) => (
    <div className="mt-1.5 flex flex-wrap items-baseline justify-between gap-x-3">
      <span>
        <b>{left}</b>
        {sub ? <span className="text-text-2"> · {sub}</span> : null}
      </span>
      {right ? <span className="text-[11.5px] text-text-3 italic">{right}</span> : null}
    </div>
  );
  const span = (a: string, b: string) => [a, b].filter(Boolean).join(" – ");
  return (
    <div className="max-h-[38vh] overflow-y-auto rounded-[var(--radius-card)] border border-border bg-surface-2/40 p-4 text-[12.5px] leading-relaxed">
      <div className="text-center text-[15px] font-semibold">{r.name}</div>
      <div className="text-center text-[11.5px] text-text-3">{[r.email, r.phone, r.location, ...r.links].filter(Boolean).join(" | ")}</div>
      {r.summary && (
        <>
          <H>Summary</H>
          <p>{r.summary}</p>
        </>
      )}
      {(r.skill_groups?.length || r.skills.length) && (
        <>
          <H>Skills</H>
          {r.skill_groups?.length ? (
            r.skill_groups.map((g) => (
              <p key={g.name}>
                <b>{g.name || "Skills"}:</b> {g.items.join(", ")}
              </p>
            ))
          ) : (
            <p>{r.skills.join(", ")}</p>
          )}
        </>
      )}
      {!!r.experience.length && <H>Experience</H>}
      {r.experience.map((e, i) => (
        <div key={i}>
          <Role left={e.title || e.organization} sub={[e.title ? e.organization : "", e.location].filter(Boolean).join(", ")} right={span(e.start, e.end)} />
          <ul className="ml-4 list-disc">
            {e.bullets.map((b, j) => (
              <li key={j}>{b}</li>
            ))}
          </ul>
          {!!e.tech?.length && <p className="ml-4 text-[11.5px] text-text-3">Tech: {e.tech.join(", ")}</p>}
        </div>
      ))}
      {!!r.projects.length && <H>Projects</H>}
      {r.projects.map((p, i) => (
        <div key={i}>
          <Role left={p.name} />
          <ul className="ml-4 list-disc">
            {p.bullets.map((b, j) => (
              <li key={j}>{b}</li>
            ))}
          </ul>
          {!!p.tech.length && <p className="ml-4 text-[11.5px] text-text-3">Tech: {p.tech.join(", ")}</p>}
        </div>
      ))}
      {!!r.education.length && <H>Education</H>}
      {r.education.map((e, i) => (
        <div key={i}>
          <Role left={e.degree || e.school} sub={e.degree ? e.school : ""} right={span(e.start, e.end)} />
          {e.details && <p className="whitespace-pre-line text-text-2">{e.details}</p>}
        </div>
      ))}
      {!!r.certifications?.length && (
        <>
          <H>Certifications & awards</H>
          <ul className="ml-4 list-disc">
            {r.certifications.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

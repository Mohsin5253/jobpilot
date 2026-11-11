"use client";

import { useMutation } from "@tanstack/react-query";
import { Download, Plus, Save, Trash2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { ScoreHeader } from "@/components/resume/ats-report";
import { AtsTarget, targetBody, type Target } from "@/components/resume/ats-target";
import { AtsReportView } from "@/components/resume/ats-report";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Field, Input, Textarea } from "@/components/ui/input";
import { TagInput } from "@/components/ui/tag-input";
import { api } from "@/lib/api";
import type { AtsReport } from "@/lib/ats-types";
import { useSaveProfile } from "@/lib/queries";
import type { Resume, SkillGroup } from "@/lib/types";

const blank: Resume = { name: "", email: "", phone: "", location: "", links: [], summary: "", skills: [], skill_groups: [], experience: [], projects: [], education: [], certifications: [], additional: [] };
const lines = (s: string) => s.split("\n").map((l) => l.replace(/^[•\-*]\s*/, "").trim()).filter(Boolean);

export async function download(resume: Resume, format: "pdf" | "docx") {
  const res = await fetch(`/api/resume/render?format=${format}`, { method: "POST", credentials: "include", headers: { "content-type": "application/json" }, body: JSON.stringify(resume) });
  if (!res.ok) throw new Error("Couldn't build the file");
  const name = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") ?? "")?.[1] ?? `resume.${format}`;
  const url = URL.createObjectURL(await res.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

/**
 * A structured editor that produces an ATS-friendly resume (one column, standard headings, real text). Every edit is
 * re-scored live against the chosen field or job, so the student sees each change move the score.
 */
export function ResumeBuilder({ initial, target, setTarget }: { initial: Resume | undefined; target: Target; setTarget: (t: Target) => void }) {
  const [r, setR] = useState<Resume>(initial ?? blank);
  const loaded = useRef(false);
  useEffect(() => {
    if (initial && !loaded.current) {
      loaded.current = true;
      setR({ ...blank, ...initial });
    }
  }, [initial]);
  const save = useSaveProfile();
  const score = useMutation({ mutationFn: (body: object) => api.post<AtsReport>("/ats/score", body) });
  const body = useMemo(() => ({ resume: r, ...targetBody(target) }), [r, target]);
  const key = JSON.stringify(body);
  useEffect(() => {
    if (target.kind === "match" && !target.matchId) return;
    const t = setTimeout(() => score.mutate(body), 600);
    return () => clearTimeout(t);
    // Re-score only when the resume or target actually changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  const [busy, setBusy] = useState<"pdf" | "docx" | null>(null);
  const dl = async (f: "pdf" | "docx") => {
    setBusy(f);
    try {
      await download(r, f);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(null);
    }
  };
  const set = <K extends keyof Resume>(k: K, v: Resume[K]) => setR((x) => ({ ...x, [k]: v }));
  const useBullet = (id: string, text: string) => {
    const m = /^(exp|proj)(\d+)\.b(\d+)$/.exec(id);
    if (!m) return;
    const [, kind, i, j] = m;
    setR((x) => {
      const list = kind === "exp" ? [...x.experience] : [...x.projects];
      const item = { ...list[+i], bullets: [...list[+i].bullets] };
      item.bullets[+j] = text;
      list[+i] = item as never;
      return kind === "exp" ? { ...x, experience: list as Resume["experience"] } : { ...x, projects: list as Resume["projects"] };
    });
    toast.success("Bullet replaced. Fill in any [placeholder] with your real figure.");
  };
  const report = score.data;

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_380px]">
      <div className="space-y-4">
        <Card>
          <CardHeader title="Contact" description="Plain text only: ATSs can't read icons or text inside images." />
          <div className="grid gap-3 p-5 pt-3 sm:grid-cols-2">
            <Field label="Full name">
              <Input value={r.name} onChange={(e) => set("name", e.target.value)} />
            </Field>
            <Field label="Email">
              <Input type="email" value={r.email} onChange={(e) => set("email", e.target.value)} />
            </Field>
            <Field label="Phone">
              <Input value={r.phone} onChange={(e) => set("phone", e.target.value)} placeholder="+91 98765 43210" />
            </Field>
            <Field label="City">
              <Input value={r.location} onChange={(e) => set("location", e.target.value)} />
            </Field>
            <Field label="Links" hint="LinkedIn, GitHub, portfolio" className="sm:col-span-2">
              <TagInput value={r.links} onChange={(v) => set("links", v)} placeholder="linkedin.com/in/you, github.com/you" />
            </Field>
          </div>
        </Card>

        <Card>
          <CardHeader title="Summary (optional)" description="The standard layout has none; if you add one, 2-3 lines on who you are, your strongest skills and what you're looking for. Some fields' recruiters skim it first." />
          <div className="p-5 pt-3">
            <Textarea value={r.summary} onChange={(e) => set("summary", e.target.value)} rows={3} />
            <p className="mt-1 text-right text-[12px] text-text-3">{r.summary.split(/\s+/).filter(Boolean).length} words · aim for 25-70</p>
          </div>
        </Card>

        <Card>
          <CardHeader title="Skills" description="Only tools and skills you've really used. Show the important ones in a bullet too." />
          <div className="space-y-3 p-5 pt-3">
            <SkillGroupsField value={r.skill_groups ?? []} onChange={(v) => set("skill_groups", v)} />
            <Field label="All skills" hint="What ATS searches match on. Anything not in a group above prints under “Other”.">
              <TagInput value={r.skills} onChange={(v) => set("skills", v)} placeholder="Python, SQL, Figma…" />
            </Field>
          </div>
        </Card>

        <ItemList
          title="Work Experience"
          description="Internships, freelance, college clubs, part-time work. Prints as “Company, City · dates”, the role in italics, then bullets and the tech line. One bullet per line: action verb, what you did, the result."
          items={r.experience}
          onChange={(v) => set("experience", v)}
          make={() => ({ title: "", organization: "", location: "", start: "", end: "", bullets: [], tech: [] })}
          render={(e, upd) => (
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Role">
                <Input value={e.title} onChange={(ev) => upd({ ...e, title: ev.target.value })} />
              </Field>
              <Field label="Organisation">
                <Input value={e.organization} onChange={(ev) => upd({ ...e, organization: ev.target.value })} />
              </Field>
              <Field label="Location" hint="City, or Remote">
                <Input value={e.location ?? ""} onChange={(ev) => upd({ ...e, location: ev.target.value })} placeholder="Bengaluru" />
              </Field>
              <Field label="Tech used" hint="Printed on its own line under the bullets">
                <TagInput value={e.tech ?? []} onChange={(v) => upd({ ...e, tech: v })} placeholder="Java, AWS" />
              </Field>
              <Field label="Start">
                <Input value={e.start} onChange={(ev) => upd({ ...e, start: ev.target.value })} placeholder="Jun 2025" />
              </Field>
              <Field label="End">
                <Input value={e.end} onChange={(ev) => upd({ ...e, end: ev.target.value })} placeholder="Aug 2025 or Present" />
              </Field>
              <BulletsField value={e.bullets} onChange={(b) => upd({ ...e, bullets: b })} />
            </div>
          )}
        />

        <ItemList
          title="Education"
          items={r.education}
          onChange={(v) => set("education", v)}
          make={() => ({ school: "", degree: "", start: "", end: "", details: "" })}
          render={(e, upd) => (
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Degree">
                <Input value={e.degree} onChange={(ev) => upd({ ...e, degree: ev.target.value })} placeholder="B.Tech, Computer Science" />
              </Field>
              <Field label="College">
                <Input value={e.school} onChange={(ev) => upd({ ...e, school: ev.target.value })} />
              </Field>
              <Field label="Start">
                <Input value={e.start} onChange={(ev) => upd({ ...e, start: ev.target.value })} placeholder="2022" />
              </Field>
              <Field label="End">
                <Input value={e.end} onChange={(ev) => upd({ ...e, end: ev.target.value })} placeholder="2026" />
              </Field>
              <Field label="Details" className="sm:col-span-2" hint="One per line: CGPA, relevant coursework">
                <Textarea value={e.details} rows={2} onChange={(ev) => upd({ ...e, details: ev.target.value })} placeholder={"CGPA: 8.4/10\nRelevant coursework: DBMS, OS, Computer Networks"} />
              </Field>
            </div>
          )}
        />

        <ItemList
          title="Project Work"
          description="Prints as one bullet each: the project name in bold, then what it does and the tech. Put a year in brackets if you like, e.g. “Campus Eats (2025)”."
          items={r.projects}
          onChange={(v) => set("projects", v)}
          make={() => ({ name: "", tech: [], bullets: [] })}
          render={(p, upd) => (
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Project name">
                <Input value={p.name} onChange={(ev) => upd({ ...p, name: ev.target.value })} />
              </Field>
              <Field label="Tech used">
                <TagInput value={p.tech} onChange={(v) => upd({ ...p, tech: v })} placeholder="React, Node.js" />
              </Field>
              <BulletsField value={p.bullets} onChange={(b) => upd({ ...p, bullets: b })} />
            </div>
          )}
        />

        <Card>
          <CardHeader title="Awards and Certificates" description="Certificates, hackathon wins, scholarships, positions of responsibility. One per line." />
          <div className="p-5 pt-3">
            <LinesField value={r.certifications ?? []} onChange={(v) => set("certifications", v)} placeholder={"AWS Certified Cloud Practitioner (2025)\nWinner, Smart India Hackathon 2024"} />
          </div>
        </Card>
      </div>

      <div className="space-y-4 lg:sticky lg:top-4 lg:self-start">
        <Card className="space-y-4 p-5">
          <AtsTarget value={target} onChange={setTarget} />
          {report ? <ScoreHeader r={report} title="Live ATS score" /> : <p className="text-[13px] text-text-3">{target.kind === "match" && !target.matchId ? "Choose a job to score against." : "Scoring…"}</p>}
          {report?.improvements.slice(0, 3).map((i) => (
            <div key={i.title} className="flex items-start justify-between gap-2 text-[13px]">
              <span className="text-text-2">{i.title}</span>
              <Badge tone="success">+{i.gain}</Badge>
            </div>
          ))}
          <div className="flex flex-wrap gap-2 border-t border-border pt-4">
            <Button variant="primary" onClick={() => save.mutate({ resume: r })} loading={save.isPending}>
              <Save /> Save as my resume
            </Button>
            <Button onClick={() => dl("pdf")} loading={busy === "pdf"}>
              <Download /> PDF
            </Button>
            <Button onClick={() => dl("docx")} loading={busy === "docx"}>
              <Download /> Word
            </Button>
          </div>
          <p className="text-[12px] text-text-3">The file uses a single-column ATS-safe layout with standard headings. Saving replaces the resume the agents use to match and tailor.</p>
        </Card>
        {report && (
          <details className="group">
            <summary className="cursor-pointer text-[13px] font-medium text-cobalt-text">Full report and bullet suggestions</summary>
            <div className="mt-3">
              <AtsReportView r={report} onUseBullet={useBullet} jobTitle={target.title} jobDescription={target.description} improve={{ target: targetBody(target), resume: r, onOpenInBuilder: (next) => setR({ ...blank, ...next }) }} />
            </div>
          </details>
        )}
      </div>
    </div>
  );
}

function LinesField({ value, onChange, placeholder }: { value: string[]; onChange: (v: string[]) => void; placeholder?: string }) {
  const [text, setText] = useState(value.join("\n"));
  useEffect(() => {
    if (lines(text).join("\n") !== value.join("\n")) setText(value.join("\n"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  return (
    <Textarea
      value={text}
      rows={Math.max(2, value.length + 1)}
      aria-label="One per line"
      onChange={(e) => {
        setText(e.target.value);
        onChange(lines(e.target.value));
      }}
      placeholder={placeholder}
    />
  );
}

const groupText = (g: SkillGroup[]) => g.map((x) => (x.name ? `${x.name}: ` : "") + x.items.join(", ")).join("\n");
const parseGroups = (t: string): SkillGroup[] =>
  t
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .map((l) => {
      const m = /^([^:]{1,40}):\s*(.*)$/.exec(l);
      const items = (m ? m[2] : l).split(/,|;/).map((x) => x.trim()).filter(Boolean);
      return { name: m ? m[1].trim() : "", items };
    })
    .filter((g) => g.items.length);

function SkillGroupsField({ value, onChange }: { value: SkillGroup[]; onChange: (v: SkillGroup[]) => void }) {
  const [text, setText] = useState(groupText(value));
  useEffect(() => {
    if (groupText(parseGroups(text)) !== groupText(value)) setText(groupText(value));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  return (
    <Field label="Skill groups" hint="One line per group, as it prints: “Languages: Java, Python”">
      <Textarea
        value={text}
        rows={Math.max(2, value.length + 1)}
        onChange={(e) => {
          setText(e.target.value);
          onChange(parseGroups(e.target.value));
        }}
        placeholder={"Languages: Java, Python, SQL\nFrameworks: React, Spring Boot\nTools: Git, Docker, AWS"}
      />
    </Field>
  );
}

function BulletsField({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const [text, setText] = useState(value.join("\n"));
  useEffect(() => {
    if (lines(text).join("\n") !== value.join("\n")) setText(value.join("\n"));
    // Sync only when the bullets change from outside (an AI suggestion was used).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  return (
    <Field label="Bullets" hint="One per line" className="sm:col-span-2">
      <Textarea
        value={text}
        rows={Math.max(3, value.length + 1)}
        onChange={(e) => {
          setText(e.target.value);
          onChange(lines(e.target.value));
        }}
        placeholder={"Built …, used by [N] students\nReduced … by [X]% by …"}
      />
    </Field>
  );
}

function ItemList<T>({ title, description, items, onChange, make, render }: { title: string; description?: string; items: T[]; onChange: (v: T[]) => void; make: () => T; render: (item: T, update: (v: T) => void) => React.ReactNode }) {
  return (
    <Card>
      <CardHeader
        title={title}
        description={description}
        action={
          <Button size="sm" variant="ghost" onClick={() => onChange([...items, make()])}>
            <Plus /> Add
          </Button>
        }
      />
      <div className="space-y-4 p-5 pt-3">
        {!items.length && <p className="text-[13px] text-text-3">Nothing here yet.</p>}
        {items.map((it, i) => (
          <div key={i} className="relative rounded-[var(--radius-card)] border border-border p-4">
            <Button size="icon" variant="ghost" className="absolute top-2 right-2 size-8" aria-label={`Remove ${title.toLowerCase()} ${i + 1}`} onClick={() => onChange(items.filter((_, k) => k !== i))}>
              <Trash2 className="size-4" />
            </Button>
            {render(it, (v) => onChange(items.map((x, k) => (k === i ? v : x))))}
          </div>
        ))}
      </div>
    </Card>
  );
}

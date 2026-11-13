"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { useStaffMe } from "@/components/campus/portal";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/input";
import { api } from "@/lib/api";

type Degree = { id: string; name: string; abbreviation: string; isced_level: number; typical_years: number | null; custom: boolean };
type Setup = {
  degrees: Degree[];
  departments: { id: string; name: string }[];
  programs: { id: string; department_id: string; degree_id: string; field_code: string | null; specialisation: string; intake_per_year: number | null }[];
  batches: { id: string; program_id: string; admission_year: number; graduation_year: number }[];
  fields: { code: string; level: string; name: string }[];
  custom_fields: { key: string; label: string; type: string }[];
};
type CapNode = { level: string; id: string; capacity: number | null; used: number; remaining: number | null; children?: CapNode[]; department_id?: string };
const LEVEL = { 3: "Upper secondary", 4: "Post-secondary", 5: "Diploma", 6: "Bachelor's", 7: "Master's", 8: "Doctoral" } as Record<number, string>;
const sel = "h-10 w-full rounded-[var(--radius-control)] border border-border bg-surface px-3 text-[13px]";

/** College setup: settings and grading scale → degrees offered → departments → programmes → batches → capacity. */
export default function SetupPage() {
  const qc = useQueryClient();
  const { data: s } = useQuery({ queryKey: ["campus-setup"], queryFn: () => api.get<Setup>("/campus/staff/setup") });
  const refresh = () => (qc.invalidateQueries({ queryKey: ["campus-setup"] }), qc.invalidateQueries({ queryKey: ["campus-cap"] }), qc.invalidateQueries({ queryKey: ["campus-staff-me"] }));
  const post = useMutation({ mutationFn: ({ url, body }: { url: string; body: unknown }) => api.post(url, body), onSuccess: refresh, onError: (e: Error) => toast.error(e.message) });
  if (!s) return null;
  const deg = (id: string) => s.degrees.find((d) => d.id === id);
  return (
    <div className="space-y-6">
      <Settings onSaved={refresh} />
      <Degrees offered={s.degrees} onSaved={refresh} />
      <Card>
        <CardHeader title="3 · Departments" description="Each department can run several degrees, and a degree can span departments." />
        <div className="space-y-3 p-5">
          <div className="flex flex-wrap gap-1.5">{s.departments.map((d) => <Badge key={d.id}>{d.name}</Badge>)}</div>
          <form onSubmit={(e: FormEvent<HTMLFormElement>) => { e.preventDefault(); const f = new FormData(e.currentTarget); post.mutate({ url: "/campus/staff/departments", body: { name: f.get("name") } }); e.currentTarget.reset(); }} className="flex gap-2">
            <Input name="name" required minLength={2} placeholder="e.g. Commerce, Nursing, Computer Engineering, Kathak" aria-label="Department name" />
            <Button type="submit"><Plus /> Add</Button>
          </form>
        </div>
      </Card>
      <Card>
        <CardHeader title="4 · Programmes and batches" description="A programme is a department running a degree, in a field (ISCED), with a yearly intake. Students belong to programmes and batches." />
        <div className="space-y-4 p-5">
          <form
            onSubmit={(e: FormEvent<HTMLFormElement>) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              post.mutate({ url: "/campus/staff/programs", body: { department_id: f.get("department_id"), degree_id: f.get("degree_id"), field_code: f.get("field_code") || null, specialisation: f.get("specialisation"), intake_per_year: f.get("intake") ? Number(f.get("intake")) : null } });
            }}
            className="grid gap-2 sm:grid-cols-5"
          >
            <select name="department_id" required className={sel} aria-label="Department"><option value="">Department</option>{s.departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</select>
            <select name="degree_id" required className={sel} aria-label="Degree"><option value="">Degree</option>{s.degrees.map((d) => <option key={d.id} value={d.id}>{d.abbreviation}</option>)}</select>
            <select name="field_code" className={sel} aria-label="Field"><option value="">Field (ISCED)</option>{s.fields.filter((f) => f.level === "detailed").map((f) => <option key={f.code} value={f.code}>{f.code} · {f.name}</option>)}</select>
            <Input name="specialisation" placeholder="Specialisation (optional)" aria-label="Specialisation" />
            <div className="flex gap-2"><Input name="intake" type="number" min={0} placeholder="Intake / year" aria-label="Intake per year" /><Button type="submit"><Plus /></Button></div>
          </form>
          <div className="space-y-2">
            {s.programs.map((p) => (
              <div key={p.id} className="flex flex-wrap items-center gap-2 rounded-[var(--radius-card)] border border-border px-3 py-2 text-[13.5px]">
                <span className="flex-1">{s.departments.find((d) => d.id === p.department_id)?.name} · {deg(p.degree_id)?.abbreviation} {p.specialisation} {p.field_code && <span className="text-text-3">({p.field_code})</span>}</span>
                <span className="text-[12px] text-text-3">{s.batches.filter((b) => b.program_id === p.id).map((b) => b.admission_year).join(", ") || "no batches"}</span>
                <form onSubmit={(e: FormEvent<HTMLFormElement>) => { e.preventDefault(); const f = new FormData(e.currentTarget); post.mutate({ url: "/campus/staff/batches", body: { program_id: p.id, admission_year: Number(f.get("year")) } }); }} className="flex gap-1">
                  <Input name="year" type="number" min={1950} max={2100} placeholder="Admission year" className="w-36" aria-label="Admission year" />
                  <Button type="submit" size="sm">Add batch</Button>
                </form>
              </div>
            ))}
          </div>
        </div>
      </Card>
      <Capacity setup={s} />
    </div>
  );
}

function Settings({ onSaved }: { onSaved: () => void }) {
  const { data: me } = useStaffMe();
  const save = useMutation({ mutationFn: (b: unknown) => api.put("/campus/staff/settings", b), onSuccess: () => (toast.success("Saved"), onSaved()), onError: (e: Error) => toast.error(e.message) });
  if (!me) return null;
  const c = me.campus;
  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const type = String(f.get("scale_type"));
    save.mutate({
      allowed_email_domains: String(f.get("domains") || "").split(",").map((d) => d.trim()).filter(Boolean),
      student_id_label: f.get("id_label"),
      pending_subjects_label: f.get("pending_label"),
      term_type: f.get("term_type"),
      score_scale: { type, max: f.get("scale_max") ? Number(f.get("scale_max")) : null },
    });
  };
  return (
    <Card>
      <CardHeader title="1 · Your college" description="Labels and the grading scale exactly as your college uses them. Scores are never converted between scales." />
      <form onSubmit={submit} className="grid gap-3 p-5 sm:grid-cols-2 lg:grid-cols-3">
        <Field label="Staff email domains" hint="Staff must confirm an address on one of these"><Input name="domains" defaultValue={c.allowed_email_domains.join(", ")} placeholder="college.edu.in, ac.in" /></Field>
        <Field label="Student ID is called"><Input name="id_label" defaultValue={c.student_id_label} placeholder="Roll no., Enrollment no., PRN, USN" /></Field>
        <Field label="Pending / failed subjects are called" hint="Leave empty if your system has none"><Input name="pending_label" defaultValue={c.pending_subjects_label ?? ""} placeholder="Backlog, ATKT, KT, arrears, resit…" /></Field>
        <Field label="Grading scale">
          <select name="scale_type" defaultValue={c.score_scale?.type ?? "cgpa"} className={sel}>
            {["cgpa", "gpa", "percentage", "division", "letter", "pass_fail"].map((t) => <option key={t} value={t}>{t.replace("_", "/")}</option>)}
          </select>
        </Field>
        <Field label="Scale maximum" hint="e.g. 10, 4, 7 or 100"><Input name="scale_max" type="number" step="any" defaultValue={c.score_scale?.max ?? ""} /></Field>
        <Field label="Terms"><select name="term_type" defaultValue={c.term_type} className={sel}>{["annual", "semester", "trimester", "modular"].map((t) => <option key={t} value={t}>{t}</option>)}</select></Field>
        <div className="sm:col-span-2 lg:col-span-3"><Button type="submit" variant="primary" loading={save.isPending}>Save</Button></div>
      </form>
    </Card>
  );
}

function Degrees({ offered, onSaved }: { offered: Degree[]; onSaved: () => void }) {
  const [q, setQ] = useState("");
  const found = useQuery({ queryKey: ["degree-search", q], queryFn: () => api.get<Degree[]>(`/campus/staff/degrees?q=${encodeURIComponent(q)}`), enabled: q.trim().length >= 1 });
  const ids = offered.map((d) => d.id);
  const set = useMutation({ mutationFn: (degree_ids: string[]) => api.put("/campus/staff/degrees/offered", { degree_ids }), onSuccess: onSaved, onError: (e: Error) => toast.error(e.message) });
  const add = useMutation({ mutationFn: (b: unknown) => api.post("/campus/staff/degrees", b), onSuccess: onSaved, onError: (e: Error) => toast.error(e.message) });
  return (
    <Card>
      <CardHeader title="2 · Degrees you offer" description="From AISHE's 201 programmes and common international degrees. Add any that's missing." />
      <div className="space-y-3 p-5">
        <div className="flex flex-wrap gap-1.5">
          {offered.map((d) => (
            <button key={d.id} type="button" onClick={() => set.mutate(ids.filter((x) => x !== d.id))} title="Remove" className="rounded-full border border-[var(--cobalt)] px-2.5 py-1 text-[12.5px] text-cobalt-text">
              {d.abbreviation} · {LEVEL[d.isced_level]} ×
            </button>
          ))}
        </div>
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search: B.Com., MBBS, LL.B., B.Sc.(Nursing), B.Des., Ph.D., MBA…" aria-label="Search degrees" />
        <div className="flex flex-wrap gap-1.5">
          {found.data?.filter((d) => !ids.includes(d.id)).slice(0, 24).map((d) => (
            <button key={d.id} type="button" onClick={() => set.mutate([...ids, d.id])} className="rounded-full border border-border px-2.5 py-1 text-[12.5px] text-text-2 hover:text-text">
              + {d.abbreviation} <span className="text-text-3">{d.name !== d.abbreviation ? d.name : ""}</span>
            </button>
          ))}
        </div>
        <form onSubmit={(e: FormEvent<HTMLFormElement>) => { e.preventDefault(); const f = new FormData(e.currentTarget); add.mutate({ name: f.get("name"), abbreviation: f.get("abbr"), isced_level: Number(f.get("level")) }); }} className="grid gap-2 sm:grid-cols-[2fr_1fr_1fr_auto]">
          <Input name="name" required placeholder="A degree that's missing (full name)" aria-label="Degree name" />
          <Input name="abbr" required placeholder="Abbreviation" aria-label="Abbreviation" />
          <select name="level" className={sel} aria-label="Level">{Object.entries(LEVEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
          <Button type="submit">Add</Button>
        </form>
      </div>
    </Card>
  );
}

function Capacity({ setup }: { setup: Setup }) {
  const qc = useQueryClient();
  const { data: tree } = useQuery({ queryKey: ["campus-cap"], queryFn: () => api.get<CapNode & { departments: CapNode[] }>("/campus/staff/capacity") });
  const save = useMutation({
    mutationFn: (b: { level: string; ref_id?: string; capacity: number }) => api.put("/campus/staff/capacity", b),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["campus-cap"] }),
    onError: (e: Error & { detail?: unknown }) => toast.error(e.message),
  });
  const split = useMutation({
    mutationFn: (q: string) => api.post(`/campus/staff/capacity/split?${q}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["campus-cap"] }),
    onError: (e: Error) => toast.error(e.message),
  });
  if (!tree) return null;
  const name = (n: CapNode) =>
    n.level === "campus" ? "Whole college" : n.level === "degree" ? setup.degrees.find((d) => d.id === n.id)?.abbreviation : n.level === "department" ? setup.departments.find((d) => d.id === n.id)?.name
      : n.level === "program" ? `${setup.departments.find((d) => d.id === n.department_id)?.name ?? ""} programme` : setup.batches.find((b) => b.id === n.id)?.admission_year;
  const row = (n: CapNode, depth: number) => (
    <div key={`${n.level}:${n.id}`}>
      <div className="flex flex-wrap items-center gap-2 py-1.5" style={{ paddingLeft: depth * 18 }}>
        <span className="min-w-40 flex-1 text-[13.5px]">{name(n)} <span className="text-[11.5px] text-text-3 uppercase">{n.level}</span></span>
        <span className="num text-[12.5px] text-text-2">{n.used.toLocaleString("en-IN")} used{n.remaining != null && ` · ${n.remaining.toLocaleString("en-IN")} left`}</span>
        <Input
          type="number"
          min={0}
          max={4000000}
          defaultValue={n.capacity ?? ""}
          placeholder="Capacity"
          className="w-28"
          aria-label={`Capacity for ${name(n)}`}
          onBlur={(e) => e.target.value !== String(n.capacity ?? "") && e.target.value && save.mutate({ level: n.level, ref_id: n.level === "campus" ? undefined : n.id, capacity: Number(e.target.value) })}
        />
        {n.level === "campus" && <Button size="sm" variant="ghost" onClick={() => split.mutate("level=degree&mode=even")}>Split evenly</Button>}
        {n.level === "degree" && <Button size="sm" variant="ghost" onClick={() => split.mutate(`level=program&mode=intake&parent_id=${n.id}`)}>Use intake numbers</Button>}
        {n.level === "program" && <Button size="sm" variant="ghost" onClick={() => split.mutate(`level=batch&mode=even&parent_id=${n.id}`)}>Split evenly</Button>}
      </div>
      {n.children?.map((c) => row(c, depth + 1))}
    </div>
  );
  return (
    <Card>
      <CardHeader title="5 · Seat capacity" description="Total → degree → programme → batch (departments too). A level never exceeds its parent; when it's full, new students wait on a list and you're told. Plan limits are only for billing." />
      <div className="p-5">
        {row(tree, 0)}
        {!!tree.departments.length && <div className="mt-3 border-t border-border pt-3">{tree.departments.map((d) => row(d, 1))}</div>}
      </div>
    </Card>
  );
}

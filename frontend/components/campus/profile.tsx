"use client";

/**
 * Campus profile (student app): join your college (claim the college's record with your college email, or pick your
 * programme for staff to confirm), see your college record (read-only: it comes from the college), and add exactly
 * three kinds of entries: internships, roles and awards. Each is Self-reported until your department verifies it.
 * Mobile-first: one column on phones, cards with large tap targets.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Award, BadgeCheck, Briefcase, CircleAlert, FileUp, GraduationCap, Pencil, Plus, Trash2, Users } from "lucide-react";
import Link from "next/link";
import { useState, type FormEvent, type ReactNode } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Field, Input, Textarea } from "@/components/ui/input";
import { api } from "@/lib/api";

type Kind = "internship" | "role" | "award";
export type Entry = {
  id: string;
  campus_id: string;
  kind: Kind;
  sub_type: string;
  category: string;
  title: string;
  organisation: string;
  level: string | null;
  position: string | null;
  mode: string | null;
  start_date: string | null;
  end_date: string | null;
  ongoing: boolean;
  description: string;
  link: string | null;
  status: "self_reported" | "verified" | "rejected";
  label: string;
  reject_reason: string | null;
  verifier_flags: string[];
  proof_url: string | null;
  has_proof: boolean;
  show_on_proof_page: boolean;
  stipend_inr: number | null;
  stipend_private: boolean;
};
type Overview = {
  membership: null | { campus: string; status: string; department: string | null; program: string | null; batch: string | null; locked: boolean; labels: { student_id: string; pending_subjects: string | null } };
  record: null | { student_id: string; name: string; score: number | null; score_scale: { type: string; max?: number } | null; pending_subjects: number | null; graduation_year: number | null; current_term: number | null; from: string };
  achievements: Entry[];
  shares_with_college: boolean;
  sharing_note: string;
};

const KINDS: { kind: Kind; title: string; icon: ReactNode; blurb: string }[] = [
  { kind: "internship", title: "Internships", icon: <Briefcase className="size-4" />, blurb: "Internships, apprenticeships, articleship, clinical postings, moot or law-firm internships, teaching practice, field work, industrial training." },
  { kind: "role", title: "Roles", icon: <Users className="size-4" />, blurb: "Positions of responsibility: clubs, societies, sports teams, committees, NSS / NCC, student council, organising teams." },
  { kind: "award", title: "Awards", icon: <Award className="size-4" />, blurb: "Wins and recognitions: hackathons, moot courts, case competitions, sports, cultural fests, olympiads, papers, scholarships." },
];
const SUB_TYPES = ["internship", "apprenticeship", "articleship", "clinical_posting", "rotation", "house_job", "residency", "moot_or_law_firm", "teaching_practice", "field_work", "practicum", "industrial_training", "research_internship"];
const CATEGORIES = ["hackathon", "moot_court", "case_competition", "sports", "cultural", "debate", "olympiad", "paper_or_poster", "art_exhibition", "music_or_dance", "quiz", "scholarship", "fellowship", "other"];
const LEVELS = ["college", "inter_college", "state", "national", "international"];
const POSITIONS = ["winner", "runner_up", "finalist", "participant"];
const human = (s: string) => s.replaceAll("_", " ").replace(/^\w/, (c) => c.toUpperCase());

const select = "h-11 w-full rounded-[var(--radius-control)] border border-border bg-surface px-3 text-[14px] text-text md:h-10";

export function CampusProfile() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["campus-profile"], queryFn: () => api.get<Overview>("/campus-profile") });
  const refresh = () => qc.invalidateQueries({ queryKey: ["campus-profile"] });
  if (!data) return null;
  return (
    <div className="space-y-6">
      {data.membership ? <College o={data} /> : <JoinCollege onDone={refresh} />}
      <p className="flex items-start gap-2 rounded-[var(--radius-card)] border border-border bg-surface-2/50 px-4 py-3 text-[13px] text-text-2">
        <CircleAlert className="mt-0.5 size-4 shrink-0" />
        <span>
          {data.sharing_note}{" "}
          <Link href="/settings#privacy" className="font-medium text-cobalt-text hover:underline">
            {data.shares_with_college ? "You're sharing now" : "You're not sharing now"}
          </Link>
        </span>
      </p>
      {data.membership && (
        <div className="grid gap-4 lg:grid-cols-3">
          {KINDS.map((k) => (
            <Entries key={k.kind} spec={k} entries={data.achievements.filter((a) => a.kind === k.kind)} onChange={refresh} />
          ))}
        </div>
      )}
    </div>
  );
}

function College({ o }: { o: Overview }) {
  const m = o.membership!;
  const r = o.record;
  const scale = r?.score_scale;
  return (
    <Card>
      <CardHeader icon={<GraduationCap className="size-4" />} title={m.campus} description={[m.department, m.program, m.batch].filter(Boolean).join(" · ") || "Programme not set yet"} />
      <div className="space-y-3 p-5 text-[13.5px]">
        {m.status !== "active" && (
          <Badge tone="warning">{m.status === "waitlisted" ? "On the waitlist: your college has been told" : "Waiting for your department to confirm your programme"}</Badge>
        )}
        {r ? (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
            <div><dt className="text-[12px] text-text-3">{m.labels.student_id}</dt><dd>{r.student_id}</dd></div>
            {r.score != null && <div><dt className="text-[12px] text-text-3">Score</dt><dd>{r.score}{scale?.max ? ` / ${scale.max}` : ""} {scale?.type && <span className="text-text-3">({scale.type})</span>}</dd></div>}
            {m.labels.pending_subjects && r.pending_subjects != null && <div><dt className="text-[12px] text-text-3">{m.labels.pending_subjects}</dt><dd>{r.pending_subjects}</dd></div>}
            {r.graduation_year && <div><dt className="text-[12px] text-text-3">Graduating</dt><dd>{r.graduation_year}</dd></div>}
          </dl>
        ) : null}
        <p className="text-[12px] text-text-3">{r ? `These come from ${r.from} and can't be changed here. Ask your department if something is wrong.` : "Your academic record appears here once your college adds it."}</p>
      </div>
    </Card>
  );
}

function JoinCollege({ onDone }: { onDone: () => void }) {
  const [q, setQ] = useState("");
  const [campus, setCampus] = useState<{ id: string; name: string } | null>(null);
  const [mode, setMode] = useState<"claim" | "pick">("claim");
  const colleges = useQuery({ queryKey: ["cp-colleges", q], queryFn: () => api.get<{ id: string; name: string; city: string; state: string }[]>(`/campus-profile/colleges?q=${encodeURIComponent(q)}`), enabled: q.trim().length >= 2 && !campus });
  return (
    <Card>
      <CardHeader icon={<GraduationCap className="size-4" />} title="Join your college" description="Find your college. Your programme and academics come from the college, so nobody can put themselves in the wrong department." />
      <div className="space-y-4 p-5">
        {!campus ? (
          <>
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search your college by name" aria-label="College" />
            <ul className="space-y-1">
              {colleges.data?.map((c) => (
                <li key={c.id}>
                  <button type="button" onClick={() => setCampus(c)} className="w-full rounded-[var(--radius-control)] px-3 py-2.5 text-left text-[14px] hover:bg-elevated">
                    {c.name} <span className="text-text-3">{[c.city, c.state].filter(Boolean).join(", ")}</span>
                  </button>
                </li>
              ))}
              {q.trim().length >= 2 && colleges.data?.length === 0 && <li className="px-3 text-[13px] text-text-3">Not on JobPilot yet. Ask your placement cell to set it up.</li>}
            </ul>
          </>
        ) : (
          <>
            <div className="flex items-center justify-between text-[14px] font-medium">
              {campus.name}
              <Button size="sm" variant="ghost" onClick={() => setCampus(null)}>Change</Button>
            </div>
            <div className="flex gap-2">
              <Button size="sm" variant={mode === "claim" ? "primary" : "secondary"} onClick={() => setMode("claim")}>I have a college email</Button>
              <Button size="sm" variant={mode === "pick" ? "primary" : "secondary"} onClick={() => setMode("pick")}>Pick my programme</Button>
            </div>
            {mode === "claim" ? <Claim campusId={campus.id} onDone={onDone} /> : <Pick campusId={campus.id} onDone={onDone} />}
          </>
        )}
      </div>
    </Card>
  );
}

function Claim({ campusId, onDone }: { campusId: string; onDone: () => void }) {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [otp, setOtp] = useState("");
  const start = useMutation({ mutationFn: () => api.post("/campus-profile/claim/start", { campus_id: campusId, college_email: email }), onSuccess: () => setSent(true), onError: (e: Error) => toast.error(e.message) });
  const verify = useMutation({ mutationFn: () => api.post<{ status: string }>("/campus-profile/claim/verify", { otp }), onSuccess: () => (toast.success("Linked to your college's record"), onDone()), onError: (e: Error) => toast.error(e.message) });
  return !sent ? (
    <form onSubmit={(e) => (e.preventDefault(), start.mutate())} className="flex flex-col gap-2 sm:flex-row">
      <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@college email" aria-label="College email" />
      <Button type="submit" loading={start.isPending} disabled={!email.includes("@")}>Send code</Button>
    </form>
  ) : (
    <form onSubmit={(e) => (e.preventDefault(), verify.mutate())} className="space-y-2">
      <p className="text-[13px] text-text-2">If your college added this address, a 6-digit code is on its way.</p>
      <div className="flex gap-2">
        <Input inputMode="numeric" maxLength={6} value={otp} onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))} placeholder="6-digit code" aria-label="Code" />
        <Button type="submit" variant="primary" loading={verify.isPending} disabled={otp.length !== 6}>Confirm</Button>
      </div>
    </form>
  );
}

function Pick({ campusId, onDone }: { campusId: string; onDone: () => void }) {
  const programs = useQuery({ queryKey: ["cp-programs", campusId], queryFn: () => api.get<{ id: string; name: string; department: string }[]>(`/campus-profile/colleges/${campusId}/programs`) });
  const [program, setProgram] = useState("");
  const [year, setYear] = useState(String(new Date().getFullYear()));
  const join = useMutation({ mutationFn: () => api.post("/campus-profile/join", { campus_id: campusId, program_id: program, admission_year: Number(year) }), onSuccess: () => (toast.success("Sent to your department to confirm"), onDone()), onError: (e: Error) => toast.error(e.message) });
  return (
    <form onSubmit={(e) => (e.preventDefault(), join.mutate())} className="grid gap-3 sm:grid-cols-[2fr_1fr_auto]">
      <select value={program} onChange={(e) => setProgram(e.target.value)} className={select} aria-label="Programme">
        <option value="">Your department and programme</option>
        {programs.data?.map((p) => <option key={p.id} value={p.id}>{p.department} · {p.name}</option>)}
      </select>
      <Input type="number" value={year} onChange={(e) => setYear(e.target.value)} min={1990} max={2100} aria-label="Admission year" />
      <Button type="submit" loading={join.isPending} disabled={!program}>Request</Button>
    </form>
  );
}

function statusTone(s: Entry["status"]) {
  return s === "verified" ? "success" : s === "rejected" ? "danger" : "neutral";
}

function Entries({ spec, entries, onChange }: { spec: (typeof KINDS)[number]; entries: Entry[]; onChange: () => void }) {
  const [editing, setEditing] = useState<Entry | "new" | null>(null);
  return (
    <Card>
      <CardHeader
        icon={spec.icon}
        title={spec.title}
        description={spec.blurb}
        action={
          <Button size="sm" onClick={() => setEditing("new")} aria-label={`Add ${spec.kind}`}>
            <Plus /> Add
          </Button>
        }
      />
      <div className="space-y-3 p-4">
        {editing && <EntryForm kind={spec.kind} entry={editing === "new" ? null : editing} onDone={() => (setEditing(null), onChange())} />}
        {!entries.length && !editing && <p className="text-[13px] text-text-3">Nothing yet.</p>}
        {entries.map((e) => (
          <EntryCard key={e.id} e={e} onEdit={() => setEditing(e)} onChange={onChange} />
        ))}
      </div>
    </Card>
  );
}

function EntryCard({ e, onEdit, onChange }: { e: Entry; onEdit: () => void; onChange: () => void }) {
  const del = useMutation({ mutationFn: () => api.del(`/campus-profile/achievements/${e.campus_id}/${e.id}`), onSuccess: onChange, onError: (x: Error) => toast.error(x.message) });
  const upload = useMutation({
    mutationFn: (f: File) => {
      const fd = new FormData();
      fd.set("file", f);
      return api.post<{ warning: string | null }>(`/campus-profile/achievements/${e.campus_id}/${e.id}/proof`, fd);
    },
    onSuccess: (r) => (r.warning ? toast.warning(r.warning, { duration: 15000 }) : toast.success("Proof added"), onChange()),
    onError: (x: Error) => toast.error(x.message),
  });
  return (
    <div className="rounded-[var(--radius-card)] border border-border p-3.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[14px] font-medium">{e.title}</div>
          <div className="text-[12.5px] text-text-2">
            {[e.organisation, e.kind === "award" ? [e.level && human(e.level), e.position && human(e.position)].filter(Boolean).join(", ") : e.sub_type && human(e.sub_type)].filter(Boolean).join(" · ")}
          </div>
          <div className="text-[12px] text-text-3">{[e.start_date, e.ongoing ? "ongoing" : e.end_date].filter(Boolean).join(" – ")}</div>
        </div>
        <Badge tone={statusTone(e.status)}>{e.status === "verified" && <BadgeCheck className="size-3" />} {e.label}</Badge>
      </div>
      {e.status === "rejected" && e.reject_reason && <p className="mt-2 text-[12.5px] text-[var(--error)]">Why: {e.reject_reason}</p>}
      {!!e.verifier_flags.length && (
        <p className="mt-2 rounded-[var(--radius-control)] border border-[color-mix(in_oklab,var(--error)_35%,transparent)] px-2.5 py-1.5 text-[12px] text-[var(--error)]">
          Check this offer: {e.verifier_flags.join("; ")}. If anyone asked you to pay, don’t. Report it at cybercrime.gov.in or call 1930.
        </p>
      )}
      <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
        <Button size="sm" variant="ghost" onClick={onEdit}><Pencil /> Edit</Button>
        <label className="inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-[var(--radius-control)] px-3 text-[13px] text-text-2 hover:bg-elevated">
          <FileUp className="size-4" /> {e.has_proof ? "Replace proof" : "Add proof"}
          <input type="file" accept="application/pdf,image/jpeg,image/png" className="sr-only" onChange={(x) => x.target.files?.[0] && upload.mutate(x.target.files[0])} />
        </label>
        {e.proof_url && <a href={e.proof_url} target="_blank" rel="noreferrer" className="text-[12.5px] text-cobalt-text hover:underline">View proof</a>}
        <Button size="sm" variant="ghost" className="ml-auto" onClick={() => confirm("Delete this entry?") && del.mutate()} aria-label="Delete"><Trash2 /></Button>
      </div>
      {e.status === "verified" && <p className="mt-1 text-[12px] text-text-3">Editing a verified entry sends it back for verification.</p>}
    </div>
  );
}

function EntryForm({ kind, entry, onDone }: { kind: Kind; entry: Entry | null; onDone: () => void }) {
  const [ongoing, setOngoing] = useState(entry?.ongoing ?? false);
  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => (entry ? api.put(`/campus-profile/achievements/${entry.campus_id}/${entry.id}`, body) : api.post("/campus-profile/achievements", body)),
    onSuccess: () => (toast.success(entry ? "Saved" : "Added: it's Self-reported until your department verifies it"), onDone()),
    onError: (e: Error) => toast.error(e.message),
  });
  const submit = (ev: FormEvent<HTMLFormElement>) => {
    ev.preventDefault();
    const fd = new FormData(ev.currentTarget);
    const v = (k: string) => String(fd.get(k) ?? "").trim();
    const body: Record<string, unknown> = { kind, title: v("title"), organisation: v("organisation"), start_date: v("start_date") || null, ongoing, description: v("description"), show_on_proof_page: fd.get("show_on_proof_page") === "on" };
    if (!ongoing && v("end_date")) body.end_date = v("end_date");
    if (v("link")) body.link = v("link");
    if (kind === "internship") Object.assign(body, { sub_type: v("sub_type") || "internship", mode: v("mode") || "onsite", ...(v("stipend_inr") ? { stipend_inr: Number(v("stipend_inr")) } : {}), stipend_private: fd.get("stipend_private") === "on" });
    if (kind === "award") Object.assign(body, { category: v("category") || "other", level: v("level"), position: v("position") });
    save.mutate(body);
  };
  const today = new Date().toISOString().slice(0, 10);
  return (
    <form onSubmit={submit} className="space-y-3 rounded-[var(--radius-card)] border border-border bg-surface-2/40 p-3.5">
      <Field label={kind === "internship" ? "Role / title" : kind === "role" ? "Position" : "Event name"}><Input name="title" required minLength={2} maxLength={200} defaultValue={entry?.title} /></Field>
      <Field label={kind === "internship" ? "Company / hospital / firm" : kind === "role" ? "Organisation (club, committee, NSS...)" : "Organiser"}>
        <Input name="organisation" required={kind !== "award"} maxLength={200} defaultValue={entry?.organisation} />
      </Field>
      {kind === "internship" && (
        <div className="grid grid-cols-2 gap-2">
          <Field label="Type">
            <select name="sub_type" defaultValue={entry?.sub_type || "internship"} className={select}>{SUB_TYPES.map((s) => <option key={s} value={s}>{human(s)}</option>)}</select>
          </Field>
          <Field label="Mode">
            <select name="mode" defaultValue={entry?.mode || "onsite"} className={select}>{["onsite", "remote", "hybrid"].map((s) => <option key={s} value={s}>{human(s)}</option>)}</select>
          </Field>
        </div>
      )}
      {kind === "award" && (
        <div className="grid grid-cols-3 gap-2">
          <Field label="Category"><select name="category" defaultValue={entry?.category || "other"} className={select}>{CATEGORIES.map((s) => <option key={s} value={s}>{human(s)}</option>)}</select></Field>
          <Field label="Level"><select name="level" required defaultValue={entry?.level || "college"} className={select}>{LEVELS.map((s) => <option key={s} value={s}>{human(s)}</option>)}</select></Field>
          <Field label="Position"><select name="position" required defaultValue={entry?.position || "participant"} className={select}>{POSITIONS.map((s) => <option key={s} value={s}>{human(s)}</option>)}</select></Field>
        </div>
      )}
      <div className="grid grid-cols-2 gap-2">
        <Field label={kind === "award" ? "Date" : "Start"}><Input name="start_date" type="date" required max={today} defaultValue={entry?.start_date ?? ""} /></Field>
        {kind !== "award" && <Field label="End"><Input name="end_date" type="date" max={today} disabled={ongoing} defaultValue={entry?.end_date ?? ""} /></Field>}
      </div>
      {kind !== "award" && (
        <label className="flex items-center gap-2 text-[13px]"><input type="checkbox" checked={ongoing} onChange={(e) => setOngoing(e.target.checked)} /> Ongoing</label>
      )}
      {kind === "internship" && (
        <div className="grid grid-cols-2 items-end gap-2">
          <Field label="Stipend (₹ / month, optional)"><Input name="stipend_inr" type="number" min={0} defaultValue={entry?.stipend_inr ?? ""} /></Field>
          <label className="flex items-center gap-2 pb-2.5 text-[13px]"><input type="checkbox" name="stipend_private" defaultChecked={entry?.stipend_private ?? true} /> Keep stipend private</label>
        </div>
      )}
      <Field label="Description (plain text)"><Textarea name="description" rows={3} maxLength={2000} defaultValue={entry?.description} /></Field>
      <Field label="Link (optional)"><Input name="link" type="url" placeholder="https://" defaultValue={entry?.link ?? ""} /></Field>
      <label className="flex items-center gap-2 text-[13px]"><input type="checkbox" name="show_on_proof_page" defaultChecked={entry?.show_on_proof_page} /> Once verified, show it on my public Proof page as “Verified by my college”</label>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onDone}>Cancel</Button>
        <Button type="submit" variant="primary" loading={save.isPending}>Save</Button>
      </div>
    </form>
  );
}

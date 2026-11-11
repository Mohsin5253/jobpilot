"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronDown, ChevronUp, KeyRound, Plus, RefreshCw, ShieldCheck, Sparkles, Trash2, UserPlus, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Field, Input, Textarea } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/misc";
import { api } from "@/lib/api";
import { ago, cn } from "@/lib/utils";

export type StaffMe = { college: string; role: "tpo" | "hod" | "teacher"; label: string; department: string; permissions: string[]; domain: string | null; staff_code_set: boolean; staff_code_set_at: string | null };
type Requirement = { text: string; kind: "must" | "nice"; status: "met" | "partial" | "missing"; evidence: string };
export type Placement = {
  id: string;
  student: string | null;
  company: string;
  title: string;
  stage: string;
  stage_label: string;
  source: string;
  match_score: number | null;
  reasoning: { strengths?: string[]; gaps?: string[]; requirements?: Requirement[]; explanation?: string; guardrails?: string[]; semantic?: number; skills?: number; llm?: number | null };
  feedback: string;
  history: { stage: string; at: string; by: string; note: string }[];
  updated_at: string | null;
};
type Pipeline = { stages: { key: string; label: string; count: number }[]; items: Placement[]; precision: { k: number; precision: number | null; decided: number; approved: number } };
type StudentRow = {
  user_id: string;
  name: string;
  email: string;
  branch: string;
  grad_year: number | null;
  cgpa: number | null;
  matches: number;
  applied: number;
  interviews: number;
  offers: number;
  furthest: string | null;
  furthest_label: string;
  pipeline: Placement[];
  last_active: string | null;
};

const MOVES: { key: string; label: string }[] = [
  { key: "round_1", label: "Round 1" },
  { key: "technical", label: "Technical" },
  { key: "hr", label: "HR" },
  { key: "placed", label: "Placed" },
  { key: "rejected", label: "Rejected" },
];
const STAGE_TONE: Record<string, "success" | "accent" | "warning" | "danger" | "outline"> = {
  proposed: "warning", shortlisted: "accent", round_1: "accent", technical: "accent", hr: "accent", placed: "success", rejected: "danger", dismissed: "outline", withdrawn: "outline",
};

export const useStaffMe = () => useQuery({ queryKey: ["college", "me"], queryFn: () => api.get<StaffMe>("/college/me"), retry: false });

function useRefresh() {
  const qc = useQueryClient();
  return () => ["college", "college-pipeline", "college-students", "college-staff", "college-jobs"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
}

/** Not staff yet: HODs and faculty join with the college's staff code. */
export function StaffJoin() {
  const [f, setF] = useState({ code: "", role: "hod" as "hod" | "teacher", department: "" });
  const qc = useQueryClient();
  const join = useMutation({
    mutationFn: () => api.post<{ college: string; label: string }>("/college/staff/join", f),
    onSuccess: (r) => {
      toast.success(`Joined ${r.college} as ${r.label}`);
      qc.invalidateQueries({ queryKey: ["college"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });
  return (
    <Card className="mx-auto max-w-[560px]">
      <CardHeader title="Join your college's placement cell" description="Heads of department and faculty join with the staff code from your TPO. Your college may require your college email. TPO access is granted by JobPilot or another TPO." />
      <form
        className="grid gap-3 p-5 pt-3 sm:grid-cols-2"
        onSubmit={(e) => {
          e.preventDefault();
          join.mutate();
        }}
      >
        <Field label="Staff code" className="sm:col-span-2">
          <Input required value={f.code} onChange={(e) => setF({ ...f, code: e.target.value })} placeholder="STAFF-XXXX-XXXX-XXXX" autoComplete="off" />
        </Field>
        <Field label="Your role">
          <select value={f.role} onChange={(e) => setF({ ...f, role: e.target.value as "hod" | "teacher" })} className="h-10 rounded-[var(--radius-control)] border border-border bg-transparent px-3 text-[14px]">
            <option value="hod">Head of Department</option>
            <option value="teacher">Faculty</option>
          </select>
        </Field>
        <Field label="Department" hint="You'll see this department's students">
          <Input value={f.department} onChange={(e) => setF({ ...f, department: e.target.value })} placeholder="e.g. Computer Engineering" required={f.role === "hod"} />
        </Field>
        <div className="sm:col-span-2">
          <Button type="submit" variant="primary" loading={join.isPending}>
            <UserPlus /> Join as staff
          </Button>
        </div>
      </form>
      <p className="border-t border-border p-5 text-[12.5px] text-text-3">
        A college that isn&rsquo;t on JobPilot yet? See{" "}
        <a href="/campus-pricing" className="text-cobalt-text">
          campus plans
        </a>
        .
      </p>
    </Card>
  );
}

function Reasoning({ r }: { r: Placement["reasoning"] }) {
  return (
    <div className="space-y-2 text-[12.5px]">
      {r.explanation && <p className="text-text-2">{r.explanation}</p>}
      {!!r.requirements?.length && (
        <ul className="space-y-1">
          {r.requirements.map((q, i) => (
            <li key={i} className="flex gap-2">
              <span className={cn("shrink-0", q.status === "met" ? "text-success" : q.status === "partial" ? "text-warning" : "text-[var(--error)]")}>{q.status === "met" ? "✓" : q.status === "partial" ? "~" : "✗"}</span>
              <span>
                <b>{q.text}</b>
                {q.kind === "must" ? "" : " (nice to have)"}
                {q.evidence && <span className="text-text-3 italic"> · “{q.evidence}”</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
      {!r.requirements?.length && (
        <p className="text-text-2">
          {r.strengths?.length ? `Strong: ${r.strengths.join(", ")}. ` : ""}
          {r.gaps?.length ? `Missing: ${r.gaps.join(", ")}.` : ""}
        </p>
      )}
      {!!r.guardrails?.length && <p className="text-warning">Guardrails: {r.guardrails.join(" · ")}</p>}
      <p className="text-text-3">
        Signals: semantic {r.semantic ?? "—"} · skills {r.skills ?? "—"} · reviewer {r.llm ?? "—"}
      </p>
    </div>
  );
}

function PlacementRow({ p, me }: { p: Placement; me: StaffMe }) {
  const [open, setOpen] = useState(p.stage === "proposed");
  const [note, setNote] = useState("");
  const refresh = useRefresh();
  const decide = useMutation({
    mutationFn: (decision: "approve" | "reject") => api.post(`/college/placements/${p.id}/decision`, { decision, note }),
    onSuccess: (_r, d) => (toast.success(d === "approve" ? "Shortlisted: the student has been told" : "Marked not a fit"), refresh()),
    onError: (e: Error) => toast.error(e.message),
  });
  const move = useMutation({
    mutationFn: (stage: string) => api.put(`/college/placements/${p.id}/stage`, { stage, note }),
    onSuccess: () => (toast.success("Updated; the student has been told"), setNote(""), refresh()),
    onError: (e: Error) => toast.error(e.message),
  });
  const fb = useMutation({
    mutationFn: () => api.post(`/college/placements/${p.id}/feedback`, { note }),
    onSuccess: () => (toast.success("Feedback saved"), setNote(""), refresh()),
    onError: (e: Error) => toast.error(e.message),
  });
  const may = (x: string) => me.permissions.includes(x);
  return (
    <li className="rounded-[var(--radius-card)] border border-border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="min-w-0 flex-1">
          <div className="text-[14px] font-medium">
            {p.student ?? "Student"} <span className="font-normal text-text-2">→ {p.title} · {p.company}</span>
          </div>
          <div className="text-[12px] text-text-3">
            {p.source === "ai_recommended" ? "AI proposal" : p.source === "staff_posted" ? "Posted by staff" : "Added by the student"}
            {p.match_score != null && ` · fit ${Math.round(p.match_score)}`}
            {p.updated_at && ` · ${ago(p.updated_at)}`}
          </div>
        </div>
        <Badge tone={STAGE_TONE[p.stage] ?? "outline"}>{p.stage_label}</Badge>
        <Button size="icon" variant="ghost" className="size-8" aria-label={open ? "Hide details" : "Show details"} onClick={() => setOpen((o) => !o)}>
          {open ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
        </Button>
      </div>
      {open && (
        <div className="mt-3 space-y-3 border-t border-border pt-3">
          {p.reasoning && Object.keys(p.reasoning).length > 0 && <Reasoning r={p.reasoning} />}
          {p.feedback && <p className="text-[12.5px]">Feedback: {p.feedback}</p>}
          {!!p.history.length && (
            <ol className="flex flex-wrap gap-x-3 gap-y-1 text-[11.5px] text-text-3">
              {p.history.map((h, i) => (
                <li key={i}>
                  {h.stage.replace("_", " ")} · {ago(h.at)}
                </li>
              ))}
            </ol>
          )}
          <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder={p.stage === "proposed" ? "Optional note to the student (e.g. register by Friday)" : "Note or interview feedback (optional)"} aria-label="Note" />
          <div className="flex flex-wrap gap-2">
            {p.stage === "proposed" && may("approve") && (
              <>
                <Button size="sm" variant="primary" loading={decide.isPending && decide.variables === "approve"} onClick={() => decide.mutate("approve")}>
                  <Check /> Approve & shortlist
                </Button>
                <Button size="sm" loading={decide.isPending && decide.variables === "reject"} onClick={() => decide.mutate("reject")}>
                  <X /> Not a fit
                </Button>
              </>
            )}
            {p.stage !== "proposed" && may("move") && !["placed", "rejected", "dismissed", "withdrawn"].includes(p.stage) &&
              MOVES.map((m) => (
                <Button key={m.key} size="sm" variant={m.key === "placed" ? "primary" : "secondary"} disabled={m.key === p.stage} loading={move.isPending && move.variables === m.key} onClick={() => move.mutate(m.key)}>
                  {m.label}
                </Button>
              ))}
            {may("feedback") && note.trim().length > 1 && p.stage !== "proposed" && (
              <Button size="sm" variant="ghost" loading={fb.isPending} onClick={() => fb.mutate()}>
                Save feedback only
              </Button>
            )}
          </div>
        </div>
      )}
    </li>
  );
}

/** The pipeline: AI proposals waiting for approval first, then every stage, with the AI's measured precision. */
export function PipelineBoard({ me }: { me: StaffMe }) {
  const [stage, setStage] = useState<string>("proposed");
  const { data, isLoading } = useQuery({ queryKey: ["college-pipeline", stage], queryFn: () => api.get<Pipeline>(`/college/pipeline${stage === "all" ? "" : `?stage=${stage}`}`) });
  const all = useQuery({ queryKey: ["college-pipeline", "counts"], queryFn: () => api.get<Pipeline>("/college/pipeline") });
  const refresh = useRefresh();
  const pull = useMutation({
    mutationFn: () => api.post<{ proposed: number }>("/college/proposals/refresh"),
    onSuccess: (r) => (toast.success(r.proposed ? `${r.proposed} new proposal(s)` : "No new strong matches right now"), refresh()),
    onError: (e: Error) => toast.error(e.message),
  });
  const prec = all.data?.precision;
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="card p-4">
          <div className="text-[13px] text-text-2">Waiting for approval</div>
          <div className="num mt-2 text-[28px] leading-none font-semibold">{all.data?.stages.find((s) => s.key === "proposed")?.count ?? "—"}</div>
        </div>
        <div className="card p-4">
          <div className="text-[13px] text-text-2">Placed</div>
          <div className="num mt-2 text-[28px] leading-none font-semibold">{all.data?.stages.find((s) => s.key === "placed")?.count ?? "—"}</div>
        </div>
        <div className="card p-4">
          <div className="flex items-center gap-1.5 text-[13px] text-text-2">
            <ShieldCheck className="size-3.5" /> AI precision (P@{prec?.k ?? 5})
          </div>
          <div className="num mt-2 text-[28px] leading-none font-semibold">{prec?.precision == null ? "—" : `${Math.round(prec.precision * 100)}%`}</div>
          <div className="mt-1 text-[11.5px] text-text-3">{prec?.decided ? `${prec.approved} of ${prec.decided} top proposals approved by staff · target 90%` : "Shown once staff decide on proposals"}</div>
        </div>
      </div>
      <Card>
        <CardHeader
          title="Placement pipeline"
          description="AI proposals come from jobs you post and from your students' own strong matches. Approve to shortlist; then move students round by round. Students are told at every step."
          action={
            me.permissions.includes("approve") ? (
              <Button size="sm" onClick={() => pull.mutate()} loading={pull.isPending}>
                <RefreshCw /> Find new matches
              </Button>
            ) : undefined
          }
        />
        <div className="space-y-3 p-5 pt-3">
          <div className="flex flex-wrap gap-1.5">
            {[{ key: "all", label: "All", count: all.data?.items.length ?? 0 }, ...(all.data?.stages ?? [])].map((s) => (
              <button key={s.key} type="button" aria-pressed={stage === s.key} onClick={() => setStage(s.key)} className={cn("h-8 rounded-full border px-3 text-[12.5px]", stage === s.key ? "border-[var(--cobalt)] bg-cobalt-subtle text-cobalt-text" : "border-border text-text-2 hover:text-text")}>
                {s.label} <span className="num text-text-3">{s.count}</span>
              </button>
            ))}
          </div>
          {isLoading ? (
            <Skeleton className="h-40" />
          ) : data?.items.length ? (
            <ul className="space-y-2">
              {data.items.map((p) => (
                <PlacementRow key={p.id} p={p} me={me} />
              ))}
            </ul>
          ) : (
            <p className="text-[13px] text-text-3">{stage === "proposed" ? "No proposals waiting. Post a job, or press Find new matches." : "Nothing at this stage yet."}</p>
          )}
        </div>
      </Card>
    </div>
  );
}

/** Every sharing student in scope, with their furthest stage and pipeline. */
export function StudentAudit() {
  const { data, isLoading } = useQuery({ queryKey: ["college-students"], queryFn: () => api.get<{ total_students: number; visible: number; scope: string; students: StudentRow[] }>("/college/students") });
  const [q, setQ] = useState("");
  if (isLoading || !data) return <Skeleton className="h-60" />;
  const rows = data.students.filter((s) => !q || `${s.name} ${s.email} ${s.branch}`.toLowerCase().includes(q.toLowerCase()));
  return (
    <Card>
      <CardHeader title="Student progress" description={`${data.visible} of ${data.total_students} students share their progress · scope: ${data.scope}. Students who don't share are counted but never listed. Each view is logged.`} />
      <div className="space-y-3 p-5 pt-3">
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name, email or branch" aria-label="Search students" />
        <div className="overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead className="text-left text-[11.5px] tracking-wide text-subtle uppercase">
              <tr>
                {["Student", "Branch", "CGPA", "Matches", "Applied", "Interviews", "Offers", "Furthest stage", "Last active"].map((h) => (
                  <th key={h} className="pb-2 pr-3 font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rows.map((s) => (
                <tr key={s.user_id}>
                  <td className="py-2 pr-3">
                    <div className="font-medium">{s.name}</div>
                    <div className="text-[11.5px] text-subtle">{s.email}</div>
                  </td>
                  <td className="py-2 pr-3">{s.branch || "—"}</td>
                  <td className="num py-2 pr-3">{s.cgpa ?? "—"}</td>
                  <td className="num py-2 pr-3">{s.matches}</td>
                  <td className="num py-2 pr-3">{s.applied}</td>
                  <td className="num py-2 pr-3">{s.interviews}</td>
                  <td className="num py-2 pr-3">{s.offers}</td>
                  <td className="py-2 pr-3">
                    <Badge tone={STAGE_TONE[s.furthest ?? ""] ?? "outline"}>{s.furthest_label}</Badge>
                    {s.pipeline[0] && <div className="mt-0.5 text-[11.5px] text-text-3">{s.pipeline[0].company}</div>}
                  </td>
                  <td className="py-2 text-subtle">{s.last_active ? ago(s.last_active) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!rows.length && <p className="pt-3 text-[13px] text-subtle">{data.visible ? "No student matches that search." : "No students in your scope share their progress yet."}</p>}
        </div>
      </div>
    </Card>
  );
}

/** Post a job from a recruiter's link: matched to students right away. */
export function CampusJobs({ me }: { me: StaffMe }) {
  const blank = { title: "", company: "", url: "", location: "", description: "", track: "technical", kind: "internship" };
  const [f, setF] = useState(blank);
  const [open, setOpen] = useState(false);
  const refresh = useRefresh();
  const { data } = useQuery({ queryKey: ["college-jobs"], queryFn: () => api.get<{ id: string; title: string; company: string; url: string; track: string; posted_at: string | null; placements: number }[]>("/college/jobs") });
  const post = useMutation({
    mutationFn: () => api.post<{ proposed: number }>("/college/jobs", f),
    onSuccess: (r) => (toast.success(`Posted. ${r.proposed} student${r.proposed === 1 ? "" : "s"} proposed for your approval`), setF(blank), setOpen(false), refresh()),
    onError: (e: Error) => toast.error(e.message),
  });
  const rematch = useMutation({
    mutationFn: (id: string) => api.post<{ proposed: number }>(`/college/jobs/${id}/rematch`),
    onSuccess: (r) => (toast.success(r.proposed ? `${r.proposed} new proposal(s)` : "No new students clear the bar"), refresh()),
    onError: (e: Error) => toast.error(e.message),
  });
  const may = me.permissions.includes("post_job");
  return (
    <Card>
      <CardHeader
        title="Jobs for your students"
        description="Visible only to your college's students. Each is ranked against every sharing student in your scope: nearest profiles first, then a requirement-by-requirement review of each resume."
        action={
          may ? (
            <Button size="sm" variant="primary" onClick={() => setOpen((o) => !o)}>
              <Plus /> Post a job
            </Button>
          ) : undefined
        }
      />
      <div className="space-y-3 p-5 pt-3">
        {open && (
          <form
            className="grid gap-3 rounded-[var(--radius-card)] border border-border p-4 sm:grid-cols-2"
            onSubmit={(e) => {
              e.preventDefault();
              post.mutate();
            }}
          >
            <Field label="Role">
              <Input required value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} placeholder="Software Engineer Intern" />
            </Field>
            <Field label="Company">
              <Input required value={f.company} onChange={(e) => setF({ ...f, company: e.target.value })} />
            </Field>
            <Field label="Apply link">
              <Input value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} placeholder="https://careers.example.com/…" />
            </Field>
            <Field label="Location">
              <Input value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })} placeholder="Bengaluru / Remote" />
            </Field>
            <Field label="Track">
              <select value={f.track} onChange={(e) => setF({ ...f, track: e.target.value })} className="h-10 rounded-[var(--radius-control)] border border-border bg-transparent px-3 text-[14px]">
                <option value="technical">Technical</option>
                <option value="non_technical">Non-technical</option>
              </select>
            </Field>
            <Field label="Type">
              <select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })} className="h-10 rounded-[var(--radius-control)] border border-border bg-transparent px-3 text-[14px]">
                <option value="internship">Internship</option>
                <option value="full_time">Full time</option>
              </select>
            </Field>
            <Field label="Job description" className="sm:col-span-2" hint="Paste the full description: requirements drive the matching">
              <Textarea required minLength={40} rows={6} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} />
            </Field>
            <div className="sm:col-span-2">
              <Button type="submit" variant="primary" loading={post.isPending}>
                <Sparkles /> Post and match students
              </Button>
              {post.isPending && <span className="ml-3 text-[12.5px] text-text-3">Ranking your students… up to a minute.</span>}
            </div>
          </form>
        )}
        {!data?.length && !open && <p className="text-[13px] text-text-3">No jobs posted yet.</p>}
        <ul className="divide-y divide-border">
          {data?.map((j) => (
            <li key={j.id} className="flex flex-wrap items-center gap-3 py-2.5">
              <div className="min-w-0 flex-1">
                <div className="text-[14px] font-medium">
                  {j.title} · {j.company}
                </div>
                <div className="text-[12px] text-text-3">
                  {j.track === "technical" ? "Technical" : "Non-technical"} · {j.placements} in pipeline{j.posted_at && ` · posted ${ago(j.posted_at)}`}
                </div>
              </div>
              {may && (
                <Button size="sm" variant="ghost" loading={rematch.isPending && rematch.variables === j.id} onClick={() => rematch.mutate(j.id)}>
                  <RefreshCw /> Match again
                </Button>
              )}
            </li>
          ))}
        </ul>
      </div>
    </Card>
  );
}

/** Staff list, roles and the staff code (TPOs manage; others see who's on the team). */
export function StaffPanel({ me }: { me: StaffMe }) {
  const refresh = useRefresh();
  const { data } = useQuery({ queryKey: ["college-staff"], queryFn: () => api.get<{ id: string; name: string; email: string; role: string; label: string; department: string; you: boolean }[]>("/college/staff") });
  const [code, setCode] = useState<string | null>(null);
  const [domain, setDomain] = useState(me.domain ?? "");
  const manage = me.permissions.includes("manage_staff");
  const rotate = useMutation({ mutationFn: () => api.post<{ code: string }>("/college/staff-code"), onSuccess: (r) => (setCode(r.code), refresh()), onError: (e: Error) => toast.error(e.message) });
  const saveDomain = useMutation({ mutationFn: () => api.put("/college/settings", { domain: domain.trim() || null }), onSuccess: () => (toast.success("Saved"), refresh()), onError: (e: Error) => toast.error(e.message) });
  const update = useMutation({ mutationFn: (b: { id: string; role: string; department: string }) => api.put(`/college/staff/${b.id}`, b), onSuccess: () => (toast.success("Updated"), refresh()), onError: (e: Error) => toast.error(e.message) });
  const remove = useMutation({ mutationFn: (id: string) => api.del(`/college/staff/${id}`), onSuccess: () => (toast.success("Removed"), refresh()), onError: (e: Error) => toast.error(e.message) });
  return (
    <div className="grid gap-6 xl:grid-cols-[1.3fr_1fr] [&>*]:min-w-0">
      <Card>
        <CardHeader title="Placement staff" description="TPOs see the whole college; HODs and faculty see their department's students." />
        <ul className="divide-y divide-border px-5 pb-3">
          {data?.map((s) => (
            <li key={s.id} className="flex flex-wrap items-center gap-2 py-2.5">
              <div className="min-w-0 flex-1">
                <div className="text-[14px] font-medium">
                  {s.name} {s.you && <span className="text-[12px] text-text-3">(you)</span>}
                </div>
                <div className="text-[12px] text-text-3">
                  {s.email}
                  {s.department && ` · ${s.department}`}
                </div>
              </div>
              {manage && !s.you ? (
                <>
                  <select aria-label={`Role for ${s.name}`} value={s.role} onChange={(e) => update.mutate({ id: s.id, role: e.target.value, department: s.department })} className="h-8 rounded-[var(--radius-control)] border border-border bg-transparent px-2 text-[12.5px]">
                    <option value="tpo">TPO</option>
                    <option value="hod">HOD</option>
                    <option value="teacher">Faculty</option>
                  </select>
                  <Button size="icon" variant="ghost" className="size-8" aria-label={`Remove ${s.name}`} onClick={() => remove.mutate(s.id)}>
                    <Trash2 className="size-4" />
                  </Button>
                </>
              ) : (
                <Badge tone="outline">{s.label}</Badge>
              )}
            </li>
          ))}
        </ul>
      </Card>
      {manage && (
        <Card>
          <CardHeader title="Staff access" description="Staff join with this code. Only a hash is stored, so a new code is shown once; the old one stops working." />
          <div className="space-y-4 p-5 pt-3">
            {code ? (
              <div className="rounded-[var(--radius-card)] border border-[var(--cobalt)]/40 bg-cobalt-subtle/40 p-3">
                <div className="num text-[16px] font-semibold tracking-wide">{code}</div>
                <p className="mt-1 text-[12px] text-text-3">Copy it now; it won&rsquo;t be shown again. Share it only with staff.</p>
                <Button size="sm" className="mt-2" onClick={() => (navigator.clipboard.writeText(code), toast.success("Copied"))}>
                  Copy
                </Button>
              </div>
            ) : (
              <p className="text-[13px] text-text-2">{me.staff_code_set ? `A staff code is active${me.staff_code_set_at ? ` (issued ${ago(me.staff_code_set_at)})` : ""}.` : "No staff code yet."}</p>
            )}
            <Button onClick={() => rotate.mutate()} loading={rotate.isPending}>
              <KeyRound /> {me.staff_code_set ? "Issue a new code" : "Create a staff code"}
            </Button>
            <Field label="Require staff emails on this domain" hint="e.g. coep.ac.in; leave empty to allow any email">
              <div className="flex gap-2">
                <Input value={domain} onChange={(e) => setDomain(e.target.value)} placeholder="yourcollege.edu.in" />
                <Button onClick={() => saveDomain.mutate()} loading={saveDomain.isPending}>
                  Save
                </Button>
              </div>
            </Field>
          </div>
        </Card>
      )}
    </div>
  );
}

/** The student's own pipeline as their placement cell runs it. */
export function MyPlacements() {
  const { data } = useQuery({ queryKey: ["campus-placements"], queryFn: () => api.get<Placement[]>("/campus/placements") });
  if (!data?.length) return null;
  return (
    <Card>
      <CardHeader title="Your placement pipeline" description="Shortlists and rounds from your college's placement cell. Updates arrive here and in notifications." />
      <ul className="divide-y divide-border px-5 pb-3">
        {data.map((p) => (
          <li key={p.id} className="flex flex-wrap items-center gap-2 py-2.5">
            <div className="min-w-0 flex-1">
              <div className="text-[14px] font-medium">
                {p.title} · {p.company}
              </div>
              {p.feedback && <div className="text-[12.5px] text-text-2">{p.feedback}</div>}
            </div>
            <Badge tone={STAGE_TONE[p.stage] ?? "outline"}>{p.stage_label}</Badge>
          </li>
        ))}
      </ul>
    </Card>
  );
}

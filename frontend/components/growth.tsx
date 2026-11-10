"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, GitBranch, Mic, MicOff, Target } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button, buttonClass } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Input, Textarea } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/misc";
import { api } from "@/lib/api";

type Q = { id: string; q: string; jd_line: string; skill: string | null; kind: string };
type Score = { relevance: number; specificity: number; structure: number; score: number; tests: string; feedback: string[] };
type Session = { id: string; match_id: string; questions: Q[]; answers: Record<string, string>; scores: Record<string, Score>; completed_at: string | null };
type Gap = { id: string; skill: string; status: string; repo_url: string | null; before_score: number | null; after_score: number | null; spec: { title: string; why: string; deadline_hours: number; steps: string[]; accepted_if: string[] } };

/** On a job page: practise for this job, and close a near-miss gap with a 48-hour project. */
export function GrowthPanel({ matchId }: { matchId: string }) {
  const router = useRouter();
  const start = useMutation({
    mutationFn: () => api.post<Session>("/interviews", { match_id: matchId }),
    onSuccess: (s) => router.push(`/interview/${s.id}`),
    onError: (e: Error) => toast.error(e.message),
  });
  const { data: gaps } = useQuery({ queryKey: ["gaps", matchId], queryFn: () => api.get<Gap[]>(`/matches/${matchId}/gap-projects`) });
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader icon={<Mic className="size-4" />} title="Mock interview for this job" description="8-12 questions from this job description and your projects. Type or speak; each answer is scored against the line it tests." />
        <div className="p-5">
          <Button variant="primary" onClick={() => start.mutate()} loading={start.isPending}>
            Start practice
          </Button>
        </div>
      </Card>
      {!!gaps?.length && (
        <Card>
          <CardHeader icon={<Target className="size-4" />} title="Close a gap in 48 hours" description="Build a small project that proves the missing skill. Submit the repo and we re-score this job." />
          <div className="space-y-4 p-5">
            {gaps.map((g) => (
              <GapItem key={g.id} g={g} matchId={matchId} />
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

function GapItem({ g, matchId }: { g: Gap; matchId: string }) {
  const [url, setUrl] = useState("");
  const qc = useQueryClient();
  const submit = useMutation({
    mutationFn: () => api.post<Gap>(`/gap-projects/${g.id}/submit`, { repo_url: url }),
    onSuccess: (r) => {
      toast.success(`Verified. Fit ${r.before_score} → ${r.after_score}`);
      qc.invalidateQueries();
    },
    onError: (e: Error) => toast.error(e.message),
  });
  return (
    <div className="rounded-[var(--radius-card)] border border-border p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-[14px] font-semibold">{g.spec.title}</div>
        {g.status === "verified" ? (
          <Badge tone="success">
            <Check /> Fit {g.before_score} → {g.after_score}
          </Badge>
        ) : (
          <Badge tone="outline">{g.skill}</Badge>
        )}
      </div>
      <p className="mt-1 text-[12.5px] text-text-2">{g.spec.why}</p>
      {g.status !== "verified" && (
        <>
          <ol className="mt-2 list-decimal space-y-1 pl-5 text-[13px] text-text-2">
            {g.spec.steps.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ol>
          <div className="mt-3 flex gap-2">
            <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://github.com/you/project" className="flex-1" />
            <Button onClick={() => submit.mutate()} loading={submit.isPending} disabled={!url.startsWith("https://github.com/")}>
              <GitBranch /> Submit
            </Button>
          </div>
        </>
      )}
      {g.status === "verified" && g.repo_url && (
        <a href={g.repo_url} target="_blank" rel="noreferrer" className="mt-2 inline-block text-[12.5px] text-accent hover:underline">
          {g.repo_url}
        </a>
      )}
      <span className="sr-only">{matchId}</span>
    </div>
  );
}

type SR = { start: () => void; stop: () => void; onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null; onend: (() => void) | null; lang: string; continuous: boolean; interimResults: boolean };

/** One question at a time; voice uses the browser's own speech recognition (nothing is recorded or uploaded). */
export function InterviewRunner({ id }: { id: string }) {
  const qc = useQueryClient();
  const { data: s } = useQuery({ queryKey: ["interview", id], queryFn: () => api.get<Session>(`/interviews/${id}`) });
  const [i, setI] = useState(0);
  const [text, setText] = useState("");
  const [listening, setListening] = useState(false);
  const rec = useRef<SR | null>(null);
  const answer = useMutation({
    mutationFn: (b: { question_id: string; answer: string }) => api.post<Session>(`/interviews/${id}/answer`, b),
    onSuccess: (r) => qc.setQueryData(["interview", id], r),
    onError: (e: Error) => toast.error(e.message),
  });
  const apply = useMutation({
    mutationFn: (ids: string[]) => api.post<{ added: string[] }>(`/interviews/${id}/apply-skills`, { question_ids: ids }),
    onSuccess: (r) => toast.success(r.added.length ? `Added ${r.added.join(", ")} and re-scored the job` : "Nothing strong enough to add yet"),
  });
  useEffect(() => () => rec.current?.stop(), []);
  if (!s) return <Skeleton className="h-64" />;
  const q = s.questions[i];
  const sc = q ? s.scores[q.id] : undefined;
  const toggleMic = () => {
    const W = window as unknown as { SpeechRecognition?: new () => SR; webkitSpeechRecognition?: new () => SR };
    const Ctor = W.SpeechRecognition ?? W.webkitSpeechRecognition;
    if (!Ctor) return toast("Voice isn’t supported in this browser. Type your answer instead.");
    if (listening) return rec.current?.stop();
    const r = new Ctor();
    r.lang = "en-IN";
    r.continuous = true;
    r.interimResults = false;
    r.onresult = (e) => setText((t) => `${t} ${Array.from(e.results).map((x) => x[0].transcript).join(" ")}`.trim());
    r.onend = () => setListening(false);
    rec.current = r;
    r.start();
    setListening(true);
  };
  const strong = s.questions.filter((x) => x.skill && (s.scores[x.id]?.score ?? 0) >= 4).map((x) => x.id);
  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div className="flex items-center justify-between text-[13px] text-text-2">
        <span>
          Question {Math.min(i + 1, s.questions.length)} of {s.questions.length}
        </span>
        <Link href={`/jobs/${s.match_id}`} className="hover:underline">
          Back to the job
        </Link>
      </div>
      {q ? (
        <Card>
          <div className="space-y-4 p-5">
            <p className="text-[17px] leading-relaxed font-medium">{q.q}</p>
            <p className="text-[12.5px] text-text-3">Tests: “{q.jd_line}”</p>
            <Textarea value={text} onChange={(e) => setText(e.target.value)} rows={6} placeholder="Your answer…" />
            <div className="flex flex-wrap gap-2">
              <Button onClick={toggleMic} aria-pressed={listening}>
                {listening ? <MicOff /> : <Mic />} {listening ? "Stop" : "Speak"}
              </Button>
              <Button variant="primary" loading={answer.isPending} disabled={!text.trim()} onClick={() => answer.mutate({ question_id: q.id, answer: text })}>
                Score my answer
              </Button>
              {sc && (
                <Button
                  variant="ghost"
                  onClick={() => {
                    setI(i + 1);
                    setText("");
                  }}
                >
                  Next question
                </Button>
              )}
            </div>
            {sc && (
              <div className="rounded-[var(--radius-card)] border border-border p-4 text-[13.5px]">
                <div className="num font-semibold">
                  {sc.score}/5 · relevance {sc.relevance} · specificity {sc.specificity} · structure {sc.structure}
                </div>
                <ul className="mt-2 space-y-1 text-text-2">
                  {sc.feedback.map((f) => (
                    <li key={f}>· {f}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </Card>
      ) : (
        <Card>
          <div className="space-y-3 p-5">
            <p className="text-[16px] font-semibold">Session complete</p>
            <p className="text-[13.5px] text-text-2">
              Average {(Object.values(s.scores).reduce((a, x) => a + x.score, 0) / Math.max(1, Object.keys(s.scores).length)).toFixed(1)}/5 across {Object.keys(s.scores).length} answers.
            </p>
            {!!strong.length && (
              <Button variant="primary" loading={apply.isPending} onClick={() => apply.mutate(strong)}>
                Add the skills I showed to my profile
              </Button>
            )}
            <Link href={`/jobs/${s.match_id}`} className={buttonClass({})}>
              Back to the job
            </Link>
          </div>
        </Card>
      )}
    </div>
  );
}

type Agg = { company: string; reports: number; median_stipend: number; stipend_range: [number, number]; ppo_rate: number; paid_on_time_rate: number; modes: string[] };
type Mine = { id: string; company: string; stipend: number; status: string; verified_via: string };

/** Stipend & PPO ledger: share yours (verified), see companies with 3+ reports. */
export function Ledger() {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const { data: rows } = useQuery({ queryKey: ["ledger", q], queryFn: () => api.get<Agg[]>(`/ledger/companies?q=${encodeURIComponent(q)}`) });
  const { data: mine } = useQuery({ queryKey: ["ledger-mine"], queryFn: () => api.get<Mine[]>("/ledger/reports") });
  const [form, setForm] = useState({ company: "", role: "", stipend: "", duration_months: "3", mode: "onsite", ppo_offered: false, paid_on_time: true });
  const [verify, setVerify] = useState<{ id: string; email: string; code: string; sent: boolean } | null>(null);
  const add = useMutation({
    mutationFn: () => api.post<Mine>("/ledger/reports", { ...form, stipend: Number(form.stipend), duration_months: Number(form.duration_months) }),
    onSuccess: (r) => {
      setVerify({ id: r.id, email: "", code: "", sent: false });
      qc.invalidateQueries({ queryKey: ["ledger-mine"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const call = async (fn: () => Promise<unknown>, ok: string) => {
    try {
      await fn();
      toast.success(ok);
      qc.invalidateQueries({ queryKey: ["ledger-mine"] });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Something went wrong");
    }
  };
  return (
    <div className="grid gap-6 xl:grid-cols-2 [&>*]:min-w-0">
      <Card>
        <CardHeader title="What companies really pay interns" description="From verified student reports. A company appears only once 3 or more students have reported." />
        <div className="space-y-3 p-5">
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search a company" />
          {!rows?.length && <p className="text-[13px] text-subtle">No company has 3 verified reports yet.</p>}
          {rows?.map((r) => (
            <div key={r.company} className="rounded-[var(--radius-card)] border border-border px-4 py-3 text-[13.5px]">
              <div className="flex justify-between font-medium">
                <span>{r.company}</span>
                <span className="num">₹{r.median_stipend.toLocaleString("en-IN")}/mo</span>
              </div>
              <div className="text-[12px] text-subtle">
                {r.reports} reports · ₹{r.stipend_range[0].toLocaleString("en-IN")}–{r.stipend_range[1].toLocaleString("en-IN")} · PPO {Math.round(r.ppo_rate * 100)}% · paid on time {Math.round(r.paid_on_time_rate * 100)}%
              </div>
            </div>
          ))}
        </div>
      </Card>
      <Card>
        <CardHeader title="Share your internship" description="Needs the ledger consent in Settings → Privacy. Your name is never shown; only totals of 3+ students are." />
        <div className="space-y-3 p-5">
          <div className="grid gap-2 sm:grid-cols-2">
            <Input value={form.company} onChange={(e) => setForm({ ...form, company: e.target.value })} placeholder="Company" />
            <Input value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} placeholder="Role" />
            <Input value={form.stipend} onChange={(e) => setForm({ ...form, stipend: e.target.value })} inputMode="numeric" placeholder="Stipend ₹ / month" />
            <Input value={form.duration_months} onChange={(e) => setForm({ ...form, duration_months: e.target.value })} inputMode="numeric" placeholder="Months" />
          </div>
          <div className="flex flex-wrap gap-4 text-[13px]">
            <select value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value })} className="h-10 rounded-[var(--radius-control)] border border-border bg-surface px-2">
              <option value="onsite">Onsite</option>
              <option value="hybrid">Hybrid</option>
              <option value="remote">Remote</option>
            </select>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={form.ppo_offered} onChange={(e) => setForm({ ...form, ppo_offered: e.target.checked })} /> PPO offered
            </label>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={form.paid_on_time} onChange={(e) => setForm({ ...form, paid_on_time: e.target.checked })} /> Paid on time
            </label>
          </div>
          <Button variant="primary" onClick={() => add.mutate()} loading={add.isPending} disabled={!form.company || !form.stipend}>
            Add report
          </Button>
          {verify && (
            <div className="space-y-2 rounded-[var(--radius-card)] border border-border p-3 text-[13px]">
              <div className="font-medium">Verify it (needed before it counts)</div>
              <div className="flex gap-2">
                <Input value={verify.email} onChange={(e) => setVerify({ ...verify, email: e.target.value })} placeholder="you@college.ac.in" className="flex-1" />
                <Button onClick={() => call(() => api.post(`/ledger/reports/${verify.id}/otp`, { college_email: verify.email }), "Code sent").then(() => setVerify({ ...verify, sent: true }))}>Send code</Button>
              </div>
              {verify.sent && (
                <div className="flex gap-2">
                  <Input value={verify.code} onChange={(e) => setVerify({ ...verify, code: e.target.value })} placeholder="6-digit code" className="flex-1" />
                  <Button onClick={() => call(() => api.post(`/ledger/reports/${verify.id}/otp/verify`, { code: verify.code }), "Verified")}>Verify</Button>
                </div>
              )}
              <label className="block text-subtle">
                Or upload the offer letter (deleted once checked; we keep only a fingerprint):{" "}
                <input
                  type="file"
                  accept=".pdf,.png,.jpg,.jpeg"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (!f) return;
                    const fd = new FormData();
                    fd.set("file", f);
                    call(() => fetch(`/api/ledger/reports/${verify.id}/offer-letter`, { method: "POST", body: fd }).then((r) => (r.ok ? r : Promise.reject(new Error("Upload failed")))), "Uploaded for review");
                  }}
                />
              </label>
            </div>
          )}
          {!!mine?.length && (
            <ul className="divide-y divide-border rounded-[var(--radius-card)] border border-border text-[13px]">
              {mine.map((m) => (
                <li key={m.id} className="flex justify-between px-3 py-2">
                  <span>
                    {m.company} · ₹{m.stipend.toLocaleString("en-IN")}
                  </span>
                  <Badge tone={m.status === "published" ? "success" : "outline"}>{m.status}</Badge>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Card>
    </div>
  );
}

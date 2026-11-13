"use client";

import { Activity, Building2, Coins, Database, Gauge, Radar, Users } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { EmptyState, PageHeader, Skeleton } from "@/components/ui/misc";
import { useAddOfficer, useAdminMetrics, useAdminOrgs, useAdminRights, useCreateOrg, useResolveRight, useSetPlan } from "@/lib/queries";
import { api } from "@/lib/api";
import { ago, cn } from "@/lib/utils";
import { toast } from "sonner";

function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="card p-4">
      <div className="text-[12.5px] text-muted">{label}</div>
      <div className="num mt-1.5 text-[24px] font-semibold tracking-[-0.02em]">{value}</div>
      {sub && <div className="mt-0.5 text-[12px] text-subtle">{sub}</div>}
    </div>
  );
}

export default function AdminPage() {
  const { data: m, error, isLoading } = useAdminMetrics();
  const setPlan = useSetPlan();
  const [email, setEmail] = useState("");

  if (error) return <EmptyState icon={<Gauge className="size-5" />} title="Admins only" description="Add your email to ADMIN_EMAILS on the server, or run scripts/set_plan.py <email> admin." />;
  if (isLoading || !m) return <Skeleton agent="pilot" className="min-h-96" />;

  const queued = (m.queue.queued ?? 0) + (m.queue.resume_queued ?? 0);
  return (
    <div className="space-y-6">
      <PageHeader title="Admin" description={`Live service metrics · updated ${ago(m.generated_at)}`} />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
        <Stat label="Users" value={m.users.total} sub={`+${m.users.new_7d} this week`} />
        <Stat label="Active today" value={m.users.active_1d} sub={`${m.users.active_7d} this week`} />
        <Stat label="Pro" value={m.users.pro} sub={`${m.pro_requests.length} waiting`} />
        <Stat label="Demo sessions" value={m.users.demo_sessions_7d} sub="last 7 days" />
        <Stat label="Open jobs indexed" value={m.jobs.open.toLocaleString()} sub={`+${m.jobs.new_24h} in 24h`} />
        <Stat label="Interview rate" value={m.jobs.interview_rate == null ? "—" : `${m.jobs.interview_rate}%`} sub={`${m.jobs.applications_total ?? 0} applications all time · ${m.jobs.applications_7d} this week`} />
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.4fr_1fr] [&>*]:min-w-0">
        <Card>
          <CardHeader icon={<Radar className="size-4" />} title="Shared ingestion" description="Each board, feed and search is fetched once for every user who wants it" />
          <div className="overflow-x-auto p-5">
            <table className="w-full text-[13px]">
              <thead className="text-left text-[11.5px] tracking-wide text-subtle uppercase">
                <tr>
                  <th className="pb-2 font-medium">Source</th>
                  <th className="pb-2 text-right font-medium">Targets</th>
                  <th className="pb-2 text-right font-medium">Wanted</th>
                  <th className="pb-2 text-right font-medium">Failing</th>
                  <th className="pb-2 text-right font-medium">Overdue</th>
                  <th className="pb-2 text-right font-medium">Last fetch</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {m.sources.map((s) => (
                  <tr key={s.source}>
                    <td className="py-2 font-medium">{s.source}</td>
                    <td className="py-2 text-right font-mono tabular-nums">{s.targets}</td>
                    <td className="py-2 text-right font-mono tabular-nums">{s.wanted}</td>
                    <td className={cn("py-2 text-right font-mono tabular-nums", s.failing && "text-warning")}>{s.failing}</td>
                    <td className={cn("py-2 text-right font-mono tabular-nums", s.overdue && "text-danger")}>{s.overdue}</td>
                    <td className="py-2 text-right text-subtle">{s.last_fetch ? ago(s.last_fetch) : "never"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <div className="space-y-6">
          <Card>
            <CardHeader icon={<Activity className="size-4" />} title="Agent queue" />
            <div className="grid grid-cols-3 gap-3 p-5">
              <Stat label="Queued" value={queued} />
              <Stat label="Running" value={m.queue.running ?? 0} />
              <Stat label="Runs · 24h" value={Object.values(m.runs_24h).reduce((a, b) => a + b, 0)} sub={`${m.runs_24h.failed ?? 0} failed`} />
            </div>
          </Card>
          <Card>
            <CardHeader icon={<Coins className="size-4" />} title="AI spend · 24h" />
            <div className="space-y-2 p-5">
              <div className="flex items-baseline justify-between">
                <span className="font-mono text-2xl font-semibold">${m.llm.usd_24h.toFixed(2)}</span>
                <span className="text-[12.5px] text-subtle">${m.llm.usd_per_active_user.toFixed(3)} per active user</span>
              </div>
              {Object.entries(m.llm.by_agent).map(([agent, usd]) => (
                <div key={agent} className="flex justify-between text-[13px]">
                  <span className="text-muted">{agent}</span>
                  <span className="font-mono">${usd.toFixed(3)}</span>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-2 [&>*]:min-w-0">
        <Card>
          <CardHeader icon={<Users className="size-4" />} title="Pro requests" description="No payments yet: switch accounts to Pro by hand" />
          <div className="space-y-2 p-5">
            {m.pro_requests.length === 0 && <p className="text-[13px] text-subtle">No requests yet.</p>}
            {m.pro_requests.map((r) => (
              <div key={r.email} className="flex items-center justify-between gap-3 rounded-[var(--radius-card)] border border-border px-4 py-2.5">
                <div className="min-w-0">
                  <div className="truncate text-[13.5px] font-medium">{r.name || r.email}</div>
                  <div className="truncate text-[12px] text-subtle">
                    {r.email} · asked {ago(r.requested_at)}
                  </div>
                </div>
                <Button size="sm" variant="primary" onClick={() => setPlan.mutate({ email: r.email, plan: "pro" })}>Make Pro</Button>
              </div>
            ))}
          </div>
        </Card>
        <Card>
          <CardHeader icon={<Database className="size-4" />} title="Change a plan" />
          <form
            className="flex flex-wrap gap-2 p-5"
            onSubmit={(e) => {
              e.preventDefault();
              const plan = (e.nativeEvent as SubmitEvent).submitter?.getAttribute("value") as "free" | "pro";
              if (email.trim()) setPlan.mutate({ email: email.trim(), plan });
            }}
          >
            <Input value={email} onChange={(e) => setEmail(e.target.value)} type="email" placeholder="student@example.com" className="min-w-56 flex-1" />
            <Button type="submit" value="pro" variant="primary" loading={setPlan.isPending}>Pro</Button>
            <Button type="submit" value="free">Free</Button>
          </form>
          <div className="px-5 pb-5">
            <Badge tone="outline">Free: 10 drafts · 3 runs · $0.05 AI a day</Badge> <Badge tone="accent">Pro: 50 · 20 · $0.50</Badge>
          </div>
        </Card>
      </div>
      <Quality />
      <RightsQueue />
      <DepartmentRequests />
      <Colleges />
    </div>
  );
}

type QualityData = {
  window_days: number;
  verifier: { mix: Record<string, number>; verified_share: number | null; previous_verified_share: number | null; injection_flagged: number };
  tailor_guard: { tailored: number; bullets: number; reverted: number; revert_rate: number | null };
  llm: { calls: number; failure_rate: number | null; repair_rate: number | null; by_agent: { agent: string; calls: number; failed: number; repaired: number; p95_ms: number | null }[] };
  approvals: { events: Record<string, number>; drafts: Record<string, number>; grants: Record<string, number>; rejected: number; rejected_with_reason: number };
  outcomes: { applied: number; replied: number; reply_rate: number | null };
  cost: { runs: number; avg_inr_per_run: number | null };
  alerts: string[];
};

const pct = (v: number | null | undefined) => (v == null ? "—" : `${Math.round(v * 1000) / 10}%`);

/** Accuracy and safety signals from metadata only (no prompt, reply or email text), with alerts on shifts. */
function Quality() {
  const [days, setDays] = useState(7);
  const { data: q } = useQuery({ queryKey: ["admin-quality", days], queryFn: () => api.get<QualityData>(`/admin/quality?days=${days}`) });
  if (!q) return null;
  const mix = Object.entries(q.verifier.mix).sort((a, b) => b[1] - a[1]);
  return (
    <Card>
      <CardHeader
        icon={<Activity className="size-4" />}
        title="Quality"
        description="Accuracy and safety signals from metadata only. Offline accuracy is in the eval gate report (CI)."
        action={
          <select value={days} onChange={(e) => setDays(Number(e.target.value))} className="rounded-[var(--radius-control)] border border-border bg-transparent px-2 py-1 text-[12.5px]" aria-label="Window">
            {[1, 7, 30, 90].map((d) => (
              <option key={d} value={d}>
                Last {d} day{d > 1 ? "s" : ""}
              </option>
            ))}
          </select>
        }
      />
      <div className="space-y-4 p-5">
        {q.alerts.length > 0 && (
          <ul role="alert" className="space-y-1 rounded-[var(--radius-control)] border border-[color-mix(in_oklab,var(--error)_35%,transparent)] px-3 py-2 text-[13px] text-[var(--error)]">
            {q.alerts.map((a) => (
              <li key={a}>· {a}</li>
            ))}
          </ul>
        )}
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
          <Stat label="VERIFIED share" value={pct(q.verifier.verified_share)} sub={`was ${pct(q.verifier.previous_verified_share)}`} />
          <Stat label="Injection-flagged posts" value={q.verifier.injection_flagged} />
          <Stat label="Guard revert rate" value={pct(q.tailor_guard.revert_rate)} sub={`${q.tailor_guard.reverted} of ${q.tailor_guard.bullets} bullets`} />
          <Stat label="AI failures" value={pct(q.llm.failure_rate)} sub={`repaired ${pct(q.llm.repair_rate)} · ${q.llm.calls} calls`} />
          <Stat label="Reply rate" value={pct(q.outcomes.reply_rate)} sub={`${q.outcomes.replied} of ${q.outcomes.applied}`} />
          <Stat label="Avg cost / run" value={q.cost.avg_inr_per_run == null ? "—" : `₹${q.cost.avg_inr_per_run}`} sub={`${q.cost.runs} runs`} />
        </div>
        <div className="grid gap-4 text-[13px] md:grid-cols-3">
          <div>
            <div className="mb-1 font-medium">Verdicts</div>
            {mix.map(([k, v]) => (
              <div key={k} className="flex justify-between text-text-2">
                <span>{k}</span>
                <span className="num">{v}</span>
              </div>
            ))}
          </div>
          <div>
            <div className="mb-1 font-medium">Approvals</div>
            {Object.entries({ ...q.approvals.events, ...Object.fromEntries(Object.entries(q.approvals.grants).map(([k, v]) => [`grant: ${k}`, v])) }).map(([k, v]) => (
              <div key={k} className="flex justify-between text-text-2">
                <span>{k}</span>
                <span className="num">{v}</span>
              </div>
            ))}
            <div className="flex justify-between text-text-2">
              <span>rejected with a reason</span>
              <span className="num">
                {q.approvals.rejected_with_reason} / {q.approvals.rejected}
              </span>
            </div>
          </div>
          <div>
            <div className="mb-1 font-medium">AI calls by agent</div>
            {q.llm.by_agent.map((r) => (
              <div key={r.agent} className="flex justify-between gap-2 text-text-2">
                <span>{r.agent}</span>
                <span className="num">
                  {r.calls} · {r.failed} failed · p95 {r.p95_ms ?? "—"} ms
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </Card>
  );
}

/** DPDP rights requests and grievances, oldest due first, with the 30-day deadline. */
function RightsQueue() {
  const { data } = useAdminRights();
  const resolve = useResolveRight();
  const [answer, setAnswer] = useState<Record<string, string>>({});
  const open = (data ?? []).filter((r) => r.status === "open");
  return (
    <Card>
      <CardHeader icon={<Users className="size-4" />} title="Privacy requests" description={`${open.length} open · reply within 30 days`} />
      <div className="space-y-2 p-5">
        {open.length === 0 && <p className="text-[13px] text-subtle">Nothing waiting.</p>}
        {open.map((r) => (
          <div key={r.id} className="space-y-2 rounded-[var(--radius-card)] border border-border px-4 py-3">
            <div className="flex flex-wrap items-center justify-between gap-2 text-[13px]">
              <span className="font-medium capitalize">
                {r.kind} · {r.contact_email}
              </span>
              <Badge tone={r.overdue ? "danger" : "outline"}>{r.overdue ? "Overdue" : `Due ${new Date(r.due_at).toLocaleDateString("en-IN")}`}</Badge>
            </div>
            <p className="text-[13px] whitespace-pre-wrap text-muted">{r.details}</p>
            <div className="flex gap-2">
              <Input value={answer[r.id] ?? ""} onChange={(e) => setAnswer({ ...answer, [r.id]: e.target.value })} placeholder="Reply (emailed to them)" className="flex-1" />
              <Button size="sm" variant="primary" disabled={!answer[r.id]?.trim()} onClick={() => resolve.mutate({ id: r.id, response: answer[r.id] })}>
                Answer
              </Button>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function Colleges() {
  const { data: orgs } = useAdminOrgs();
  const create = useCreateOrg();
  const addOfficer = useAddOfficer();
  const [name, setName] = useState("");
  const [officer, setOfficer] = useState<Record<string, string>>({});
  return (
    <Card>
      <CardHeader icon={<Building2 className="size-4" />} title="Colleges" description="Create a college, share its invite code with students, and make the placement officer an officer." />
      <div className="space-y-3 p-5">
        <form onSubmit={(e) => (e.preventDefault(), name.trim() && create.mutate(name.trim(), { onSuccess: () => setName("") }))} className="flex gap-2">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Mumbai Institute of Technology" />
          <Button type="submit" variant="primary" loading={create.isPending}>Create</Button>
        </form>
        {(orgs ?? []).map((o) => (
          <div key={o.id} className="rounded-[var(--radius-card)] border border-border p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="text-[14px] font-medium">{o.name}</div>
              <div className="text-[12.5px] text-subtle">
                Code <span className="font-mono text-accent">{o.invite_code}</span> · {o.students} students · officers: {o.officers.join(", ") || "none"}
              </div>
            </div>
            <form onSubmit={(e) => (e.preventDefault(), officer[o.id] && addOfficer.mutate({ org: o.id, email: officer[o.id] }))} className="mt-3 flex gap-2">
              <Input value={officer[o.id] ?? ""} onChange={(e) => setOfficer({ ...officer, [o.id]: e.target.value })} type="email" placeholder="officer@college.edu (must have an account)" />
              <Button type="submit" size="sm">Add officer</Button>
            </form>
          </div>
        ))}
      </div>
    </Card>
  );
}

type DeptRequest = {
  id: string; college_name: string; branch: string; department_name: string; city: string; state: string; email: string; created_at: string | null;
  aishe_match: boolean; existing_campus: { id: string; name: string; plan: string; domains: string[]; website: string | null } | null;
};

/** Departments that registered themselves (Department plan, 300 students). Check the email domain belongs to the
 * college and the person is staff there before approving. */
function DepartmentRequests() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["admin-dept-requests"], queryFn: () => api.get<DeptRequest[]>("/admin/campuses/department-requests") });
  const [reason, setReason] = useState<Record<string, string>>({});
  const decide = useMutation({
    mutationFn: (v: { id: string; approve: boolean }) => api.post(`/admin/campuses/department-requests/${v.id}`, { approve: v.approve, reason: reason[v.id] || null }),
    onSuccess: (_, v) => (toast.success(v.approve ? "Approved: the department is live" : "Rejected"), qc.invalidateQueries({ queryKey: ["admin-dept-requests"] })),
    onError: (e: Error) => toast.error(e.message),
  });
  return (
    <Card>
      <CardHeader icon={<Building2 className="size-4" />} title="Departments waiting for verification" description={`${data?.length ?? 0} waiting · Department plan, 300 students each`} />
      <div className="space-y-2 p-5">
        {!data?.length && <p className="text-[13px] text-subtle">Nothing waiting.</p>}
        {data?.map((r) => {
          const domain = r.email.split("@")[1];
          const known = r.existing_campus?.domains.some((d) => domain === d || domain.endsWith(`.${d}`));
          return (
            <div key={r.id} className="space-y-2 rounded-[var(--radius-card)] border border-border px-4 py-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-[14px] font-medium">{r.department_name} · {r.college_name}{r.branch ? ` — ${r.branch}` : ""}</div>
                <div className="flex gap-1">
                  <Badge tone={r.aishe_match ? "accent" : "outline"}>{r.aishe_match ? "In AISHE list" : "Typed by hand"}</Badge>
                  <Badge tone={known ? "accent" : "outline"}>{known ? "Known domain" : "New domain"}</Badge>
                </div>
              </div>
              <div className="text-[12.5px] text-subtle">
                {r.email} · {[r.city, r.state].filter(Boolean).join(", ") || "no city given"} · {r.created_at ? ago(r.created_at) : ""}
                {r.existing_campus ? ` · joins ${r.existing_campus.name} (${r.existing_campus.plan} plan)` : " · creates the college"}
              </div>
              <div className="flex flex-wrap gap-2">
                <Input value={reason[r.id] ?? ""} onChange={(e) => setReason({ ...reason, [r.id]: e.target.value })} placeholder="Reason (needed to reject)" className="min-w-48 flex-1" />
                <Button size="sm" variant="primary" loading={decide.isPending && decide.variables?.id === r.id} onClick={() => decide.mutate({ id: r.id, approve: true })}>Approve</Button>
                <Button size="sm" disabled={!reason[r.id]?.trim()} onClick={() => decide.mutate({ id: r.id, approve: false })}>Reject</Button>
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

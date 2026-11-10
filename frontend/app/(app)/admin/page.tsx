"use client";

import { Activity, Building2, Coins, Database, Gauge, Radar, Users } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { EmptyState, PageHeader, Skeleton } from "@/components/ui/misc";
import { useAddOfficer, useAdminMetrics, useAdminOrgs, useAdminRights, useCreateOrg, useResolveRight, useSetPlan } from "@/lib/queries";
import { ago, cn } from "@/lib/utils";

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
      <RightsQueue />
      <Colleges />
    </div>
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

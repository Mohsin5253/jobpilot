"use client";

import { CalendarClock, Check, ChevronDown, GraduationCap, Plus, Trash2, X } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import { DriveForm } from "@/components/drive-form";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Field, Input, Switch } from "@/components/ui/input";
import { Segmented, Skeleton } from "@/components/ui/misc";
import { StatCard } from "@/components/ui/stat-card";
import { CREW_HERO } from "@/config/agents";
import { useAddDrive, useCampus, useDeleteDrive, useDriveStatus, useJoinCollege, useLeaveCollege, useSaveAcademics, useShareProgress } from "@/lib/queries";
import type { Drive } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATUS: [Drive["status"], string][] = [
  ["interested", "Interested"],
  ["registered", "Registered"],
  ["in_rounds", "In rounds"],
  ["selected", "Selected"],
  ["rejected", "Not selected"],
  ["skipped", "Skipping"],
];
const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleString([], { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }) : "");

function DriveCard({ d }: { d: Drive }) {
  const set = useDriveStatus();
  const del = useDeleteDrive();
  const [open, setOpen] = useState(false);
  return (
    <div className="card overflow-hidden">
      <div className="flex flex-wrap items-start gap-4 p-5">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-[16px] font-semibold">{d.company}</h3>
            {d.posted_by_college && <Badge tone="accent">From your college</Badge>}
            {d.eligible === true && <Badge tone="success"><Check className="size-3" /> Eligible</Badge>}
            {d.eligible === false && <Badge tone="danger"><X className="size-3" /> Not eligible</Badge>}
          </div>
          <div className="mt-0.5 text-[13.5px] text-muted">
            {d.role} · {d.kind === "internship" ? "Internship" : "Full-time"}
            {d.compensation && ` · ${d.compensation}`}
          </div>
          {d.register_by && <div className="mt-1.5 inline-flex items-center gap-1.5 text-[12.5px] text-accent"><CalendarClock className="size-3.5" /> Register by {fmt(d.register_by)}</div>}
          {!!d.eligibility_notes.length && <div className="mt-1.5 text-[12.5px] text-subtle">{d.eligibility_notes.join(" · ")}</div>}
        </div>
        <div className="flex items-center gap-2">
          <select value={d.status} onChange={(e) => set.mutate({ id: d.id, status: e.target.value })} aria-label={`Your status for ${d.company}`} className="h-11 rounded-[var(--radius-control)] border border-border bg-surface px-3 text-[13px] text-text md:h-9">
            {STATUS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          {d.editable && (
            <button type="button" aria-label={`Delete the ${d.company} drive`} onClick={() => del.mutate(d.id)} className="grid size-11 place-items-center rounded-[var(--radius-control)] text-text-3 hover:bg-[color-mix(in_oklab,var(--error)_10%,transparent)] hover:text-[var(--error)] md:size-9">
              <Trash2 className="size-4" />
            </button>
          )}
        </div>
      </div>
      {!!d.rounds.length && (
        <div className="border-t border-border px-5 py-3">
          <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-2 text-[13px] text-muted hover:text-fg">
            {d.rounds.map((r) => r.name).join(" → ")}
            <ChevronDown className={cn("ml-auto size-4 transition-transform", open && "rotate-180")} />
          </button>
          {open && (
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              {d.prep.map((p, i) => (
                <div key={i} className="rounded-[var(--radius-card)] border border-border bg-surface-2/50 p-4">
                  <div className="flex items-center justify-between text-[13px] font-semibold">
                    {p.round} <span className="font-normal text-subtle">{fmt(d.rounds[i]?.date ?? null)}</span>
                  </div>
                  <ul className="mt-2 space-y-1.5">
                    {p.checklist.map((c) => (
                      <li key={c} className="flex gap-2 text-[12.5px] leading-relaxed text-muted">
                        <span className="mt-1.5 size-1 shrink-0 rounded-full bg-accent" /> {c}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function AcademicsCard({ a }: { a: Record<string, unknown> }) {
  const save = useSaveAcademics();
  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    const n = (k: string) => (fd.get(k) === "" ? null : Number(fd.get(k)));
    save.mutate({ college: fd.get("college"), branch: fd.get("branch"), grad_year: n("grad_year"), cgpa: n("cgpa"), backlogs: n("backlogs") });
  };
  return (
    <Card>
      <CardHeader icon={<GraduationCap className="size-4" />} title="Your academics" description="Used only to check drive eligibility for you." />
      <form onSubmit={submit} className="grid gap-3 p-5 sm:grid-cols-2">
        <Field label="College"><Input name="college" defaultValue={String(a.college ?? "")} placeholder="Your college" /></Field>
        <Field label="Branch"><Input name="branch" defaultValue={String(a.branch ?? "")} placeholder="CSE" /></Field>
        <Field label="Graduation year"><Input name="grad_year" type="number" defaultValue={(a.grad_year as number) ?? ""} placeholder="2027" /></Field>
        <Field label="CGPA"><Input name="cgpa" type="number" step="0.01" min={0} max={10} defaultValue={(a.cgpa as number) ?? ""} placeholder="8.2" /></Field>
        <Field label="Active backlogs"><Input name="backlogs" type="number" min={0} defaultValue={(a.backlogs as number) ?? ""} placeholder="0" /></Field>
        <div className="flex items-end"><Button type="submit" loading={save.isPending} className="w-full">Save</Button></div>
      </form>
    </Card>
  );
}

function CollegeCard() {
  const { data } = useCampus();
  const join = useJoinCollege();
  const leave = useLeaveCollege();
  const share = useShareProgress();
  const [code, setCode] = useState("");
  const [agree, setAgree] = useState(false);
  const c = data?.college;
  return (
    <Card>
      <CardHeader title="Your college" description="Join your placement cell to see its drives here." />
      <div className="space-y-3 p-5">
        {c ? (
          <>
            <div className="text-[14px] font-medium">{c.name} {c.role === "officer" && <Badge tone="accent">Placement officer</Badge>}</div>
            <div className="flex items-center justify-between rounded-[var(--radius-card)] border border-border px-4 py-3">
              <div>
                <div className="text-[13.5px] font-medium">Share my progress with the placement cell</div>
                <div className="text-[12px] text-subtle">Applications, interviews and offers, by name. Without it you count only in totals.</div>
              </div>
              <Switch checked={c.sharing} onChange={(v) => share.mutate(v)} label="Share progress" />
            </div>
            {c.role === "officer" ? <Link href="/college"><Button size="sm" variant="primary">Open the college dashboard</Button></Link> : <Button size="sm" variant="ghost" onClick={() => leave.mutate(undefined)}>Leave college</Button>}
          </>
        ) : (
          <form onSubmit={(e) => (e.preventDefault(), join.mutate({ invite_code: code, share_progress: agree }))} className="space-y-3">
            <div className="flex gap-2">
              <Input value={code} onChange={(e) => setCode(e.target.value)} placeholder="Invite code from your placement cell" />
              <Button type="submit" loading={join.isPending} disabled={code.trim().length < 4}>Join</Button>
            </div>
            <label className="flex items-start gap-2 text-[12.5px] text-muted">
              <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} className="mt-0.5 accent-[var(--accent)]" />
              Also share my placement progress with the placement cell (you can turn this off any time)
            </label>
          </form>
        )}
      </div>
    </Card>
  );
}

export default function CampusPage() {
  const { data, isLoading } = useCampus();
  const add = useAddDrive();
  const [adding, setAdding] = useState(false);
  const [view, setView] = useState<"drives" | "timeline">("drives");
  if (isLoading || !data) return <Skeleton agent="researcher" className="min-h-96" />;
  const s = data.summary;
  return (
    <div className="space-y-6">
      {/* The crew, cropped: Campus's one large character moment. Kept on graphite in both themes. */}
      <div className="dark relative isolate overflow-hidden rounded-[var(--radius-panel)] border border-border bg-bg text-text">
        <Image src={CREW_HERO.src} alt="" width={CREW_HERO.width} height={CREW_HERO.height} sizes="(min-width: 1024px) 900px, 100vw" priority className="absolute inset-y-0 right-0 -z-10 h-full w-auto max-w-none object-cover opacity-90 [mask-image:linear-gradient(90deg,transparent,#000_35%)] max-md:opacity-35" />
        <div className="flex min-h-48 flex-col justify-end gap-4 p-5 md:min-h-56 md:max-w-[55%] md:p-7">
          <div>
            <div className="eyebrow mb-2">Campus placements</div>
            <h1 className="font-display text-[clamp(26px,3.2vw,36px)] leading-tight">Campus</h1>
            <p className="mt-1.5 text-[14px] text-text-2">On-campus drives, off-campus applications and internship-to-PPO, in one place.</p>
          </div>
          <div>
            <Button variant="primary" onClick={() => setAdding(true)}>
              <Plus /> Track a drive
            </Button>
          </div>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard label="Eligible soon" value={s.eligible_upcoming} />
        <StatCard label="In rounds" value={s.in_rounds} />
        <StatCard label="Selected" value={s.selected} />
        <StatCard label="Off-campus" value={s.off_campus_applied} />
      </div>

      {adding && (
        <Card className="p-5">
          <DriveForm loading={add.isPending} onCancel={() => setAdding(false)} onSubmit={(b) => add.mutate(b, { onSuccess: () => setAdding(false) })} />
        </Card>
      )}

      <div className="grid gap-6 xl:grid-cols-[1.5fr_1fr] [&>*]:min-w-0">
        <div className="space-y-4">
          <Segmented value={view} onChange={setView} options={[{ value: "drives", label: "Drives" }, { value: "timeline", label: "Timeline" }]} />
          {view === "drives" ? (
            data.drives.length ? (
              data.drives.map((d) => <DriveCard key={d.id} d={d} />)
            ) : (
              <div className="card p-8 text-center text-[14px] text-text-2">No drives yet. Join your college with its invite code, or track one yourself.</div>
            )
          ) : (
            <div className="card p-5">
              {data.timeline.length === 0 && <p className="text-[13px] text-subtle">Nothing on the timeline yet.</p>}
              <ol className="relative space-y-4 border-l border-border-strong pl-5">
                {data.timeline.map((e, i) => (
                  <li key={i} className="relative">
                    <span className={cn("absolute top-1.5 -left-[25px] size-2.5 rounded-full", e.kind === "off_campus" ? "bg-text-3" : "bg-cobalt")} />
                    <div className="text-[12px] text-subtle">{fmt(e.at)} · {e.kind === "off_campus" ? "Off-campus" : e.kind === "deadline" ? "Deadline" : "Round"}</div>
                    {e.match_id ? <Link href={`/jobs/${e.match_id}`} className="text-[14px] hover:text-accent">{e.title}</Link> : <div className="text-[14px]">{e.title}</div>}
                  </li>
                ))}
              </ol>
            </div>
          )}
        </div>
        <div className="space-y-6">
          <AcademicsCard a={data.academics} />
          <CollegeCard />
          {!!data.ppo.length && (
            <Card>
              <CardHeader title="Internship → PPO" description="Internships with a pre-placement offer in play." />
              <div className="space-y-2 p-5">
                {data.ppo.map((p) => (
                  <Link key={p.match_id} href={`/jobs/${p.match_id}`} className="flex items-center justify-between rounded-[var(--radius-card)] border border-border px-4 py-2.5 hover:border-border-strong">
                    <span className="text-[13.5px]">{p.company} · {p.title}</span>
                    <Badge tone={p.ppo_status === "converted" ? "success" : "accent"}>{p.ppo_status === "none" ? "Offer" : p.ppo_status}</Badge>
                  </Link>
                ))}
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

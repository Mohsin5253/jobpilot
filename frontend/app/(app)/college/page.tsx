"use client";

import { Building2, Copy, Plus } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { AlumniUpload, CircularImport } from "@/components/campus-v2";
import { DriveForm } from "@/components/drive-form";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { EmptyState, PageHeader, Skeleton } from "@/components/ui/misc";
import { useAddDrive, useCollege, useDeleteDrive } from "@/lib/queries";
import { ago } from "@/lib/utils";

export default function CollegePage() {
  const { data: d, isLoading, error } = useCollege();
  const add = useAddDrive(true);
  const del = useDeleteDrive(true);
  const [adding, setAdding] = useState(false);
  if (error) return <EmptyState icon={<Building2 className="size-5" />} title="For placement officers" description="Ask the JobPilot team to add you as your college’s placement officer." />;
  if (isLoading || !d) return <Skeleton agent="pilot" className="min-h-96" />;
  const c = d.cohort;
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Placement cell"
        title={d.college.name}
        description={`${d.students} students · ${d.sharing} sharing their progress · ${d.active_7d} active this week`}
        action={
          <div className="flex gap-2">
            <Button onClick={() => (navigator.clipboard.writeText(d.college.invite_code), toast.success("Invite code copied"))}>
              <Copy className="size-4" /> Code {d.college.invite_code}
            </Button>
            <Button variant="primary" onClick={() => setAdding(true)}><Plus className="size-4" /> Post a drive</Button>
          </div>
        }
      />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[
          ["Applications", c?.applied ?? 0],
          ["Interview rate", c?.interview_rate == null ? "—" : `${c.interview_rate}%`],
          ["Offers", d.offers],
          ["PPO conversions", d.ppo_converted],
        ].map(([k, v]) => (
          <div key={k as string} className="card p-4">
            <div className="text-[13px] text-text-2">{k}</div>
            <div className="num mt-2 text-[28px] leading-none font-semibold tracking-[-0.02em]">{v}</div>
          </div>
        ))}
      </div>

      {adding && (
        <Card className="p-5">
          <DriveForm loading={add.isPending} onCancel={() => setAdding(false)} onSubmit={(b) => add.mutate(b, { onSuccess: () => setAdding(false) })} />
        </Card>
      )}

      <div className="grid gap-6 xl:grid-cols-2 [&>*]:min-w-0">
        <CircularImport />
        <AlumniUpload />
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.4fr_1fr] [&>*]:min-w-0">
        <Card>
          <CardHeader title="Drives" description="Eligibility is checked against each student’s academics." />
          <div className="divide-y divide-border px-5 pb-2">
            {d.drives.length === 0 && <p className="py-4 text-[13px] text-subtle">No drives posted yet.</p>}
            {d.drives.map((x) => (
              <div key={x.id} className="flex flex-wrap items-center gap-3 py-3">
                <div className="min-w-0 flex-1">
                  <div className="text-[14px] font-medium">{x.company} · {x.role}</div>
                  <div className="text-[12px] text-subtle">
                    {x.eligible_students} eligible · {Object.entries(x.statuses ?? {}).map(([k, v]) => `${v} ${k.replace("_", " ")}`).join(" · ") || "no responses yet"}
                  </div>
                </div>
                <Button size="sm" variant="ghost" onClick={() => del.mutate(x.id)}>Remove</Button>
              </div>
            ))}
          </div>
        </Card>
        <Card>
          <CardHeader title="Where the cohort falls short" description="Skills most often missing in rejected or silent applications. Worth a workshop." />
          <div className="flex flex-wrap gap-2 p-5">
            {d.top_gaps.length === 0 && <p className="text-[13px] text-subtle">Not enough outcomes yet.</p>}
            {d.top_gaps.map((g) => (
              <span key={g.skill} className="inline-flex items-center gap-2 rounded-full border border-border-strong bg-accent-soft px-3 py-1.5 text-[13px]">
                {g.skill} <Badge tone="outline">{g.count}×</Badge>
              </span>
            ))}
          </div>
        </Card>
      </div>

      <Card>
        <CardHeader title="Students sharing their progress" description="Only students who opted in are listed; everyone counts in the totals above." />
        <div className="overflow-x-auto p-5">
          <table className="w-full text-[13px]">
            <thead className="text-left text-[11.5px] tracking-wide text-subtle uppercase">
              <tr>
                {["Student", "Branch", "CGPA", "Applied", "Interviews", "Offers", "PPO", "Last active"].map((h) => <th key={h} className="pb-2 font-medium">{h}</th>)}
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {d.per_student.map((s) => (
                <tr key={s.email}>
                  <td className="py-2"><div className="font-medium">{s.name}</div><div className="text-[11.5px] text-subtle">{s.email}</div></td>
                  <td className="py-2">{s.branch || "—"}</td>
                  <td className="py-2 font-mono">{s.cgpa ?? "—"}</td>
                  <td className="py-2 font-mono">{s.applications}</td>
                  <td className="py-2 font-mono">{s.interviews}</td>
                  <td className="py-2 font-mono">{s.offers}</td>
                  <td className="py-2 font-mono">{s.ppo}</td>
                  <td className="py-2 text-subtle">{s.last_active ? ago(s.last_active) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {d.per_student.length === 0 && <p className="pt-3 text-[13px] text-subtle">No students have opted in yet.</p>}
        </div>
      </Card>
    </div>
  );
}

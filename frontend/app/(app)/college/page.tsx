"use client";

import { Copy, Plus } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { AlumniUpload, CircularImport } from "@/components/campus-v2";
import { DriveForm } from "@/components/drive-form";
import { CampusJobs, PipelineBoard, StaffJoin, StaffPanel, StudentAudit, useStaffMe } from "@/components/placement-cell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { PageHeader, Skeleton } from "@/components/ui/misc";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAddDrive, useCollege, useDeleteDrive } from "@/lib/queries";

export default function CollegePage() {
  const { data: d, isLoading, error } = useCollege();
  const me = useStaffMe();
  const add = useAddDrive(true);
  const del = useDeleteDrive(true);
  const [adding, setAdding] = useState(false);
  const [tab, setTab] = useState("pipeline");
  if (error || me.error)
    return (
      <div className="space-y-6">
        <PageHeader eyebrow="Placement cell" title="College staff" description="For TPOs, heads of department and faculty running placements." />
        <StaffJoin />
      </div>
    );
  if (isLoading || !d || !me.data) return <Skeleton agent="pilot" className="min-h-96" />;
  const c = d.cohort;
  const m = me.data;
  const canDrives = m.permissions.includes("drives");
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={`Placement cell · ${m.label}${m.department && m.role !== "tpo" ? ` · ${m.department}` : ""}`}
        title={d.college.name}
        description={`${d.students} students · ${d.sharing} sharing their progress · ${d.active_7d} active this week`}
        action={
          <div className="flex gap-2">
            <Button onClick={() => (navigator.clipboard.writeText(d.college.invite_code), toast.success("Student invite code copied"))}>
              <Copy className="size-4" /> Student code {d.college.invite_code}
            </Button>
            {canDrives && (
              <Button variant="primary" onClick={() => (setTab("overview"), setAdding(true))}>
                <Plus className="size-4" /> Post a drive
              </Button>
            )}
          </div>
        }
      />
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="pipeline">Pipeline & approvals</TabsTrigger>
          <TabsTrigger value="students">Students</TabsTrigger>
          <TabsTrigger value="jobs">Jobs</TabsTrigger>
          <TabsTrigger value="overview">Drives & cohort</TabsTrigger>
          <TabsTrigger value="staff">Staff</TabsTrigger>
        </TabsList>
        <TabsContent value="pipeline" className="mt-4">
          <PipelineBoard me={m} />
        </TabsContent>
        <TabsContent value="students" className="mt-4">
          <StudentAudit />
        </TabsContent>
        <TabsContent value="jobs" className="mt-4">
          <CampusJobs me={m} />
        </TabsContent>
        <TabsContent value="staff" className="mt-4">
          <StaffPanel me={m} />
        </TabsContent>
        <TabsContent value="overview" className="mt-4 space-y-6">
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
                {canDrives && <Button size="sm" variant="ghost" onClick={() => del.mutate(x.id)}>Remove</Button>}
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

        </TabsContent>
      </Tabs>
    </div>
  );
}

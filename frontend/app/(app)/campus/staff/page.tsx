"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, UserCheck, UserX } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ROLE_LABEL, useStaffMe } from "@/components/campus/portal";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { api } from "@/lib/api";

type Member = { membership_id: string; name: string; email: string; role: keyof typeof ROLE_LABEL; status: string; email_verified: boolean; requested_at: string; assignments: { department_id: string | null; program_id: string | null; batch_id: string | null; status: string }[] };
type Assignment = { id: string; name: string; role: string; department_id: string | null; program_id: string | null; batch_id: string | null };
type Pending = { membership_id: string; name: string; status: string; department_id: string | null; program_id: string | null };

export default function StaffPage() {
  const qc = useQueryClient();
  const { data: me } = useStaffMe();
  const { data: setup } = useQuery({ queryKey: ["campus-setup"], queryFn: () => api.get<{ departments: { id: string; name: string }[] }>("/campus/staff/setup") });
  const pending = useQuery({ queryKey: ["staff-pending"], queryFn: () => api.get<Member[]>("/campus/staff/members?status=pending") });
  const active = useQuery({ queryKey: ["staff-active"], queryFn: () => api.get<Member[]>("/campus/staff/members?status=active") });
  const assigns = useQuery({ queryKey: ["staff-assign"], queryFn: () => api.get<Assignment[]>("/campus/staff/assignments") });
  const students = useQuery({ queryKey: ["students-pending"], queryFn: () => api.get<Pending[]>("/campus/staff/students-pending") });
  const refresh = () => ["staff-pending", "staff-active", "staff-assign", "students-pending"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  const decide = useMutation({ mutationFn: ({ id, action }: { id: string; action: string }) => api.post(`/campus/staff/members/${id}`, { action }), onSuccess: refresh, onError: (e: Error) => toast.error(e.message) });
  const assign = useMutation({ mutationFn: ({ id, approve }: { id: string; approve: boolean }) => api.post(`/campus/staff/assignments/${id}?approve=${approve}`), onSuccess: refresh, onError: (e: Error) => toast.error(e.message) });
  const confirmStudent = useMutation({ mutationFn: ({ id, approve }: { id: string; approve: boolean }) => api.post<{ status: string }>(`/campus/staff/students/memberships/${id}`, { approve }), onSuccess: (r) => (toast.success(r.status === "waitlisted" ? "Full: added to the waitlist" : "Done"), refresh()), onError: (e: Error) => toast.error(e.message) });
  const [code, setCode] = useState<string | null>(null);
  const rotate = useMutation({ mutationFn: () => api.post<{ code: string; expires_at: string | null }>("/campus/staff/staff-code", { expires_in_days: 30 }), onSuccess: (r) => setCode(r.code), onError: (e: Error) => toast.error(e.message) });
  const dname = (id: string | null) => setup?.departments.find((d) => d.id === id)?.name ?? "";
  const lead = me?.whole_campus;
  return (
    <div className="grid gap-6 xl:grid-cols-2 [&>*]:min-w-0">
      {lead && (
        <Card>
          <CardHeader icon={<UserCheck className="size-4" />} title="Pending staff approvals" description="Institutional email confirmed; no data access until you approve." />
          <div className="divide-y divide-border">
            {pending.data?.length === 0 && <p className="p-5 text-[13px] text-text-3">Nobody waiting.</p>}
            {pending.data?.map((m) => (
              <div key={m.membership_id} className="flex flex-wrap items-center gap-2 px-5 py-3">
                <div className="min-w-0 flex-1">
                  <div className="text-[14px] font-medium">{m.name} <Badge>{ROLE_LABEL[m.role] ?? m.role}</Badge></div>
                  <div className="text-[12px] text-text-3">{m.email} · {m.assignments.map((a) => dname(a.department_id)).filter(Boolean).join(", ") || "no department picked"}</div>
                </div>
                <Button size="sm" variant="primary" onClick={() => confirm(`Give ${m.name} ${ROLE_LABEL[m.role]} access?`) && decide.mutate({ id: m.membership_id, action: "approve" })}>Approve</Button>
              </div>
            ))}
          </div>
        </Card>
      )}
      <Card>
        <CardHeader title="Assignment requests" description="Departments, programmes or batches staff asked for. Nobody approves their own." />
        <div className="divide-y divide-border">
          {assigns.data?.length === 0 && <p className="p-5 text-[13px] text-text-3">None.</p>}
          {assigns.data?.map((a) => (
            <div key={a.id} className="flex items-center gap-2 px-5 py-3 text-[13.5px]">
              <span className="flex-1">{a.name} → {dname(a.department_id) || "a programme or batch"}</span>
              <Button size="sm" onClick={() => assign.mutate({ id: a.id, approve: true })}>Approve</Button>
              <Button size="sm" variant="ghost" onClick={() => assign.mutate({ id: a.id, approve: false })}>Decline</Button>
            </div>
          ))}
        </div>
      </Card>
      <Card>
        <CardHeader title="Students waiting to be confirmed" description="Students who picked their programme themselves stay out of every list until staff of that programme confirm." />
        <div className="divide-y divide-border">
          {students.data?.length === 0 && <p className="p-5 text-[13px] text-text-3">None.</p>}
          {students.data?.map((s) => (
            <div key={s.membership_id} className="flex items-center gap-2 px-5 py-3 text-[13.5px]">
              <span className="flex-1">{s.name} · {dname(s.department_id)} {s.status === "waitlisted" && <Badge tone="warning">Waitlisted</Badge>}</span>
              <Button size="sm" onClick={() => confirmStudent.mutate({ id: s.membership_id, approve: true })}>Confirm</Button>
              <Button size="sm" variant="ghost" onClick={() => confirmStudent.mutate({ id: s.membership_id, approve: false })}>Decline</Button>
            </div>
          ))}
        </div>
      </Card>
      {lead && (
        <Card>
          <CardHeader icon={<KeyRound className="size-4" />} title="Staff and the staff code" description="Unlimited staff on every plan. A new code replaces the old one and is shown only once." action={<Button size="sm" loading={rotate.isPending} onClick={() => rotate.mutate()}>New staff code</Button>} />
          {code && <p className="mx-5 mb-3 rounded-[var(--radius-control)] border border-border bg-surface-2 px-3 py-2 font-mono text-[15px]">{code} <span className="ml-2 font-sans text-[12px] text-text-3">Copy it now: it isn't shown again.</span></p>}
          <div className="divide-y divide-border">
            {active.data?.map((m) => (
              <div key={m.membership_id} className="flex items-center gap-2 px-5 py-3 text-[13.5px]">
                <span className="flex-1">{m.name} <span className="text-text-3">· {ROLE_LABEL[m.role] ?? m.role}</span></span>
                <Button size="sm" variant="ghost" onClick={() => confirm(`Remove ${m.name}'s access? Their sessions end at once.`) && decide.mutate({ id: m.membership_id, action: "deactivate" })}><UserX /> Remove</Button>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

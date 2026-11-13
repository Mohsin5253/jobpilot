"use client";

import { useQuery } from "@tanstack/react-query";
import { BadgeCheck, Download, Search, X } from "lucide-react";
import { useState } from "react";

import type { Entry } from "@/components/campus/profile";
import { KeysetList, useStaffMe } from "@/components/campus/portal";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";

type Row = { id: string; student_id: string; name: string; department_id: string | null; program_id: string | null; batch_id: string | null; score: number | null; score_scale: { type: string; max?: number } | null; pending_subjects: number | null; graduation_year: number | null; self_reported_academics: boolean; shares_with_college: boolean };
type Setup = { departments: { id: string; name: string }[]; programs: { id: string; department_id: string; specialisation: string; degree_id: string }[]; batches: { id: string; program_id: string; admission_year: number; graduation_year: number }[] };

export default function StudentsPage() {
  const { data: me } = useStaffMe();
  const { data: setup } = useQuery({ queryKey: ["campus-setup"], queryFn: () => api.get<Setup>("/campus/staff/setup") });
  const [q, setQ] = useState("");
  const [term, setTerm] = useState("");
  const [dept, setDept] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const qs = new URLSearchParams({ ...(term && { q: term }), ...(dept && { department_id: dept }) }).toString();
  const dname = (id: string | null) => setup?.departments.find((d) => d.id === id)?.name ?? "";
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <form onSubmit={(e) => (e.preventDefault(), setTerm(q.trim()))} className="flex min-w-60 flex-1 gap-2">
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Search by name or ${me?.campus.student_id_label ?? "ID"}`} aria-label="Search students" />
          <button type="submit" className="grid size-10 place-items-center rounded-[var(--radius-control)] border border-border" aria-label="Search"><Search className="size-4" /></button>
        </form>
        <select value={dept} onChange={(e) => setDept(e.target.value)} className="h-10 rounded-[var(--radius-control)] border border-border bg-surface px-3 text-[13px]" aria-label="Department">
          <option value="">All departments in your scope</option>
          {setup?.departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
        <a href={`/api/campus/staff/export.csv${dept ? `?department_id=${dept}` : ""}`} className="inline-flex h-10 items-center gap-1.5 rounded-[var(--radius-control)] border border-border px-3 text-[13px]"><Download className="size-4" /> Export (logged)</a>
      </div>
      <KeysetList<Row>
        url={`/campus/staff/students${qs ? `?${qs}` : ""}`}
        queryKey={["campus-students", qs]}
        empty="No students in your scope yet. Import the roster to add them."
        render={(r) => (
          <button type="button" onClick={() => setOpen(r.id)} className="flex h-full w-full items-center gap-3 px-4 text-left hover:bg-elevated">
            <div className="min-w-0 flex-1">
              <div className="truncate text-[14px] font-medium">{r.name}</div>
              <div className="truncate text-[12px] text-text-3">{r.student_id} · {dname(r.department_id)}{r.graduation_year ? ` · ${r.graduation_year}` : ""}</div>
            </div>
            {r.score != null && <span className="num text-[13px] text-text-2">{r.score}{r.score_scale?.max ? `/${r.score_scale.max}` : ""}</span>}
            {r.self_reported_academics && <Badge tone="warning">Self-reported</Badge>}
            {r.shares_with_college && <Badge tone="success">Shares</Badge>}
          </button>
        )}
      />
      {open && <StudentDrawer id={open} onClose={() => setOpen(null)} label={me?.campus.pending_subjects_label ?? null} />}
    </div>
  );
}

function StudentDrawer({ id, onClose, label }: { id: string; onClose: () => void; label: string | null }) {
  const { data } = useQuery({ queryKey: ["campus-student", id], queryFn: () => api.get<{ record: Row; achievements: Entry[]; note: string | null }>(`/campus/staff/students/${id}`) });
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40" onClick={onClose}>
      <aside onClick={(e) => e.stopPropagation()} className="h-full w-full max-w-lg overflow-y-auto bg-surface p-5 shadow-xl" aria-label="Student details">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-[17px] font-semibold">{data?.record.name ?? "Loading…"}</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="grid size-10 place-items-center"><X className="size-4" /></button>
        </div>
        {data && (
          <div className="space-y-4 text-[13.5px]">
            <dl className="grid grid-cols-2 gap-3">
              <div><dt className="text-[12px] text-text-3">ID</dt><dd>{data.record.student_id}</dd></div>
              {data.record.score != null && <div><dt className="text-[12px] text-text-3">Score ({data.record.score_scale?.type})</dt><dd>{data.record.score}{data.record.score_scale?.max ? ` / ${data.record.score_scale.max}` : ""}</dd></div>}
              {label && data.record.pending_subjects != null && <div><dt className="text-[12px] text-text-3">{label}</dt><dd>{data.record.pending_subjects}</dd></div>}
              {data.record.graduation_year && <div><dt className="text-[12px] text-text-3">Graduating</dt><dd>{data.record.graduation_year}</dd></div>}
            </dl>
            {data.note && <p className="rounded-[var(--radius-card)] border border-border px-3 py-2 text-[12.5px] text-text-2">{data.note}</p>}
            {data.achievements.map((a) => (
              <div key={a.id} className="rounded-[var(--radius-card)] border border-border p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">{a.title}</span>
                  <Badge tone={a.status === "verified" ? "success" : a.status === "rejected" ? "danger" : "neutral"}>{a.status === "verified" && <BadgeCheck className="size-3" />} {a.label}</Badge>
                </div>
                <div className="text-[12.5px] text-text-2">{a.kind} · {a.organisation}</div>
                {a.proof_url && <a href={a.proof_url} target="_blank" rel="noreferrer" className="text-[12.5px] text-cobalt-text hover:underline">Proof</a>}
              </div>
            ))}
          </div>
        )}
      </aside>
    </div>
  );
}

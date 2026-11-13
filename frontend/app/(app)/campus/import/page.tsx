"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { FileSpreadsheet } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { useStaffMe } from "@/components/campus/portal";
import { Card, CardHeader } from "@/components/ui/card";
import { api } from "@/lib/api";

type Job = { id: string; status: string; progress: number; total: number; result: { imported?: number; rows?: number }; error_count: number; error: string | null };

export default function ImportPage() {
  const { data: me } = useStaffMe();
  const [job, setJob] = useState<string | null>(null);
  const upload = useMutation({
    mutationFn: (f: File) => {
      const fd = new FormData();
      fd.set("file", f);
      return api.post<{ job_id: string }>("/campus/staff/roster/import", fd);
    },
    onSuccess: (r) => setJob(r.job_id),
    onError: (e: Error) => toast.error(e.message),
  });
  const status = useQuery({ queryKey: ["campus-job", job], queryFn: () => api.get<Job>(`/campus/staff/jobs/${job}`), enabled: !!job, refetchInterval: (q) => (q.state.data && ["done", "failed"].includes(q.state.data.status) ? false : 1500) });
  const j = status.data;
  return (
    <Card>
      <CardHeader icon={<FileSpreadsheet className="size-4" />} title="Import your roster" description="CSV or Excel, up to 1 lakh+ rows. Rows become college records and invites, never accounts: a student claims theirs with their college email." />
      <div className="space-y-4 p-5 text-[13.5px]">
        <p className="text-text-2">
          Columns: <b>{me?.campus.student_id_label ?? "Student ID"}</b>, <b>Name</b>, Department, Degree, Admission year or Graduation year, Semester/Year, Score{me?.campus.score_scale ? ` (${me.campus.score_scale.type}${me.campus.score_scale.max ? ` out of ${me.campus.score_scale.max}` : ""})` : ""}
          {me?.campus.pending_subjects_label ? `, ${me.campus.pending_subjects_label}` : ""}, College email, and any custom fields you set up. Department and degree names must match Setup.
        </p>
        <label className="inline-flex cursor-pointer items-center gap-2 rounded-[var(--radius-control)] border border-border px-4 py-2.5 hover:bg-elevated">
          Choose a .csv or .xlsx file
          <input type="file" accept=".csv,.xlsx" className="sr-only" onChange={(e) => e.target.files?.[0] && upload.mutate(e.target.files[0])} />
        </label>
        {j && (
          <div className="space-y-2">
            <div className="h-2 overflow-hidden rounded-full bg-surface-2">
              <div className="h-full bg-cobalt transition-[width]" style={{ width: `${j.total ? Math.min(100, (j.progress / j.total) * 100) : j.status === "done" ? 100 : 10}%` }} />
            </div>
            <p>
              {j.status === "done" ? `Imported ${j.result.imported ?? 0} of ${j.result.rows ?? 0} rows.` : j.status === "failed" ? `Failed: ${j.error}` : `Working… ${j.progress.toLocaleString("en-IN")} rows so far`}
              {j.error_count > 0 && (
                <>
                  {" "}{j.error_count} rows need fixing: <a href={`/api/campus/staff/jobs/${j.id}/errors.csv`} className="text-cobalt-text hover:underline">download the error report</a>.
                </>
              )}
            </p>
          </div>
        )}
      </div>
    </Card>
  );
}

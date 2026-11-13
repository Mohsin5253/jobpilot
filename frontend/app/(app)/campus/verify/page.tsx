"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import type { Entry } from "@/components/campus/profile";
import { KeysetList } from "@/components/campus/portal";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";

type Row = Entry & { student: string };
const sel = "h-10 rounded-[var(--radius-control)] border border-border bg-surface px-3 text-[13px]";

/** Entries of students who share with the college, in your department(s). Bulk select still needs an explicit confirm. */
export default function VerifyPage() {
  const qc = useQueryClient();
  const [status, setStatus] = useState("self_reported");
  const [kind, setKind] = useState("");
  const [level, setLevel] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [reason, setReason] = useState("");
  const qs = new URLSearchParams({ status, ...(kind && { kind }), ...(level && { level }) }).toString();
  const done = () => (setPicked([]), qc.invalidateQueries({ queryKey: ["campus-verify"] }));
  const one = useMutation({ mutationFn: ({ id, decision }: { id: string; decision: string }) => api.post(`/campus/staff/achievements/${id}/verify`, { decision, reason }), onSuccess: done, onError: (e: Error) => toast.error(e.message) });
  const bulk = useMutation({ mutationFn: (decision: string) => api.post("/campus/staff/achievements/bulk", { ids: picked, decision, reason, confirm: true }), onSuccess: done, onError: (e: Error) => toast.error(e.message) });
  const toggle = (id: string) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <select value={status} onChange={(e) => setStatus(e.target.value)} className={sel} aria-label="Status"><option value="self_reported">Self-reported</option><option value="verified">Verified</option><option value="rejected">Rejected</option></select>
        <select value={kind} onChange={(e) => setKind(e.target.value)} className={sel} aria-label="Type"><option value="">All types</option><option value="internship">Internships</option><option value="role">Roles</option><option value="award">Awards</option></select>
        <select value={level} onChange={(e) => setLevel(e.target.value)} className={sel} aria-label="Level"><option value="">Any level</option>{["college", "inter_college", "state", "national", "international"].map((l) => <option key={l} value={l}>{l.replace("_", "-")}</option>)}</select>
        <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (needed to reject; the student sees it)" className="min-w-60 flex-1" aria-label="Reason" />
      </div>
      {picked.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-[var(--radius-card)] border border-border px-4 py-2.5 text-[13px]">
          {picked.length} selected
          <Button size="sm" variant="primary" loading={bulk.isPending} onClick={() => confirm(`Mark ${picked.length} entries verified?`) && bulk.mutate("verified")}><Check /> Verify selected</Button>
          <Button size="sm" variant="danger" loading={bulk.isPending} disabled={reason.trim().length < 3} onClick={() => confirm(`Reject ${picked.length} entries with this reason?`) && bulk.mutate("rejected")}><X /> Reject selected</Button>
        </div>
      )}
      <KeysetList<Row>
        url={`/campus/staff/achievements?${qs}`}
        queryKey={["campus-verify", qs]}
        rowHeight={96}
        empty="Nothing to verify. Entries appear here when students in your department share them with the college."
        render={(a) => (
          <div className="flex h-full items-center gap-3 px-4">
            {status === "self_reported" && <input type="checkbox" checked={picked.includes(a.id)} onChange={() => toggle(a.id)} aria-label={`Select ${a.title}`} className="size-5" />}
            <div className="min-w-0 flex-1">
              <div className="truncate text-[14px] font-medium">{a.title} <span className="font-normal text-text-3">· {a.student}</span></div>
              <div className="truncate text-[12.5px] text-text-2">{a.kind} · {a.organisation}{a.level ? ` · ${a.level}` : ""}{a.position ? ` · ${a.position}` : ""}</div>
              {!!a.verifier_flags.length && <div className="truncate text-[12px] text-[var(--error)]">Offer flags: {a.verifier_flags.join("; ")}</div>}
            </div>
            {a.proof_url ? <a href={a.proof_url} target="_blank" rel="noreferrer" className="text-[12.5px] text-cobalt-text hover:underline">Proof</a> : <Badge tone="outline">No proof</Badge>}
            {status === "self_reported" && (
              <div className="flex gap-1">
                <Button size="sm" onClick={() => one.mutate({ id: a.id, decision: "verified" })} aria-label="Verify"><Check /></Button>
                <Button size="sm" variant="danger" disabled={reason.trim().length < 3} onClick={() => one.mutate({ id: a.id, decision: "rejected" })} aria-label="Reject"><X /></Button>
              </div>
            )}
          </div>
        )}
      />
    </div>
  );
}

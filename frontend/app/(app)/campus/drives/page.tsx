"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { useStaffMe } from "@/components/campus/portal";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/input";
import { api } from "@/lib/api";

type Rule = { id?: string; type: string; values?: (string | number)[]; value?: number; key?: string };
type Drive = { id: string; company: string; role: string; kind: string; compensation: string; register_by: string | null; rounds: { name: string; type: string }[]; rules: Rule[]; eligible_in_scope: number };
type Setup = { departments: { id: string; name: string }[]; programs: { id: string; specialisation: string; department_id: string; field_code: string | null }[]; fields: { code: string; level: string; name: string }[]; custom_fields: { key: string; label: string; type: string }[] };
type Templates = { types: Record<string, { label: string }>; defaults: string[] };

const RULE_TYPES: [string, string][] = [
  ["department_in", "Department is one of"],
  ["field_in", "Field of study is one of"],
  ["level_in", "Degree level is"],
  ["score_gte", "Score at least (your college's scale)"],
  ["pending_subjects_lte", "Pending subjects at most"],
  ["graduation_year_in", "Graduating in"],
  ["term_in", "Current year / semester is"],
  ["custom_yes", "Custom: must be Yes"],
];
const sel = "h-10 w-full rounded-[var(--radius-control)] border border-border bg-surface px-3 text-[13px]";

export default function DrivesPage() {
  const qc = useQueryClient();
  const { data: me } = useStaffMe();
  const drives = useQuery({ queryKey: ["campus-drives"], queryFn: () => api.get<Drive[]>("/campus/staff/drives") });
  const { data: setup } = useQuery({ queryKey: ["campus-setup"], queryFn: () => api.get<Setup>("/campus/staff/setup") });
  const [open, setOpen] = useState(false);
  const evaluate = useMutation({ mutationFn: (id: string) => api.post(`/campus/staff/drives/${id}/evaluate`), onSuccess: () => toast.success("Checking eligibility in the background"), onError: (e: Error) => toast.error(e.message) });
  return (
    <div className="space-y-4">
      <div className="flex justify-end"><Button variant="primary" onClick={() => setOpen(!open)}><Plus /> New drive</Button></div>
      {open && setup && <DriveBuilder setup={setup} scaleLabel={me?.campus.score_scale ? `${me.campus.score_scale.type}${me.campus.score_scale.max ? ` out of ${me.campus.score_scale.max}` : ""}` : "set your scale in Setup"} pendingLabel={me?.campus.pending_subjects_label ?? null} onDone={() => (setOpen(false), qc.invalidateQueries({ queryKey: ["campus-drives"] }))} />}
      {drives.data?.map((d) => (
        <div key={d.id} className="card flex flex-wrap items-center gap-3 p-4">
          <div className="min-w-0 flex-1">
            <div className="text-[15px] font-semibold">{d.company} · {d.role}</div>
            <div className="text-[12.5px] text-text-2">{d.rounds.map((r) => r.name).join(" → ") || "Rounds not set"}{d.compensation ? ` · ${d.compensation}` : ""}</div>
            <div className="mt-1 flex flex-wrap gap-1">{d.rules.map((r) => <Badge key={r.id} tone="outline">{r.id}: {r.type.replaceAll("_", " ")} {r.value ?? (r.values ?? []).length}</Badge>)}</div>
          </div>
          <div className="text-right"><div className="num text-[20px] font-semibold">{d.eligible_in_scope.toLocaleString("en-IN")}</div><div className="text-[12px] text-text-3">eligible in your scope</div></div>
          <Button size="sm" variant="ghost" onClick={() => evaluate.mutate(d.id)}><RefreshCw /> Re-check</Button>
        </div>
      ))}
      {drives.data?.length === 0 && <p className="card p-8 text-center text-[14px] text-text-2">No drives yet.</p>}
    </div>
  );
}

function DriveBuilder({ setup, scaleLabel, pendingLabel, onDone }: { setup: Setup; scaleLabel: string; pendingLabel: string | null; onDone: () => void }) {
  const [company, setCompany] = useState("");
  const [role, setRole] = useState("");
  const [field, setField] = useState("");
  const [rules, setRules] = useState<Rule[]>([]);
  const [rounds, setRounds] = useState<string[]>([]);
  const tpl = useQuery({ queryKey: ["round-tpl", field, role], queryFn: () => api.get<Templates>(`/campus/staff/round-templates?field_code=${field}&role=${encodeURIComponent(role)}`) });
  const save = useMutation({
    mutationFn: () => api.post("/campus/staff/drives", { company, role, rules, rounds: (rounds.length ? rounds : tpl.data?.defaults ?? []).map((t) => ({ name: tpl.data?.types[t]?.label ?? t, type: t })) }),
    onSuccess: () => (toast.success("Drive created: eligibility is being checked in the background"), onDone()),
    onError: (e: Error) => toast.error(e.message),
  });
  const set = (i: number, r: Rule) => setRules(rules.map((x, j) => (j === i ? r : x)));
  return (
    <Card>
      <CardHeader title="New drive" description="Eligibility is a list of rules, checked for every student in the background (never in this page)." />
      <div className="space-y-4 p-5">
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Company"><Input value={company} onChange={(e) => setCompany(e.target.value)} /></Field>
          <Field label="Role"><Input value={role} onChange={(e) => setRole(e.target.value)} placeholder="Graduate trainee, Staff nurse, Legal associate…" /></Field>
          <Field label="Field (for round templates)">
            <select value={field} onChange={(e) => setField(e.target.value)} className={sel}><option value="">Any</option>{setup.fields.filter((f) => f.level !== "detailed").map((f) => <option key={f.code} value={f.code}>{f.code} · {f.name}</option>)}</select>
          </Field>
        </div>
        <div className="space-y-2">
          <div className="text-[13px] font-medium">Rounds</div>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(tpl.data?.types ?? {}).map(([k, v]) => {
              const on = (rounds.length ? rounds : tpl.data?.defaults ?? []).includes(k);
              return (
                <button key={k} type="button" onClick={() => setRounds(on ? (rounds.length ? rounds : tpl.data!.defaults).filter((x) => x !== k) : [...(rounds.length ? rounds : tpl.data!.defaults), k])} className={`rounded-full border px-2.5 py-1 text-[12.5px] ${on ? "border-[var(--cobalt)] text-cobalt-text" : "border-border text-text-2"}`}>
                  {v.label}
                </button>
              );
            })}
          </div>
        </div>
        <div className="space-y-2">
          <div className="text-[13px] font-medium">Eligibility rules</div>
          {rules.map((r, i) => (
            <div key={i} className="grid gap-2 sm:grid-cols-[1.2fr_2fr_auto]">
              <select value={r.type} onChange={(e) => set(i, { type: e.target.value })} className={sel}>{RULE_TYPES.map(([v, l]) => <option key={v} value={v}>{l.replace("Pending subjects", pendingLabel ?? "Pending subjects")}</option>)}</select>
              {r.type === "department_in" ? (
                <select multiple value={(r.values as string[]) ?? []} onChange={(e) => set(i, { ...r, values: Array.from(e.target.selectedOptions).map((o) => o.value) })} className={`${sel} h-24`}>{setup.departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</select>
              ) : r.type === "field_in" ? (
                <select multiple value={(r.values as string[]) ?? []} onChange={(e) => set(i, { ...r, values: Array.from(e.target.selectedOptions).map((o) => o.value) })} className={`${sel} h-24`}>{setup.fields.map((f) => <option key={f.code} value={f.code}>{f.code} · {f.name}</option>)}</select>
              ) : r.type === "custom_yes" ? (
                <select value={r.key ?? ""} onChange={(e) => set(i, { ...r, key: e.target.value })} className={sel}><option value="">Pick a custom field</option>{setup.custom_fields.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}</select>
              ) : r.type === "score_gte" || r.type === "pending_subjects_lte" ? (
                <Input type="number" step="any" value={r.value ?? ""} onChange={(e) => set(i, { ...r, value: Number(e.target.value) })} placeholder={r.type === "score_gte" ? scaleLabel : "0"} />
              ) : (
                <Input value={(r.values ?? []).join(", ")} onChange={(e) => set(i, { ...r, values: e.target.value.split(",").map((x) => x.trim()).filter(Boolean).map(Number) })} placeholder="e.g. 2026, 2027 or 6, 7" />
              )}
              <Button size="sm" variant="ghost" onClick={() => setRules(rules.filter((_, j) => j !== i))} aria-label="Remove rule"><Trash2 /></Button>
            </div>
          ))}
          <Button size="sm" onClick={() => setRules([...rules, { type: "department_in", values: [] }])}><Plus /> Add a rule</Button>
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onDone}>Cancel</Button>
          <Button variant="primary" loading={save.isPending} disabled={company.length < 2 || role.length < 2} onClick={() => save.mutate()}>Create drive</Button>
        </div>
      </div>
    </Card>
  );
}

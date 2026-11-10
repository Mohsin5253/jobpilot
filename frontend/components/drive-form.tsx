"use client";

import { Plus, X } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Field, Input, Textarea } from "@/components/ui/input";

type RoundType = "aptitude" | "coding" | "technical" | "group_discussion" | "hr";
const TYPES: [RoundType, string][] = [
  ["aptitude", "Aptitude"],
  ["coding", "Coding"],
  ["technical", "Technical interview"],
  ["group_discussion", "Group discussion"],
  ["hr", "HR"],
];

/** Add an on-campus drive: company, eligibility, deadline and rounds. Used by students and placement officers. */
export function DriveForm({ onSubmit, loading, onCancel }: { onSubmit: (body: Record<string, unknown>) => void; loading?: boolean; onCancel: () => void }) {
  const [rounds, setRounds] = useState<{ name: string; type: RoundType; date: string }[]>([{ name: "Online test", type: "aptitude", date: "" }]);

  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    const num = (k: string) => (fd.get(k) ? Number(fd.get(k)) : null);
    const list = (k: string) => String(fd.get(k) || "").split(",").map((x) => x.trim()).filter(Boolean);
    onSubmit({
      company: fd.get("company"),
      role: fd.get("role"),
      kind: fd.get("kind"),
      compensation: fd.get("compensation") || "",
      register_by: fd.get("register_by") ? new Date(String(fd.get("register_by"))).toISOString() : null,
      eligibility: { min_cgpa: num("min_cgpa"), max_backlogs: num("max_backlogs"), branches: list("branches"), grad_years: list("grad_years").map(Number).filter(Boolean) },
      rounds: rounds.filter((r) => r.name.trim()).map((r) => ({ ...r, date: r.date ? new Date(r.date).toISOString() : null })),
      notes: fd.get("notes") || "",
    });
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Company"><Input name="company" required placeholder="Acme Analytics" /></Field>
        <Field label="Role"><Input name="role" required placeholder="Data Analyst Intern" /></Field>
        <Field label="Type">
          <select name="kind" className="h-10 w-full rounded-[var(--radius-control)] border border-border bg-surface text-text px-3 text-sm">
            <option value="internship">Internship</option>
            <option value="full_time">Full-time</option>
          </select>
        </Field>
        <Field label="Stipend / CTC"><Input name="compensation" placeholder="₹30k / month" /></Field>
        <Field label="Register by"><Input name="register_by" type="datetime-local" /></Field>
        <Field label="Minimum CGPA"><Input name="min_cgpa" type="number" step="0.1" min={0} max={10} placeholder="7.0" /></Field>
        <Field label="Branches" hint="Comma-separated; empty = all"><Input name="branches" placeholder="CSE, IT, AI&DS" /></Field>
        <Field label="Batch (graduation years)"><Input name="grad_years" placeholder="2027" /></Field>
        <Field label="Max active backlogs"><Input name="max_backlogs" type="number" min={0} placeholder="0" /></Field>
      </div>
      <div>
        <div className="mb-2 text-[13px] font-medium">Rounds</div>
        <div className="space-y-2">
          {rounds.map((r, i) => (
            <div key={i} className="grid grid-cols-[1fr_150px_190px_auto] gap-2">
              <Input value={r.name} onChange={(e) => setRounds(rounds.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} placeholder="Round name" />
              <select value={r.type} onChange={(e) => setRounds(rounds.map((x, j) => (j === i ? { ...x, type: e.target.value as RoundType } : x)))} className="h-10 rounded-[var(--radius-control)] border border-border bg-surface text-text px-2 text-sm">
                {TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
              <Input type="datetime-local" value={r.date} onChange={(e) => setRounds(rounds.map((x, j) => (j === i ? { ...x, date: e.target.value } : x)))} />
              <button type="button" aria-label="Remove round" onClick={() => setRounds(rounds.filter((_, j) => j !== i))} className="grid size-10 place-items-center rounded-full text-subtle hover:text-danger">
                <X className="size-4" />
              </button>
            </div>
          ))}
        </div>
        <Button type="button" size="sm" variant="ghost" className="mt-2" onClick={() => setRounds([...rounds, { name: "", type: "technical", date: "" }])}>
          <Plus className="size-3.5" /> Add round
        </Button>
      </div>
      <Field label="Notes"><Textarea name="notes" rows={2} placeholder="Venue, dress code, documents to carry…" /></Field>
      <div className="flex gap-2">
        <Button type="submit" variant="primary" loading={loading}>Save drive</Button>
        <Button type="button" variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
    </form>
  );
}

"use client";

import { Building2, Check, Send } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button, buttonClass } from "@/components/ui/button";
import { Field, Input, Textarea } from "@/components/ui/input";
import { CAMPUS_PLANS, type CampusPlan } from "@/lib/campus-pricing";
import { cn } from "@/lib/utils";

/** The four campus plans as cards. `compact` drops the feature lists (used inside Billing). */
export function CampusPlans({ compact = false, onPick }: { compact?: boolean; onPick?: (p: CampusPlan["key"]) => void }) {
  return (
    <div className={cn("grid gap-4", compact ? "sm:grid-cols-2 xl:grid-cols-4" : "md:grid-cols-2 xl:grid-cols-4")}>
      {CAMPUS_PLANS.map((p) => (
        <div key={p.key} className={cn("card flex h-full flex-col p-5", p.highlight && "border-[color-mix(in_oklab,var(--cobalt)_45%,transparent)] shadow-[0_0_0_1px_color-mix(in_oklab,var(--cobalt)_25%,transparent)]")}>
          <div className="flex items-center justify-between gap-2">
            <h3 className="eyebrow">{p.name}</h3>
            {p.highlight && <Badge tone="accent">Most colleges</Badge>}
          </div>
          <div className="mt-3">
            <span className="num text-[32px] leading-none font-semibold tracking-[-0.03em]">{p.price}</span>
            <span className="ml-1.5 text-[13px] text-text-3">{p.per}</span>
            <p className="mt-2 text-[12.5px] text-text-2">{p.note}</p>
            <p className="mt-1 text-[12.5px] text-text-3">Best for: {p.bestFor}</p>
          </div>
          {!compact && (
            <ul className="mt-4 mb-6 space-y-2 text-[13.5px]">
              {p.features.map((f) => (
                <li key={f} className="flex gap-2 text-text-2">
                  <Check className="mt-0.5 size-4 shrink-0 text-cobalt-text" />
                  <span>{f}</span>
                </li>
              ))}
            </ul>
          )}
          <div className="mt-auto pt-3">
            {onPick ? (
              <Button className="w-full" variant={p.highlight ? "primary" : "secondary"} onClick={() => onPick(p.key)}>
                {p.cta}
              </Button>
            ) : (
              <a href={`/campus-pricing?plan=${p.key}#enquire`} className={buttonClass({ variant: p.highlight ? "primary" : "secondary", className: "w-full" })}>
                {p.cta}
              </a>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

/** "Ask for a college workspace": stored for the JobPilot team, who reply by email. */
export function CampusEnquiry({ initialPlan = "" }: { initialPlan?: string }) {
  const [f, setF] = useState({ college: "", name: "", email: "", role: "TPO", students: "", plan: initialPlan, message: "" });
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }));
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await fetch("/api/campus/leads", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ ...f, students: f.students ? Number(f.students) : null }),
      });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail?.[0]?.msg ?? "Couldn't send. Check the fields and try again.");
      setSent(true);
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  if (sent)
    return (
      <div className="card flex items-start gap-3 p-6">
        <Building2 className="mt-0.5 size-5 text-cobalt-text" />
        <div>
          <div className="font-medium">Thanks, we&rsquo;ve got it.</div>
          <p className="mt-1 text-[14px] text-text-2">We&rsquo;ll email {f.email} within one working day to set up your college workspace.</p>
        </div>
      </div>
    );
  return (
    <form onSubmit={submit} className="card grid gap-3 p-6 sm:grid-cols-2">
      <Field label="College" className="sm:col-span-2">
        <Input required minLength={2} value={f.college} onChange={set("college")} placeholder="e.g. Government College of Engineering, Pune" />
      </Field>
      <Field label="Your name">
        <Input required minLength={2} value={f.name} onChange={set("name")} />
      </Field>
      <Field label="Work email">
        <Input required type="email" value={f.email} onChange={set("email")} placeholder="tpo@yourcollege.edu.in" />
      </Field>
      <Field label="Your role">
        <select value={f.role} onChange={set("role")} className="h-10 rounded-[var(--radius-control)] border border-border bg-transparent px-3 text-[14px]">
          {["TPO", "HOD", "Faculty", "Principal / Director", "Other"].map((r) => (
            <option key={r}>{r}</option>
          ))}
        </select>
      </Field>
      <Field label="Students in the placement batch">
        <Input type="number" min={1} value={f.students} onChange={set("students")} placeholder="e.g. 600" />
      </Field>
      <Field label="Plan">
        <select value={f.plan} onChange={set("plan")} className="h-10 rounded-[var(--radius-control)] border border-border bg-transparent px-3 text-[14px]">
          <option value="">Not sure yet</option>
          {CAMPUS_PLANS.map((p) => (
            <option key={p.key} value={p.key}>
              {p.name}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Anything we should know" className="sm:col-span-2">
        <Textarea rows={3} value={f.message} onChange={set("message")} placeholder="Departments, placement season dates, recruiters you work with…" />
      </Field>
      <div className="sm:col-span-2">
        <Button type="submit" variant="primary" loading={busy}>
          <Send /> Send enquiry
        </Button>
        <p className="mt-2 text-[12px] text-text-3">We use these details only to reply to you about a college workspace.</p>
      </div>
    </form>
  );
}

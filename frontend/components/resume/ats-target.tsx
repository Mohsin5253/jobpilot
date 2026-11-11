"use client";

import { useQuery } from "@tanstack/react-query";

import { Field, Input, Textarea } from "@/components/ui/input";
import { Segmented } from "@/components/ui/misc";
import { api } from "@/lib/api";
import { useMatches } from "@/lib/queries";
import type { Match } from "@/lib/types";

export type Target = { kind: "field" | "match" | "paste"; industry: string; matchId: string; title: string; description: string };

export const emptyTarget = (matchId?: string | null): Target => ({ kind: matchId ? "match" : "field", industry: "", matchId: matchId ?? "", title: "", description: "" });

export function targetBody(t: Target) {
  return {
    industry: t.industry || null,
    ...(t.kind === "match" && t.matchId ? { match_id: t.matchId } : {}),
    ...(t.kind === "paste" ? { job_title: t.title, job_description: t.description } : {}),
  };
}

const selectCls = "h-9 w-full rounded-[var(--radius-control)] border border-border bg-elevated px-2.5 text-[13.5px] text-text";

/** What to score against: a field (industry rules), one of your matches, or a pasted job description. */
export function AtsTarget({ value, onChange }: { value: Target; onChange: (t: Target) => void }) {
  const { data: industries } = useQuery({ queryKey: ["ats-industries"], queryFn: () => api.get<{ key: string; name: string }[]>("/ats/industries"), staleTime: Infinity });
  const { data: matches } = useMatches({ limit: 60, sort: "score" });
  // A job opened from its own page may not be in the top 60: load it so the dropdown can show it.
  const listed = !value.matchId || !!matches?.items.some((m) => m.id === value.matchId);
  const { data: picked } = useQuery({ queryKey: ["match", value.matchId], queryFn: () => api.get<Match>(`/matches/${value.matchId}`), enabled: !!matches && !listed });
  return (
    <div className="space-y-3">
      <Segmented
        value={value.kind}
        onChange={(kind) => onChange({ ...value, kind })}
        options={[
          { value: "field", label: "A field" },
          { value: "match", label: "One of my jobs" },
          { value: "paste", label: "Paste a job" },
        ]}
      />
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Industry rules">
          <select className={selectCls} value={value.industry} onChange={(e) => onChange({ ...value, industry: e.target.value })} aria-label="Industry">
            <option value="">{value.kind === "field" ? "Detect from my resume" : "Detect from the job"}</option>
            {industries?.map((i) => (
              <option key={i.key} value={i.key}>
                {i.name}
              </option>
            ))}
          </select>
        </Field>
        {value.kind === "match" && (
          <Field label="Job">
            <select className={selectCls} value={value.matchId} onChange={(e) => onChange({ ...value, matchId: e.target.value })} aria-label="Job">
              <option value="">Choose a job…</option>
              {!listed && picked && (
                <option value={picked.id}>
                  {picked.job.title} · {picked.job.company}
                </option>
              )}
              {matches?.items.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.job.title} · {m.job.company}
                </option>
              ))}
            </select>
          </Field>
        )}
        {value.kind === "paste" && (
          <Field label="Job title">
            <Input value={value.title} onChange={(e) => onChange({ ...value, title: e.target.value })} placeholder="e.g. Data Analyst Intern" />
          </Field>
        )}
      </div>
      {value.kind === "paste" && (
        <Field label="Job description">
          <Textarea value={value.description} onChange={(e) => onChange({ ...value, description: e.target.value })} rows={6} placeholder="Paste the full job description" />
        </Field>
      )}
    </div>
  );
}

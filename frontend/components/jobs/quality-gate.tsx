"use client";

import { Check, CircleSlash } from "lucide-react";

import { Card, CardHeader } from "@/components/ui/card";
import { useProfile, useUsage } from "@/lib/queries";
import type { Match } from "@/lib/types";
import { cn } from "@/lib/utils";

/** The same rules the agents use to decide which jobs get a tailored application. */
export function GateRules({ m, className }: { m: Match; className?: string }) {
  const { data: profile } = useProfile();
  const { data: usage } = useUsage();
  const min = profile?.preferences.min_score ?? 60;
  const rules = [
    { ok: m.score >= min, label: `Fit ${Math.round(m.score)} is at or above your minimum ${min}` },
    { ok: m.job.link_status !== "dead", label: m.job.link_status === "ok" ? "Apply link checked and live" : "Apply link listed recently" },
    {
      ok: m.job.legit_status !== "suspicious",
      label: m.job.legit_status === "verified" ? "Verifier checked it’s a real job" : m.job.legit_status === "caution" ? `Verifier: ${m.job.legit_reasons[0]?.toLowerCase() ?? "worth a closer look"}` : m.job.legit_status === "suspicious" ? "Verifier flagged it as suspicious" : "Not checked by Verifier yet",
    },
    { ok: m.job.ghost_risk !== "high", label: m.job.ghost_risk === "low" ? "No ghost-job signals" : m.job.ghost_reasons.join(" · ") },
    { ok: (usage?.week_left ?? 1) > 0 || m.has_tailored, label: usage ? `${usage.week_applications} of ${usage.weekly_cap} quality applications used this week` : "Within your weekly quality budget" },
  ];
  return (
    <ul className={cn("space-y-2", className)}>
      {rules.map((r) => (
        <li key={r.label} className="flex gap-2 text-[13px]">
          {r.ok ? <Check className="mt-0.5 size-4 shrink-0 text-done" aria-label="Passed" /> : <CircleSlash className="mt-0.5 size-4 shrink-0 text-your-turn" aria-label="Not passed" />}
          <span className={r.ok ? "text-text-2" : "text-text"}>{r.label}</span>
        </li>
      ))}
    </ul>
  );
}

/** Why this job did (or didn't) get a tailored application. */
export function QualityGate({ m }: { m: Match }) {
  return (
    <Card>
      <CardHeader title="Quality gate" description="Only jobs that pass every check get a tailored application." />
      <GateRules m={m} className="p-5" />
    </Card>
  );
}

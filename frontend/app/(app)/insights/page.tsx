"use client";

import { ArrowRight, CircleHelp } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { ActivityChart, BarList, SpendChart } from "@/components/charts";
import { Button, buttonClass } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { EmptyState, Skeleton } from "@/components/ui/misc";
import { StatCard } from "@/components/ui/stat-card";
import { useInsights, useOverview, useSetOutcome } from "@/lib/queries";
import type { InsightGroup, Outcome } from "@/lib/types";
import { ago, usd } from "@/lib/utils";

const OUTCOMES: { v: Outcome; label: string }[] = [
  { v: "replied", label: "Replied" },
  { v: "interview", label: "Interview" },
  { v: "offer", label: "Offer" },
  { v: "rejected", label: "Rejected" },
  { v: "no_reply", label: "No reply" },
];

/** Matcher heads the page (96px): this is where the scoring learns from your outcomes. */
function Header() {
  return (
    <div className="mb-6 flex items-center gap-4 md:mb-8 md:gap-5">
      <AgentAvatar agent="matcher" size={96} priority className="hidden sm:inline-block" />
      <div className="min-w-0">
        <div className="eyebrow mb-1.5">Feedback loop</div>
        <h1 className="font-display text-[clamp(24px,3vw,32px)] leading-tight">Insights</h1>
        <p className="mt-1 max-w-2xl text-[14px] text-text-2">Every application teaches the next one. Matcher uses what happened to show what converts and what to fix first.</p>
      </div>
    </div>
  );
}

function Groups({ title, rows, minSample }: { title: string; rows: InsightGroup[]; minSample: number }) {
  return (
    <Card>
      <CardHeader title={title} description="Interview rate per group" />
      <div className="p-5">
        <BarList
          unit="%"
          empty="No applications yet."
          rows={rows.map((r) => ({ label: r.key, value: r.interview_rate ?? 0, note: `${r.interviews}/${r.applied}${r.enough_data ? "" : `, too few to tell (under ${minSample})`}` }))}
        />
      </div>
    </Card>
  );
}

function NeedsOutcome({ items, reasons }: { items: { match_id: string; company: string; title: string; applied_at: string }[]; reasons: string[] }) {
  const set = useSetOutcome();
  const [rejecting, setRejecting] = useState<string | null>(null);
  if (!items.length) return null;
  return (
    <Card className="border-[color-mix(in_oklab,var(--your-turn-fill)_35%,transparent)]">
      <CardHeader icon={<CircleHelp />} title="What happened with these?" description="One tap each. This is what makes the numbers here, and your next applications, smarter." />
      <ul className="divide-y divide-border px-5 pb-2">
        {items.map((it) => (
          <li key={it.match_id} className="flex flex-col gap-3 py-3 md:flex-row md:items-center">
            <Link href={`/jobs/${it.match_id}`} className="min-w-0 flex-1">
              <div className="truncate text-[14px] font-medium">{it.title}</div>
              <div className="text-[12.5px] text-text-3">
                {it.company} · applied {ago(it.applied_at)}
              </div>
            </Link>
            <div className="flex flex-wrap gap-1.5">
              {rejecting === it.match_id
                ? reasons.map((r) => (
                    <Button key={r} size="sm" className="h-9 md:h-8" onClick={() => (set.mutate({ id: it.match_id, outcome: "rejected", rejection_reason: r }), setRejecting(null))}>
                      {r}
                    </Button>
                  ))
                : OUTCOMES.map((o) => (
                    <Button
                      key={o.v}
                      size="sm"
                      className="h-9 md:h-8"
                      variant={o.v === "interview" || o.v === "offer" ? "primary" : "secondary"}
                      onClick={() => (o.v === "rejected" ? setRejecting(it.match_id) : set.mutate({ id: it.match_id, outcome: o.v }))}
                    >
                      {o.label}
                    </Button>
                  ))}
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}

export default function InsightsPage() {
  const { data: d, isLoading } = useInsights();
  const { data: o } = useOverview();
  if (isLoading || !d)
    return (
      <div>
        <Header />
        <Skeleton agent="matcher" className="min-h-96" />
      </div>
    );
  if (d.applied === 0) {
    return (
      <div>
        <Header />
        <Card>
          <EmptyState
            agent="matcher"
            title="Nothing to learn from yet"
            description="Apply to a few roles and mark what happened. Then I’ll show your interview rate, which resume version converts and the skills holding you back."
            action={
              <Link href="/approvals" className={buttonClass({ variant: "primary" })}>
                Review drafts <ArrowRight />
              </Link>
            }
          />
        </Card>
      </div>
    );
  }
  const f = d.funnel;
  const funnel = [
    { label: "Applied", n: f.applied },
    { label: "Replied", n: f.replied },
    { label: "Interview", n: f.interview },
    { label: "Offer", n: f.offer },
  ];
  const spend14 = (o?.daily ?? []).reduce((t, x) => t + Number(x.cost_usd), 0);

  return (
    <div className="space-y-6">
      <Header />

      <div className="grid gap-3 md:grid-cols-3">
        <StatCard label="Interview rate" value={d.interview_rate == null ? "—" : `${d.interview_rate}%`} sub={`${f.interview} interview${f.interview === 1 ? "" : "s"} from ${f.applied} applications`} />
        <StatCard label="Reply rate" value={d.reply_rate == null ? "—" : `${d.reply_rate}%`} sub={`${f.replied} replied · ${f.no_reply} silent · ${f.awaiting} waiting`} empty="No replies yet. First replies usually arrive in 5–10 days." />
        <StatCard label="Offers" value={f.offer} sub={`${f.rejected} rejected so far`} empty={`None yet · ${f.rejected} rejected so far`} />
      </div>

      <NeedsOutcome items={d.needs_outcome} reasons={d.reason_options} />

      <Card>
        <CardHeader title="Your funnel" description="Each step as a share of the one before" />
        <ol className="grid grid-cols-2 gap-3 p-5 md:grid-cols-4">
          {funnel.map((s, i) => {
            const prev = i > 0 ? funnel[i - 1].n : 0;
            const pct = i > 0 && prev ? Math.round((100 * s.n) / prev) : null;
            return (
              <li key={s.label} className="rounded-[var(--radius-card)] border border-border bg-elevated p-4">
                <div className="text-[12.5px] text-text-2">{s.label}</div>
                <div className="num mt-1 text-[28px] leading-none font-semibold">{s.n}</div>
                <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-elevated-2">
                  <div className="h-full origin-left rounded-full bg-[var(--series-1)]" style={{ transform: `scaleX(${f.applied ? s.n / f.applied : 0})` }} />
                </div>
                <div className="num mt-1.5 text-[12px] text-text-3">{i === 0 ? "100%" : pct == null ? "—" : `${pct}% of ${funnel[i - 1].label.toLowerCase()}`}</div>
              </li>
            );
          })}
        </ol>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2 [&>*]:min-w-0">
        <Card>
          <CardHeader title="Score distribution" description="Applications per fit band, with the interviews each band produced" />
          <div className="p-5">
            <BarList empty="No applications yet." rows={d.by_band.map((r) => ({ label: r.key, value: r.applied, note: `${r.interviews} interview${r.interviews === 1 ? "" : "s"}` }))} />
          </div>
        </Card>
        <Card>
          <CardHeader title="Skill gaps behind rejections" description="Skills most often missing from jobs that rejected you or went silent" />
          <div className="space-y-4 p-5">
            <BarList empty="No rejections or silent applications yet." rows={d.rejection_gaps.map((g) => ({ label: g.skill, value: g.count, note: "jobs" }))} />
            {d.rejection_gaps.length > 0 && (
              <div className="flex flex-wrap gap-2">
                <Link href="/skills" className={buttonClass({ size: "sm" })}>
                  Tell Interviewer if you have them
                </Link>
                <Link href="/proof" className={buttonClass({ size: "sm", variant: "ghost" })}>
                  Add proof to your pack
                </Link>
              </div>
            )}
            {d.reasons.length > 0 && <p className="border-t border-border pt-4 text-[13px] text-text-2">What companies said: {d.reasons.map((r) => `${r.reason} (${r.count})`).join(" · ")}</p>}
          </div>
        </Card>

        <Card>
          <CardHeader title="Activity" description="Jobs matched and applications sent, last 14 days" />
          <div className="px-3 pt-3 pb-3 md:px-5">{o ? <ActivityChart data={o.daily} /> : <Skeleton className="h-[240px]" />}</div>
        </Card>
        <Card>
          <CardHeader title="Spend" description={o ? `LLM cost per day · ${usd(spend14)} over 14 days` : "LLM cost per day"} />
          <div className="px-3 pt-3 pb-3 md:px-5">{o ? <SpendChart data={o.daily} /> : <Skeleton className="h-[180px]" />}</div>
        </Card>

        <Groups title="Resume version A/B" rows={d.by_variant} minSample={d.min_sample} />
        <Groups title="By where you applied" rows={d.by_source} minSample={d.min_sample} />
        <Groups title="Technical vs non-technical" rows={d.by_track} minSample={d.min_sample} />
      </div>
    </div>
  );
}

"use client";

import { ArrowRight, Briefcase, Coins, Inbox, RotateCcw, Target, TrendingUp, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";

import { AgentAvatar, AgentHero } from "@/components/agents/agent-avatar";
import { FlightPath } from "@/components/agents/flight-path";
import { PilotConsole } from "@/components/agents/pilot-console";
import { ActivityChart } from "@/components/charts";
import { MatchRow } from "@/components/match-row";
import { ResumeDropzone } from "@/components/resume-dropzone";
import { RunButton } from "@/components/shell";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, Panel } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/misc";
import { GoalRing } from "@/components/ui/score-ring";
import { StatCard } from "@/components/ui/stat-card";
import { StatusDot } from "@/components/ui/status-dot";
import { AGENTS, type AgentKey } from "@/config/agents";
import { useLiveConnected } from "@/lib/live";
import { useDismissReminder, useInsights, useMatches, useMe, useOverview, useProfile, useReminders, useUsage } from "@/lib/queries";
import type { Overview } from "@/lib/types";
import { cn, ms, usd } from "@/lib/utils";

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);

/** 7-day trends and week-over-week deltas from the overview's daily series. */
function weekly(daily: Overview["daily"] | undefined, pick: (d: Overview["daily"][number]) => number) {
  const series = (daily ?? []).map(pick);
  const last = series.slice(-7);
  const prev = series.slice(-14, -7);
  return { trend: last, delta: prev.length ? sum(last) - sum(prev) : 0 };
}

/** A section said by one agent: their 32px avatar and name label the card. */
function AgentCardHeader({ agent, title, description, action }: { agent: AgentKey; title: string; description: string; action?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 px-4 pt-4 md:px-5 md:pt-5">
      <div className="flex min-w-0 items-start gap-3">
        <AgentAvatar agent={agent} size={32} decorative />
        <div className="min-w-0">
          <h2 className="text-[15px] font-semibold tracking-[-0.01em]">{title}</h2>
          <p className="mt-0.5 text-[13px] text-text-2">
            <span className="text-text-3">{AGENTS[agent].name} · </span>
            {description}
          </p>
        </div>
      </div>
      {action}
    </div>
  );
}

/** Small first-person empty line for feeds: the view's one large character is Pilot. */
function FeedEmpty({ agent, children, action }: { agent: AgentKey; children: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-3 px-6 py-10 text-center">
      <AgentAvatar agent={agent} size={40} decorative />
      <p className="max-w-sm text-[13.5px] text-text-2">{children}</p>
      {action}
    </div>
  );
}

function ListSkeleton({ rows }: { rows: number }) {
  return (
    <div className="space-y-2 p-3" aria-hidden>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-16" />
      ))}
    </div>
  );
}

/** First run: before there's a resume, the dashboard is one step with Pilot. */
function FirstRun({ firstName }: { firstName: string }) {
  return (
    <div className="mx-auto grid max-w-4xl items-center gap-8 py-6 md:grid-cols-[200px_minmax(0,1fr)] md:py-12">
      <div className="mx-auto">
        <AgentHero agent="pilot" size={200} />
      </div>
      <div className="min-w-0">
        <div className="eyebrow mb-2">Step 1 of 2</div>
        <h1 className="font-display text-[clamp(28px,5vw,44px)] leading-[1.05]">{firstName ? `Hi ${firstName}, let’s give the crew something to work with.` : "Let’s give the crew something to work with."}</h1>
        <p className="mt-3 text-[15px] text-text-2">
          Upload your resume once. Scout, Matcher, Tailor and Outreach use it on every run, and Tailor is never allowed to add a skill that isn’t in it.
        </p>
        <Card className="mt-6 p-2">
          <ResumeDropzone />
        </Card>
        <p className="mt-4 text-[13px] text-text-3">
          Then tune keywords, locations and company boards in{" "}
          <Link href="/settings" className="font-medium text-cobalt-text hover:underline">
            Settings
          </Link>
          .
        </p>
      </div>
    </div>
  );
}

/** The weekly quality budget, as a goal ring with the value inside. */
function WeeklyGoal() {
  const { data: u } = useUsage();
  const { data: ins } = useInsights();
  if (!u) return <Skeleton className="h-[88px] w-full sm:w-80" />;
  return (
    <Link href="/insights" className="card flex w-full items-center gap-4 px-4 py-3 transition-colors hover:border-border-strong sm:w-auto sm:min-w-80">
      <GoalRing value={u.week_applications} goal={u.weekly_cap} size={60} hideLabel />
      <div className="min-w-0 text-[13px]">
        <div className="font-medium text-text">Quality applications this week</div>
        <div className="mt-0.5 text-text-3">{ins?.interview_rate != null ? <span className="num">{ins.interview_rate}% interview rate so far</span> : "Mark outcomes to see your interview rate"}</div>
      </div>
    </Link>
  );
}

export default function DashboardPage() {
  const { data: me } = useMe();
  const { data: profile, isLoading: profileLoading } = useProfile();
  const { data: o, isError, refetch, isFetching } = useOverview();
  const { data: top } = useMatches({ sort: "score", limit: 6, stage: ["found", "shortlisted", "applied", "interview", "offer"] });
  const { data: latest } = useMatches({ sort: "recent", limit: 5, min_score: 50, stage: ["found", "shortlisted"] });
  const live = useLiveConnected();
  const { data: reminders } = useReminders();
  const dismiss = useDismissReminder();

  const firstName = (me?.name || "").split(" ")[0];
  const run = o?.last_run;
  // Date and greeting depend on the viewer's clock and locale: filled in by the browser, not the server.
  const [today, setToday] = useState("");
  const [hello, setHello] = useState("Welcome");
  useEffect(() => {
    setToday(new Date().toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" }));
    setHello(greeting());
  }, []);

  if (!profileLoading && profile && !profile.has_resume) return <FirstRun firstName={firstName} />;

  const found = weekly(o?.daily, (d) => d.found);
  const applied = weekly(o?.daily, (d) => d.applied);
  const spend = weekly(o?.daily, (d) => Number(d.cost_usd));
  const appliedTotal = (o?.stage_counts.applied ?? 0) + (o?.stage_counts.interview ?? 0) + (o?.stage_counts.offer ?? 0);
  const stats = [
    {
      key: "strong",
      node: (
        <StatCard
          label="Strong matches"
          value={o?.strong_matches ?? "–"}
          sub={`of ${o?.total_matches ?? 0} scored · avg ${o?.avg_score ?? 0}`}
          empty="None yet. Matcher marks anything 75+ as strong."
          trend={found.trend}
          delta={found.delta ? { value: found.delta } : undefined}
          icon={<Target />}
          href="/jobs"
        />
      ),
    },
    {
      key: "approval",
      node: (
        <StatCard
          label="Awaiting approval"
          value={o?.pending_approvals ?? "–"}
          sub="drafts in your queue"
          empty="Nothing waiting. Outreach drafts appear here."
          icon={<Inbox />}
          href="/approvals"
          highlight={!!o?.pending_approvals}
        />
      ),
    },
    {
      key: "applied",
      node: (
        <StatCard
          label="Applied"
          value={o ? appliedTotal : "–"}
          sub={`${o?.stage_counts.interview ?? 0} interviewing · ${o?.stage_counts.offer ?? 0} offers`}
          empty="No applications yet. Approve a draft to send your first."
          trend={applied.trend}
          delta={applied.delta ? { value: applied.delta } : undefined}
          icon={<Briefcase />}
          href="/tracker"
        />
      ),
    },
    {
      key: "response",
      node: (
        <StatCard
          label="Response rate"
          value={o ? `${Math.round(o.response_rate * 100)}%` : "–"}
          sub="interview or offer"
          empty="No replies yet. First replies usually arrive in 5–10 days."
          icon={<TrendingUp />}
          href="/insights"
        />
      ),
    },
    {
      key: "spend",
      node: (
        <StatCard
          label="Spend · 30 days"
          value={o ? usd(o.cost_30d) : "–"}
          sub={`${o?.runs_30d ?? 0} run${o?.runs_30d === 1 ? "" : "s"} · avg ${ms(o?.avg_run_latency_ms)}`}
          trend={spend.trend}
          icon={<Coins />}
          href="/runs"
        />
      ),
    },
  ];

  return (
    <div className="space-y-6 md:space-y-8">
      {/* Greeting row */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <div className="eyebrow mb-2 min-h-4">{today}</div>
          <h1 className="font-display text-[clamp(28px,4.4vw,44px)] leading-[1.05] break-words">
            {hello}
            {firstName ? `, ${firstName}` : ""}
          </h1>
          <p className="mt-2 text-[14.5px] text-text-2">
            {o ? (
              <>
                {o.strong_matches} strong match{o.strong_matches === 1 ? "" : "es"} on your board
                {o.pending_approvals > 0 ? (
                  <>
                    {" · "}
                    <Link href="/approvals" className="font-medium text-cobalt-text hover:underline">
                      {o.pending_approvals} draft{o.pending_approvals === 1 ? "" : "s"} waiting for you
                    </Link>
                  </>
                ) : o.open_questions > 0 ? (
                  <>
                    {" · "}
                    <Link href="/skills" className="font-medium text-cobalt-text hover:underline">
                      {o.open_questions} skill question{o.open_questions === 1 ? "" : "s"} to answer
                    </Link>
                  </>
                ) : null}
              </>
            ) : isError ? (
              "Couldn’t load your board."
            ) : (
              <span className="skeleton inline-block h-4 w-64 align-middle" />
            )}
          </p>
        </div>
        <WeeklyGoal />
      </div>

      {/* Pilot Console + Flight path, one panel */}
      <Panel className="overflow-hidden">
        {isError && !o ? (
          <div className="flex flex-col items-center gap-3 px-6 py-12 text-center">
            <AgentAvatar agent="pilot" status="error" size={64} decorative />
            <p className="text-[14px] text-text-2">Something broke on our side and I couldn’t reach the crew.</p>
            <Button onClick={() => refetch()} loading={isFetching}>
              {!isFetching && <RotateCcw />} Retry
            </Button>
          </div>
        ) : (
          <>
            <PilotConsole overview={o} firstName={firstName} />
            <div className="border-t border-border px-3 pt-4 pb-3 md:px-2 md:pt-5 xl:px-4">
              <div className="mb-3 flex items-center justify-between px-1 md:px-3">
                <h2 className="eyebrow">The crew</h2>
                {run && (
                  <Link href={`/runs/${run.id}`} className="inline-flex min-h-11 items-center gap-1 text-[12.5px] font-medium text-text-2 hover:text-text md:min-h-0">
                    Full trace <ArrowRight className="size-3.5" />
                  </Link>
                )}
              </div>
              <FlightPath run={run} pendingApprovals={o?.pending_approvals ?? 0} />
            </div>
          </>
        )}
      </Panel>

      {/* 5 stat cards: snap carousel on phones · 3+2 from 768 · one row from 1280 */}
      <div
        role="list"
        aria-label="Key numbers"
        className="-mx-4 flex snap-x snap-mandatory scroll-px-4 gap-3 overflow-x-auto px-4 pb-1 [scrollbar-width:none] md:mx-0 md:grid md:grid-cols-6 md:overflow-visible md:px-0 md:pb-0 xl:grid-cols-5 [&::-webkit-scrollbar]:hidden"
      >
        {stats.map((s, i) => (
          <div key={s.key} role="listitem" className={cn("w-[78%] max-w-72 shrink-0 snap-start md:w-auto md:max-w-none xl:col-span-1", i < 3 ? "md:col-span-2" : "md:col-span-3")}>
            {s.node}
          </div>
        ))}
      </div>

      {/* Feeds: Just in (2/3) + Follow-ups (1/3) */}
      <div className="grid gap-6 lg:grid-cols-3 [&>*]:min-w-0">
        <Card className="lg:col-span-2">
          <AgentCardHeader
            agent="matcher"
            title="Just in for you"
            description="new jobs that fit, the moment I score them"
            action={<StatusDot status={live ? "running" : "idle"} label={live ? "Live" : "Reconnecting…"} className="shrink-0 pt-1" />}
          />
          <div className="p-2" aria-live="polite">
            {!latest ? (
              <ListSkeleton rows={3} />
            ) : latest.items.length === 0 ? (
              <FeedEmpty agent="scout">I’m watching company career boards and job feeds. New fits will appear here as soon as Matcher scores them.</FeedEmpty>
            ) : (
              <AnimatePresence initial={false}>
                {latest.items.map((m) => (
                  <motion.div key={m.id} layout initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}>
                    <MatchRow m={m} />
                  </motion.div>
                ))}
              </AnimatePresence>
            )}
          </div>
        </Card>

        <Card>
          <AgentCardHeader agent="tracker" title="Follow-ups" description="applied 7+ days ago, no reply yet" />
          <div className="p-2">
            {!reminders ? (
              <ListSkeleton rows={2} />
            ) : reminders.length === 0 ? (
              <FeedEmpty agent="tracker">You’re all caught up. I’ll remind you 7 days after each application.</FeedEmpty>
            ) : (
              <ul>
                {reminders.map((r) => (
                  <li key={r.id} className="flex items-center gap-1 rounded-[var(--radius-control)] hover:bg-elevated/60">
                    <Link href={`/jobs/${r.match_id}`} className="flex min-w-0 flex-1 items-start gap-3 rounded-[var(--radius-control)] px-3 py-2.5">
                      <span aria-hidden className="mt-1.5 size-1.5 shrink-0 rounded-full bg-your-turn" />
                      <span className="min-w-0">
                        <span className="block truncate text-[13.5px] font-medium">
                          {r.company} · {r.title}
                        </span>
                        <span className="block text-[12.5px] text-text-2">{r.message}</span>
                      </span>
                    </Link>
                    <button
                      type="button"
                      onClick={() => dismiss.mutate(r.id)}
                      aria-label={`Dismiss follow-up for ${r.company}`}
                      className="mr-1 grid size-11 shrink-0 place-items-center rounded-[var(--radius-control)] text-text-3 hover:bg-elevated hover:text-text md:size-8"
                    >
                      <X className="size-4" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Card>
      </div>

      {/* Deeper detail: top matches, where jobs sit, activity and LLM spend */}
      <div className="grid gap-6 lg:grid-cols-3 [&>*]:min-w-0">
        <Card className="lg:col-span-2">
          <CardHeader
            title="Top matches"
            description="Ranked by fit. Open one for its tailored resume and draft."
            action={
              <Link href="/jobs" className="inline-flex min-h-11 shrink-0 items-center gap-1 text-[13px] font-medium text-text-2 hover:text-text md:min-h-0">
                All matches <ArrowRight className="size-3.5" />
              </Link>
            }
          />
          <div className="p-2">
            {!top ? (
              <ListSkeleton rows={3} />
            ) : top.items.length === 0 ? (
              <FeedEmpty agent="matcher" action={<RunButton />}>
                Nothing to score yet. Run the crew and I’ll rank today’s postings by fit.
              </FeedEmpty>
            ) : (
              top.items.map((m) => <MatchRow key={m.id} m={m} />)
            )}
          </div>
        </Card>

        <Card>
          <CardHeader title="Your board" description="Where every scored job sits" />
          <div className="space-y-3 p-5 pt-4">
            {(["found", "shortlisted", "applied", "interview", "offer"] as const).map((s) => {
              const n = o?.stage_counts[s] ?? 0;
              const max = Math.max(1, ...Object.values(o?.stage_counts ?? { a: 1 }));
              return (
                <div key={s} className="flex items-center gap-3 text-[13px]">
                  <span className="w-20 text-text-2 capitalize">{s}</span>
                  <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-elevated-2">
                    <div className="h-full origin-left rounded-full bg-cobalt transition-transform duration-[var(--dur-slow)] ease-[var(--ease)]" style={{ transform: `scaleX(${n / max})` }} />
                  </div>
                  <span className="num w-8 text-right">{n}</span>
                </div>
              );
            })}
          </div>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader title="Activity" description="Jobs matched and applications sent, last 14 days" />
          <div className="px-2 pt-4 pb-3 md:px-3">{o ? <ActivityChart data={o.daily} /> : <Skeleton className="h-[220px]" />}</div>
        </Card>

        <Card>
          <CardHeader title="Cost and latency by agent" description="Last 30 days, every LLM call traced" />
          <div className="p-5 pt-3">
            {!o ? (
              <Skeleton className="h-32" />
            ) : !o.agent_costs.length ? (
              <p className="py-6 text-center text-[13px] text-text-3">{o.llm_mode === "offline" ? "Offline mode: the crew runs on embeddings and rules, $0." : "No LLM calls yet."}</p>
            ) : (
              <table className="w-full text-[13px]">
                <thead>
                  <tr className="text-left text-[12px] text-text-3">
                    <th className="pb-2 font-medium">Agent</th>
                    <th className="pb-2 text-right font-medium">Calls</th>
                    <th className="pb-2 text-right font-medium">Avg</th>
                    <th className="pb-2 text-right font-medium">Cost</th>
                  </tr>
                </thead>
                <tbody className="num">
                  {o.agent_costs
                    .slice()
                    .sort((a, b) => b.cost_usd - a.cost_usd)
                    .map((a) => {
                      const k = a.agent as AgentKey;
                      return (
                        <tr key={a.agent} className="border-t border-border">
                          <td className="py-2 font-sans">
                            <span className="flex items-center gap-2">
                              {k in AGENTS && <AgentAvatar agent={k} size={24} decorative />}
                              <span className="capitalize">{a.agent.replace("_", " ")}</span>
                            </span>
                          </td>
                          <td className="py-2 text-right">{a.calls}</td>
                          <td className="py-2 text-right text-text-2">{ms(a.avg_latency_ms)}</td>
                          <td className="py-2 text-right">{usd(a.cost_usd)}</td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}

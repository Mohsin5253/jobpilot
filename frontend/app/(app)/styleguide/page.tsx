"use client";

import { Briefcase, Inbox, Send, Settings, Sparkles, Target } from "lucide-react";
import type { ReactNode } from "react";

import { AgentAvatar, AgentHero, type AgentStatus } from "@/components/agents/agent-avatar";
import { agentToast } from "@/components/agents/agent-toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, Panel } from "@/components/ui/card";
import { DialogContent, Dialog, DialogTrigger } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/input";
import { EmptyState, PageHeader, Segmented, Skeleton } from "@/components/ui/misc";
import { GoalRing, ScoreRing } from "@/components/ui/score-ring";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { StatCard } from "@/components/ui/stat-card";
import { StatusDot, StatusPill } from "@/components/ui/status-dot";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AGENTS, type AgentKey } from "@/config/agents";
import { cn } from "@/lib/utils";
import { useState } from "react";

const STATUSES: AgentStatus[] = ["idle", "running", "done", "your-turn", "error"];
const SWATCHES = ["--bg", "--surface", "--elevated", "--border-strong", "--text", "--text-2", "--text-3", "--cobalt", "--done", "--your-turn-fill", "--error"];

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="eyebrow">{title}</h2>
      {children}
    </section>
  );
}

/** Phase 1 review sheet: tokens, primitives and the crew in every state. */
export default function StyleguidePage() {
  const [seg, setSeg] = useState("list");
  return (
    <div className="space-y-10">
      <PageHeader eyebrow="Design system · Phase 1" title="Mission control, with a human crew" description="Tokens, primitives and the AgentAvatar, in both themes. Switch the theme in the sidebar to check light." />

      <Section title="Colour tokens">
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-6 lg:grid-cols-11">
          {SWATCHES.map((v) => (
            <div key={v} className="card overflow-hidden">
              <div className="h-12 border-b border-border" style={{ background: `var(${v})` }} />
              <div className="num truncate p-2 text-[11px] text-text-2">{v}</div>
            </div>
          ))}
        </div>
      </Section>

      <Section title="Type scale">
        <div className="card space-y-2 p-5">
          {[64, 44, 32, 24, 20, 16, 14, 13, 12].map((s) => (
            <div key={s} className="flex items-baseline gap-4">
              <span className="num w-10 text-[12px] text-text-3">{s}</span>
              <span className={cn("min-w-0 break-words", s >= 32 ? "font-display" : "font-medium")} style={{ fontSize: s, lineHeight: 1.1 }}>
                Nine agents hunt internships
              </span>
            </div>
          ))}
          <div className="num pt-2 text-[14px] text-text-2">$0.0070 · 1m 56s · 15 LLM calls · 82/100</div>
        </div>
      </Section>

      <Section title="The crew · idle, running, done, your turn, error">
        <Panel className="overflow-x-auto p-5">
          <table className="w-full min-w-[640px] text-left text-[13px]">
            <thead className="text-text-3">
              <tr>
                <th className="pb-3 font-medium">Agent</th>
                {STATUSES.map((s) => (
                  <th key={s} className="pb-3 font-medium capitalize">{s.replace("-", " ")}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {(Object.keys(AGENTS) as AgentKey[]).map((k) => (
                <tr key={k}>
                  <td className="py-3">
                    <div className="font-medium">{AGENTS[k].name}</div>
                    <div className="text-[12px] text-text-3">{AGENTS[k].role}</div>
                  </td>
                  {STATUSES.map((s) => (
                    <td key={s} className="py-3">
                      <AgentAvatar agent={k} status={s} size={64} />
                    </td>
                  ))}
                </tr>
              ))}
              <tr>
                <td className="py-3">
                  <div className="font-medium">Your turn</div>
                  <div className="text-[12px] text-text-3">You approve before anything is sent</div>
                </td>
                {STATUSES.map((s) => (
                  <td key={s} className="py-3">
                    <AgentAvatar agent="you" user={{ name: "Mohsin Sidhpurwala" }} status={s} size={64} />
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </Panel>
      </Section>

      <Section title="Avatar sizes · face crop at 40px and below">
        <Card className="flex flex-wrap items-end gap-5 p-5">
          {[24, 32, 40, 64, 96, 160].map((s) => (
            <div key={s} className="flex flex-col items-center gap-2">
              <AgentAvatar agent="scout" size={s} />
              <span className="num text-[11px] text-text-3">{s}</span>
            </div>
          ))}
          <div className="flex flex-col items-center gap-2">
            <AgentHero agent="pilot" size={200} priority={false} />
            <span className="num text-[11px] text-text-3">200 · hero with glow</span>
          </div>
        </Card>
      </Section>

      <Section title="Buttons, badges, status">
        <Card className="space-y-4 p-5">
          <div className="flex flex-wrap gap-2">
            <Button variant="primary">
              <Sparkles /> Run agents
            </Button>
            <Button>Secondary</Button>
            <Button variant="outline">Outline</Button>
            <Button variant="ghost">Ghost</Button>
            <Button variant="danger">Reject</Button>
            <Button variant="success">Approve</Button>
            <Button variant="primary" loading>
              Sending
            </Button>
            <Button size="icon" aria-label="Settings">
              <Settings />
            </Button>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge>Neutral</Badge>
            <Badge tone="accent">Remote</Badge>
            <Badge tone="success">Applied</Badge>
            <Badge tone="warning">Needs approval</Badge>
            <Badge tone="danger">Closed</Badge>
            <Badge tone="outline">Outline</Badge>
          </div>
          <div className="flex flex-wrap items-center gap-4">
            {STATUSES.map((s) => (
              <StatusDot key={s} status={s} />
            ))}
            {STATUSES.map((s) => (
              <StatusPill key={s} status={s} />
            ))}
          </div>
        </Card>
      </Section>

      <Section title="Stat cards, score and goal rings">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <StatCard label="Strong matches" value={12} sub="of 48 scored · avg 63" trend={[2, 3, 3, 5, 4, 7, 12]} delta={{ value: 5 }} icon={<Target />} />
          <StatCard label="Awaiting approval" value={4} sub="drafts in queue" icon={<Inbox />} highlight />
          <StatCard label="Applied" value={7} sub="2 interviewing" trend={[0, 1, 1, 2, 3, 5, 7]} delta={{ value: 2 }} icon={<Briefcase />} />
          <StatCard label="Response rate" value="0%" empty="No replies yet. First replies usually arrive in 5–10 days." icon={<Send />} />
          <StatCard label="Spend · 30d" value="$0.42" sub="$0.007 per run" trend={[0.02, 0.05, 0.04, 0.08, 0.06, 0.1, 0.07]} delta={{ value: -12, suffix: "%", goodWhenUp: false }} />
        </div>
        <Card className="flex flex-wrap items-center gap-6 p-5">
          {[32, 48, 62, 78, 86, 94].map((s) => (
            <ScoreRing key={s} score={s} size={48} />
          ))}
          <GoalRing value={3} goal={10} />
        </Card>
      </Section>

      <Section title="Tabs, segmented, inputs">
        <Card className="space-y-4 p-5">
          <Tabs defaultValue="email">
            <TabsList>
              <TabsTrigger value="email">Email draft</TabsTrigger>
              <TabsTrigger value="resume">Tailored resume</TabsTrigger>
              <TabsTrigger value="why">Why this match</TabsTrigger>
            </TabsList>
            <TabsContent value="email" className="pt-4 text-[14px] text-text-2">Hi Priya, I built a RAG search tool in Python…</TabsContent>
            <TabsContent value="resume" className="pt-4 text-[14px] text-text-2">Bullet diff vs your base resume.</TabsContent>
            <TabsContent value="why" className="pt-4 text-[14px] text-text-2">Strong: Python, scikit-learn. Missing: Docker.</TabsContent>
          </Tabs>
          <Segmented value={seg} onChange={setSeg} options={[{ value: "list", label: "List" }, { value: "grid", label: "Grid" }]} />
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Email">
              <Input placeholder="you@college.edu" />
            </Field>
            <Field label="Location" hint="Add “Remote” to include remote roles.">
              <Input placeholder="Bengaluru" />
            </Field>
          </div>
        </Card>
      </Section>

      <Section title="Dialog, sheet, toast">
        <Card className="flex flex-wrap gap-2 p-5">
          <Dialog>
            <DialogTrigger asChild>
              <Button>Open dialog</Button>
            </DialogTrigger>
            <DialogContent title="Reject this draft?" description="Outreach will not send it. You can still prepare it again later.">
              <div className="flex justify-end gap-2">
                <Button variant="danger">Reject</Button>
              </div>
            </DialogContent>
          </Dialog>
          <Sheet>
            <SheetTrigger asChild>
              <Button>Open sheet</Button>
            </SheetTrigger>
            <SheetContent title="Machine Learning Intern" description="Acme AI · Bengaluru">
              <div className="p-5 text-[14px] text-text-2">Job detail lives here: a side sheet on desktop, a bottom sheet on phones.</div>
            </SheetContent>
          </Sheet>
          <Button onClick={() => agentToast("outreach", "Drafted 4 emails for your review", { action: { label: "Review", onClick: () => undefined } })}>Agent toast</Button>
          <Button onClick={() => agentToast("scout", "Found 6 new roles that fit you")}>Scout toast</Button>
        </Card>
      </Section>

      <Section title="Empty and loading states">
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader title="Approvals" />
            <EmptyState agent="outreach" action={<Button variant="primary">Run agents</Button>} />
          </Card>
          <Skeleton agent="matcher" className="min-h-72" />
        </div>
      </Section>
    </div>
  );
}

"use client";

import { ArrowLeft, Check, ChevronDown, Copy, RotateCcw } from "lucide-react";
import Link from "next/link";
import { use, useState } from "react";
import { toast } from "sonner";

import { AgentAvatar, type AgentStatus } from "@/components/agents/agent-avatar";
import { FlightPath } from "@/components/agents/flight-path";
import { RUN_STATUS } from "@/components/agents/pilot-console";
import { Button } from "@/components/ui/button";
import { Card, Panel } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/misc";
import { StatusPill } from "@/components/ui/status-dot";
import { AGENTS, FLIGHT_PATH, type CrewKey } from "@/config/agents";
import { useRetryRun, useRun } from "@/lib/queries";
import type { LLMCall, RunStep } from "@/lib/types";
import { ago, cn, compact, ms, usd } from "@/lib/utils";

const STEP: Record<string, AgentStatus> = { completed: "done", running: "running", waiting: "your-turn", failed: "error", skipped: "off" };
const crewOf = (agent: string): CrewKey | null => (agent === "approval" ? "you" : agent in AGENTS ? (agent as CrewKey) : null);
const duration = (s: RunStep) => (s.started_at && s.ended_at ? new Date(s.ended_at).getTime() - new Date(s.started_at).getTime() : null);

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="card p-4">
      <div className="text-[12.5px] text-text-2">{label}</div>
      <div className="num mt-1 text-[20px] font-semibold">{value}</div>
    </div>
  );
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      onClick={() =>
        navigator.clipboard.writeText(text).then(() => {
          setDone(true);
          toast.success(`${label} copied`);
          setTimeout(() => setDone(false), 1500);
        })
      }
      aria-label={`Copy ${label}`}
      className="inline-flex min-h-9 items-center gap-1.5 rounded-[var(--radius-control)] px-2 text-[12.5px] text-text-2 hover:bg-elevated hover:text-text md:min-h-7"
    >
      {done ? <Check className="size-3.5 text-done" /> : <Copy className="size-3.5" />} Copy
    </button>
  );
}

/** One stage of the trace: avatar, result, timing, and its LLM calls in mono when expanded. */
function TraceStep({ step, calls, last }: { step: RunStep; calls: LLMCall[]; last: boolean }) {
  const [open, setOpen] = useState(step.status === "failed");
  const key = crewOf(step.agent);
  const d = duration(step);
  const cost = calls.reduce((t, c) => t + Number(c.cost_usd), 0);
  const name = key === "you" ? "Your turn" : key ? AGENTS[key].name : step.agent;
  const record = JSON.stringify({ step, calls }, null, 2);
  return (
    <li className="relative flex gap-4 pb-6">
      {!last && <span aria-hidden className="absolute top-12 bottom-0 left-[19px] w-px bg-border-strong" />}
      {key ? <AgentAvatar agent={key} status={STEP[step.status] ?? "idle"} size={40} user={{ name: "You" }} decorative /> : <span className="size-10 shrink-0 rounded-[var(--radius-avatar)] bg-elevated" />}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
          <h3 className="text-[14.5px] font-semibold">{name}</h3>
          <StatusPill status={STEP[step.status] ?? "idle"}>{step.status}</StatusPill>
          <span className="num text-[12.5px] text-text-3">
            {d != null ? ms(d) : "—"}
            {calls.length > 0 && ` · ${calls.length} call${calls.length === 1 ? "" : "s"} · ${usd(cost, 3)}`}
          </span>
        </div>
        <p className="mt-1 text-[13.5px] leading-relaxed text-text-2">{step.detail || "No details recorded."}</p>
        <div className="mt-2 flex items-center gap-1">
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            className="inline-flex min-h-9 items-center gap-1 rounded-[var(--radius-control)] px-2 text-[12.5px] font-medium text-text-2 hover:bg-elevated hover:text-text md:min-h-7"
          >
            <ChevronDown className={cn("size-3.5 transition-transform duration-[var(--dur-fast)]", open && "rotate-180")} /> {open ? "Hide" : "Show"} trace
          </button>
          <CopyButton text={record} label={`${name} trace`} />
        </div>
        {open && (
          <div className="num mt-2 overflow-x-auto rounded-[var(--radius-control)] border border-border bg-elevated p-3 text-[12px] leading-relaxed">
            <div className="text-text-3">
              started {step.started_at ? new Date(step.started_at).toLocaleTimeString() : "—"} · ended {step.ended_at ? new Date(step.ended_at).toLocaleTimeString() : "—"}
            </div>
            {calls.length === 0 ? (
              <div className="mt-1 text-text-2">No LLM calls: embeddings and rules only.</div>
            ) : (
              <table className="mt-2 w-full min-w-[480px]">
                <thead className="text-left text-text-3">
                  <tr>
                    <th className="pr-3 font-normal">model</th>
                    <th className="pr-3 font-normal">in / out</th>
                    <th className="pr-3 font-normal">latency</th>
                    <th className="pr-3 font-normal">tries</th>
                    <th className="font-normal">cost</th>
                  </tr>
                </thead>
                <tbody className="text-text">
                  {calls.map((c, i) => (
                    <tr key={i} className={cn(!c.success && "text-[var(--error)]")}>
                      <td className="pr-3">{c.model.split("/").pop()!.replace("claude-", "")}</td>
                      <td className="pr-3">
                        {compact(c.input_tokens)} / {compact(c.output_tokens)}
                      </td>
                      <td className="pr-3">{ms(c.latency_ms)}</td>
                      <td className="pr-3">{c.attempts}</td>
                      <td>
                        {usd(Number(c.cost_usd), 3)}
                        {c.error && <span className="ml-2">{c.error}</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>
    </li>
  );
}

export default function RunDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: run } = useRun(id);
  const retry = useRetryRun();
  if (!run) return <Skeleton agent="pilot" className="min-h-96" />;

  const stats = run.stats ?? {};
  const order = new Map<string, number>(FLIGHT_PATH.map((k, i) => [k === "you" ? "approval" : k, i]));
  const steps = [...run.steps].sort((a, b) => (order.get(a.agent) ?? 99) - (order.get(b.agent) ?? 99));
  const meta = RUN_STATUS[run.status];

  return (
    <div className="space-y-6">
      <Link href="/runs" className="inline-flex min-h-11 items-center gap-1.5 text-[13px] text-text-2 hover:text-text md:min-h-0">
        <ArrowLeft className="size-3.5" /> Agent runs
      </Link>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2.5">
            <h1 className="font-display text-[clamp(24px,3vw,32px)]">Run trace</h1>
            <StatusPill status={meta.status}>{meta.label}</StatusPill>
          </div>
          <p className="num mt-1 truncate text-[12.5px] text-text-3">
            {run.id} · {run.trigger} · {ago(run.created_at)}
          </p>
        </div>
        <div className="flex gap-2">
          <CopyButton text={JSON.stringify(run, null, 2)} label="Full run trace" />
          {run.status === "failed" && (
            <Button variant="primary" onClick={() => retry.mutate(run.id)} loading={retry.isPending}>
              {!retry.isPending && <RotateCcw />} Retry from checkpoint
            </Button>
          )}
        </div>
      </div>

      {run.error && <pre className="num overflow-x-auto rounded-[var(--radius-card)] border border-[color-mix(in_oklab,var(--error)_30%,transparent)] bg-[color-mix(in_oklab,var(--error)_8%,transparent)] px-4 py-3 text-[12.5px] whitespace-pre-wrap text-[var(--error)]">{run.error}</pre>}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="Active time" value={ms(stats.active_ms)} />
        <Stat label="Cost" value={usd(Number(run.cost_usd))} />
        <Stat label="LLM calls" value={run.llm_calls} />
        <Stat label="Tokens in / out" value={`${compact(run.input_tokens)} / ${compact(run.output_tokens)}`} />
        <Stat label="Guard reverts" value={stats.guard_reverts ?? 0} />
      </div>

      <Panel className="px-3 pt-4 pb-3 md:px-2 md:pt-5 xl:px-4">
        <h2 className="eyebrow mb-3 px-1 md:px-3">The crew on this run</h2>
        <FlightPath run={run} />
      </Panel>

      <Card className="p-5 md:p-6">
        <h2 className="mb-1 text-[15px] font-semibold">Trace</h2>
        <p className="mb-5 text-[13px] text-text-2">What each agent did, in order. Prompts and model outputs aren’t stored, so the trace shows each call’s model, tokens, timing and cost.</p>
        <ol>
          {steps.map((s, i) => (
            <TraceStep key={s.agent} step={s} calls={run.calls.filter((c) => c.agent === s.agent)} last={i === steps.length - 1} />
          ))}
        </ol>
        {run.calls.some((c) => !order.has(c.agent)) && (
          <div className="mt-2 border-t border-border pt-4">
            <h3 className="mb-2 text-[13.5px] font-semibold">Other calls</h3>
            <ul className="num space-y-1 text-[12px] text-text-2">
              {run.calls
                .filter((c) => !order.has(c.agent))
                .map((c, i) => (
                  <li key={i}>
                    {c.agent} · {c.model.split("/").pop()} · {compact(c.input_tokens)}/{compact(c.output_tokens)} · {ms(c.latency_ms)} · {usd(Number(c.cost_usd), 3)}
                  </li>
                ))}
            </ul>
          </div>
        )}
      </Card>
    </div>
  );
}

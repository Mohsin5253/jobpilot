"use client";

import { ChevronRight } from "lucide-react";
import Link from "next/link";

import { RUN_STATUS } from "@/components/agents/pilot-console";
import { RunButton } from "@/components/shell";
import { Card } from "@/components/ui/card";
import { EmptyState, PageHeader, Skeleton } from "@/components/ui/misc";
import { StatusPill } from "@/components/ui/status-dot";
import { useRuns } from "@/lib/queries";
import type { Run } from "@/lib/types";
import { ago, compact, ms, usd } from "@/lib/utils";

const funnel = (r: Run) => `${r.stats.new_jobs ?? 0} → ${r.stats.matched ?? 0} → ${r.stats.drafts ?? 0}`;

/** Every run: a dense table on desktop, stacked rows on phones. */
export default function RunsPage() {
  const { data, isLoading } = useRuns(50);
  return (
    <div>
      <PageHeader title="Agent runs" description="Every run is checkpointed, traced and costed. A failed run retries from the last agent that finished." />
      {isLoading ? (
        <Skeleton agent="pilot" className="min-h-72" />
      ) : !data?.length ? (
        <Card>
          <EmptyState agent="pilot" title="No runs yet" description="Runs happen daily at your chosen hour, or whenever you start one." action={<RunButton />} />
        </Card>
      ) : (
        <>
          <Card className="hidden overflow-x-auto md:block">
            <table className="w-full min-w-[760px] text-[13.5px]">
              <thead>
                <tr className="border-b border-border text-left text-[12px] text-text-3">
                  {["Status", "Started", "Trigger", "Found → matched → drafted", "Active time", "LLM calls", "Tokens in / out", "Cost"].map((h) => (
                    <th key={h} className="px-4 py-3 font-medium">
                      {h}
                    </th>
                  ))}
                  <th className="px-4 py-3">
                    <span className="sr-only">Open</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.map((r) => (
                  <tr key={r.id} className="group relative border-b border-border last:border-0 hover:bg-elevated/50">
                    <td className="px-4 py-3">
                      <StatusPill status={RUN_STATUS[r.status].status}>{RUN_STATUS[r.status].label}</StatusPill>
                    </td>
                    <td className="px-4 py-3 text-text-2">{ago(r.created_at)}</td>
                    <td className="px-4 py-3 text-text-2 capitalize">{r.trigger}</td>
                    <td className="num px-4 py-3">{funnel(r)}</td>
                    <td className="num px-4 py-3 text-text-2">{ms(r.stats.active_ms)}</td>
                    <td className="num px-4 py-3">{r.llm_calls}</td>
                    <td className="num px-4 py-3 text-text-2">
                      {compact(r.input_tokens)} / {compact(r.output_tokens)}
                    </td>
                    <td className="num px-4 py-3">{usd(Number(r.cost_usd))}</td>
                    <td className="px-4 py-3 text-right">
                      <Link href={`/runs/${r.id}`} aria-label={`Open the ${r.trigger} run from ${ago(r.created_at)}`} className="inline-flex text-text-3 after:absolute after:inset-0 group-hover:text-text">
                        <ChevronRight className="size-4" />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
          <ul className="space-y-2 md:hidden">
            {data.map((r) => (
              <li key={r.id}>
                <Link href={`/runs/${r.id}`} className="card flex items-center gap-3 p-4">
                  <div className="min-w-0 flex-1 space-y-1.5">
                    <div className="flex items-center gap-2">
                      <StatusPill status={RUN_STATUS[r.status].status}>{RUN_STATUS[r.status].label}</StatusPill>
                      <span className="text-[13px] text-text-2 capitalize">
                        {r.trigger} · {ago(r.created_at)}
                      </span>
                    </div>
                    <div className="num flex flex-wrap gap-x-3 text-[12.5px] text-text-3">
                      <span className="text-text">{funnel(r)}</span>
                      <span>{ms(r.stats.active_ms)}</span>
                      <span>{r.llm_calls} calls</span>
                      <span>{usd(Number(r.cost_usd))}</span>
                    </div>
                  </div>
                  <ChevronRight className="size-4 shrink-0 text-text-3" />
                </Link>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

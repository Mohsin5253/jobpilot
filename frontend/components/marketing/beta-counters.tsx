import { formatInr, type PublicStats } from "@/lib/server-api";

const n = (v: number) => v.toLocaleString("en-IN");

/** Live beta counters, straight from the API (server-rendered, refreshed every five minutes). No made-up numbers. */
export function BetaCounters({ stats }: { stats: PublicStats | null }) {
  const tiles = stats
    ? [
        { label: "Postings verified", value: n(stats.postings_verified) },
        { label: "Scams blocked", value: n(stats.scams_flagged) },
        { label: "Applications approved by students", value: n(stats.applications_approved) },
        {
          label: `Average AI cost per run, last ${stats.cost_window_days} days`,
          value: stats.avg_cost_inr_per_run === null ? "No runs yet" : formatInr(stats.avg_cost_inr_per_run),
        },
      ]
    : null;
  return (
    <section aria-labelledby="beta-counters" className="border-y border-border bg-surface">
      <div className="mx-auto max-w-[1200px] px-4 py-8 md:px-6">
        <div className="mb-5 flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="rounded-full border border-border-strong px-2 py-0.5 text-[11px] font-medium tracking-wide text-text-2 uppercase">Beta</span>
          <h2 id="beta-counters" className="text-[15px] font-semibold">
            Live from the beta
          </h2>
          <span className="text-[13px] text-text-3">Counted from real runs, updated every 5 minutes. Demo accounts excluded.</span>
        </div>
        {tiles ? (
          <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {tiles.map((t) => (
              <div key={t.label} className="card flex flex-col-reverse justify-end gap-1 p-4">
                <dt className="text-[12.5px] leading-snug text-text-2">{t.label}</dt>
                <dd className="num text-[26px] leading-tight font-semibold tracking-[-0.02em]">{t.value}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="text-[14px] text-text-2">The live counters can’t be reached right now. They’ll be back in a few minutes.</p>
        )}
      </div>
    </section>
  );
}

"use client";

import { ArrowUpRight, LayoutGrid, List, Search, SlidersHorizontal } from "lucide-react";
import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";

import { JobCard } from "@/components/jobs/job-card";
import { MatchDetail } from "@/components/jobs/match-detail";
import { RunButton } from "@/components/shell";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, Switch } from "@/components/ui/input";
import { EmptyState, PageHeader, Segmented, Skeleton } from "@/components/ui/misc";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { StatusDot } from "@/components/ui/status-dot";
import { useMatches } from "@/lib/queries";
import type { Stage } from "@/lib/types";
import { cn } from "@/lib/utils";

const STAGES: { value: string; label: string; stages?: Stage[] }[] = [
  { value: "all", label: "All" },
  { value: "new", label: "New", stages: ["found", "shortlisted"] },
  { value: "applied", label: "Applied", stages: ["applied"] },
  { value: "active", label: "Interviewing", stages: ["interview", "offer"] },
  { value: "archived", label: "Skipped", stages: ["rejected", "archived"] },
];

type Sort = "score" | "recent" | "posted";
type Track = "all" | "technical" | "non_technical";

function useDebounced<T>(value: T, delay = 250) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return v;
}

/** List or grid, remembered per browser. */
function useLayout() {
  const [layout, setLayout] = useState<"list" | "grid">("list");
  useEffect(() => {
    try {
      if (localStorage.getItem("jp-matches-layout") === "grid") setLayout("grid");
    } catch {}
  }, []);
  const set = (v: "list" | "grid") => {
    setLayout(v);
    try {
      localStorage.setItem("jp-matches-layout", v);
    } catch {}
  };
  return [layout, set] as const;
}

function Group({ label, children }: { label: string; children: ReactNode }) {
  return (
    <fieldset className="space-y-2">
      <legend className="eyebrow mb-2">{label}</legend>
      {children}
    </fieldset>
  );
}

/** Radio-style vertical options for the rail. */
function Options<T extends string>({ value, onChange, options, name }: { value: T; onChange: (v: T) => void; options: { value: T; label: string }[]; name: string }) {
  return (
    <div role="radiogroup" aria-label={name} className="space-y-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            "flex min-h-11 w-full items-center rounded-[var(--radius-control)] px-3 text-left text-[13.5px] transition-colors md:min-h-9",
            value === o.value ? "bg-elevated font-medium text-text" : "text-text-2 hover:bg-elevated/60 hover:text-text",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export default function JobsPage() {
  const [q, setQ] = useState("");
  const [stage, setStage] = useState("all");
  const [minScore, setMinScore] = useState(0);
  const [remoteOnly, setRemoteOnly] = useState(false);
  const [sort, setSort] = useState<Sort>("score");
  const [track, setTrack] = useState<Track>("all");
  const [layout, setLayout] = useLayout();
  const [open, setOpen] = useState<string | null>(null);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const debouncedQ = useDebounced(q);
  const debouncedMin = useDebounced(minScore, 150);

  const { data, isLoading, isFetching } = useMatches({
    q: debouncedQ || undefined,
    stage: STAGES.find((s) => s.value === stage)?.stages,
    min_score: debouncedMin,
    remote: remoteOnly ? true : undefined,
    track: track === "all" ? undefined : track,
    sort,
    limit: 200,
  });
  const filtered = !!(q || minScore || stage !== "all" || remoteOnly || track !== "all");
  const active = [stage !== "all", track !== "all", minScore > 0, remoteOnly].filter(Boolean).length;
  const reset = () => (setQ(""), setStage("all"), setMinScore(0), setRemoteOnly(false), setTrack("all"));

  const filters = (
    <div className="space-y-6">
      <Group label="Stage">
        <Options name="Stage" value={stage} onChange={setStage} options={STAGES.map((s) => ({ value: s.value, label: s.label }))} />
      </Group>
      <Group label="Role type">
        <Options<Track>
          name="Role type"
          value={track}
          onChange={setTrack}
          options={[
            { value: "all", label: "All roles" },
            { value: "technical", label: "Technical" },
            { value: "non_technical", label: "Non-technical" },
          ]}
        />
      </Group>
      <Group label="Minimum fit">
        <div className="flex items-center gap-3">
          <SlidersHorizontal className="size-4 shrink-0 text-text-3" aria-hidden />
          <input type="range" min={0} max={90} step={5} value={minScore} onChange={(e) => setMinScore(Number(e.target.value))} className="h-11 flex-1 accent-[var(--cobalt)] md:h-auto" aria-label="Minimum fit score" />
          <span className="num w-7 text-right text-[13px]">{minScore}</span>
        </div>
      </Group>
      <label className="flex min-h-11 items-center justify-between gap-3 text-[13.5px] text-text-2 md:min-h-0">
        Remote only
        <Switch checked={remoteOnly} onChange={setRemoteOnly} label="Remote only" />
      </label>
      {filtered && (
        <Button variant="ghost" size="sm" onClick={reset} className="w-full">
          Clear filters
        </Button>
      )}
    </div>
  );

  return (
    <div>
      <PageHeader
        title="Matches"
        description={data ? `${data.total} live jobs scored against your resume. Updates every minute.` : "Every job Scout found, scored and explained."}
        action={<StatusDot status={isFetching ? "running" : "done"} label={isFetching ? "Checking for new jobs…" : "Live"} />}
      />

      <div className="grid gap-6 lg:grid-cols-[220px_minmax(0,1fr)]">
        {/* ≥1024: a sticky filter rail. Smaller screens open the same filters in a bottom sheet. */}
        <aside aria-label="Filters" className="hidden lg:block">
          <div className="sticky top-20">{filters}</div>
        </aside>

        <div className="min-w-0 space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-0 flex-1 basis-56">
              <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-text-3" aria-hidden />
              <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search title, company, location" className="h-11 pl-9 md:h-9" aria-label="Search matches" />
            </div>
            <Button className="h-11 lg:hidden" onClick={() => setFiltersOpen(true)}>
              <SlidersHorizontal /> Filters{active ? <span className="num rounded-full bg-cobalt px-1.5 text-[11px] text-on-cobalt">{active}</span> : null}
            </Button>
            <Segmented<Sort>
              value={sort}
              onChange={setSort}
              options={[
                { value: "score", label: "Best fit" },
                { value: "posted", label: "Newest" },
              ]}
            />
            <Segmented
              value={layout}
              onChange={setLayout}
              options={[
                { value: "list", label: <List className="size-4" aria-label="List view" /> },
                { value: "grid", label: <LayoutGrid className="size-4" aria-label="Grid view" /> },
              ]}
            />
          </div>

          <div className={cn("transition-opacity duration-[var(--dur-base)]", isFetching && !isLoading && "opacity-80")} aria-busy={isFetching}>
            {isLoading ? (
              <Skeleton agent="scout" className="min-h-80" />
            ) : !data?.items.length ? (
              <Card>
                {filtered ? (
                  <EmptyState
                    icon={<Search />}
                    title="Nothing matches these filters"
                    description="Try a lower minimum fit, or clear the filters."
                    action={
                      <Button variant="secondary" onClick={reset}>
                        Clear filters
                      </Button>
                    }
                  />
                ) : (
                  <EmptyState agent="scout" action={<RunButton />} />
                )}
              </Card>
            ) : (
              <ul className={cn("grid gap-3", layout === "grid" && "sm:grid-cols-2 2xl:grid-cols-3")}>
                {data.items.map((m) => (
                  <li key={m.id} className="min-w-0">
                    <JobCard m={m} layout={layout} onOpen={() => setOpen(m.id)} />
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>

      <Sheet open={filtersOpen} onOpenChange={setFiltersOpen}>
        <SheetContent title="Filters" description={data ? `${data.total} matches` : undefined}>
          <div className="p-5 pb-[calc(20px+env(safe-area-inset-bottom))]">{filters}</div>
        </SheetContent>
      </Sheet>

      {/* Job detail: a right sheet on desktop, full screen on phones. */}
      <Sheet open={!!open} onOpenChange={(v) => !v && setOpen(null)}>
        <SheetContent title="Job details" full className="md:w-[min(760px,100vw)]">
          {open && (
            <div className="space-y-3 p-4 md:p-5">
              <Link href={`/jobs/${open}`} className="inline-flex min-h-11 items-center gap-1 text-[13px] font-medium text-cobalt-text hover:underline md:min-h-0">
                Open as a full page <ArrowUpRight className="size-3.5" />
              </Link>
              <MatchDetail id={open} compact />
            </div>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}

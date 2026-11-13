"use client";

/**
 * The Campus portal's shared pieces: the staff "me" query, portal navigation, the drill-down dashboard and a
 * keyset-paginated, virtualized table that stays smooth at lakhs of rows.
 */

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

export type StaffMe = {
  campus: { id: string; name: string; college: string; branch: string; institution_id: string; city: string; state: string; student_id_label: string; pending_subjects_label: string | null; score_scale: { type: string; max?: number } | null; term_type: string; allowed_email_domains: string[]; locale: string };
  role: "tpo" | "principal" | "hod" | "faculty" | "coordinator" | "university_admin";
  whole_campus: boolean;
  plan: "pilot" | "department" | "college" | "university";
  /** Runs setup, staff, roster and seats: the TPO / Principal, or the HOD on the Department plan. */
  lead: boolean;
  scope: { departments: { id: string; name: string; plan_limit: number | null }[]; programs: string[]; batches: string[] };
};
export const ROLE_LABEL: Record<StaffMe["role"], string> = { tpo: "TPO", principal: "Principal", hod: "HOD", faculty: "Faculty", coordinator: "Placement coordinator", university_admin: "University admin" };

export function useStaffMe() {
  return useQuery({ queryKey: ["campus-staff-me"], queryFn: () => api.get<StaffMe>("/campus/staff/me"), staleTime: 60_000 });
}

const TABS: { href: string; label: string; roles?: StaffMe["role"][]; lead?: boolean }[] = [
  { href: "/campus", label: "Dashboard" },
  { href: "/campus/students", label: "Students" },
  { href: "/campus/verify", label: "Verification queue" },
  { href: "/campus/drives", label: "Drives" },
  { href: "/campus/pipeline", label: "AI proposals" },
  { href: "/campus/import", label: "Roster import", roles: ["tpo", "principal", "hod"] },
  { href: "/campus/staff", label: "Staff", roles: ["tpo", "principal", "hod"] },
  { href: "/campus/setup", label: "Setup", lead: true },
];

export function PortalNav() {
  const pathname = usePathname();
  const { data: me } = useStaffMe();
  const { data: mine } = useQuery({ queryKey: ["my-staff-campuses"], queryFn: () => api.get<{ id: string; name: string; role: string }[]>("/campus/my-staff-campuses"), staleTime: 60_000 });
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <div className="eyebrow">Campus portal{me ? ` · ${ROLE_LABEL[me.role]}${me.scope.departments.length && !me.whole_campus ? ` · ${me.scope.departments.map((d) => d.name).join(", ")}` : ""}` : ""}</div>
          <h1 className="font-display text-[clamp(24px,3vw,32px)] leading-tight">{me?.campus.name ?? "Campus"}</h1>
          {mine && mine.length > 1 && (
            <label className="mt-1 flex items-center gap-2 text-[13px] text-text-2">
              Branch
              <select
                value={me?.campus.id ?? ""}
                onChange={(e) => (window.location.href = `/staff-access?campus=${e.target.value}&next=/campus`)}
                className="h-9 rounded-[var(--radius-control)] border border-border bg-surface px-2 text-[13px]"
                aria-label="Switch college or branch"
              >
                {mine.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </label>
          )}
        </div>
        <button
          type="button"
          onClick={async () => {
            await api.post("/campus/staff-session/close");
            window.location.href = "/dashboard";
          }}
          className="text-[13px] text-text-3 hover:text-text"
        >
          Leave the portal
        </button>
      </div>
      <nav aria-label="Campus portal" className="-mx-1 flex gap-1 overflow-x-auto pb-1">
        {TABS.filter((t) => (t.lead ? !!me?.lead : !t.roles || (me && t.roles.includes(me.role)))).map((t) => {
          const on = t.href === "/campus" ? pathname === "/campus" : pathname.startsWith(t.href);
          return (
            <Link key={t.href} href={t.href} aria-current={on ? "page" : undefined} className={cn("shrink-0 rounded-full px-3.5 py-2 text-[13px]", on ? "bg-elevated font-medium text-text" : "text-text-2 hover:text-text")}>
              {t.label}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}

type Node = { level: string; ref_id: string; name?: string; metrics: Record<string, number> };
type Dash = { level: string; ref_id: string; metrics: Record<string, number>; updated_at: string | null; children: Node[] };

const METRICS: [string, string][] = [
  ["students", "Students"],
  ["capacity", "Capacity"],
  ["on_jobpilot", "On JobPilot"],
  ["sharing", "Sharing with college"],
  ["eligible", "Eligible for a drive"],
  ["applied", "Applied"],
  ["shortlisted", "Shortlisted"],
  ["placed", "Placed"],
  ["internship_all", "Internships"],
  ["students_with_verified_internship", "With a verified internship"],
  ["role_all", "Roles"],
  ["award_all", "Awards"],
  ["national_award_winners", "National+ award winners"],
];

function ago(iso: string | null) {
  if (!iso) return "not computed yet";
  const m = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  return m < 1 ? "just now" : `${m} min ago`;
}

/** College → degree → department → programme → batch: every number pre-aggregated; click to drill down. */
export function DrillDown() {
  const [path, setPath] = useState<{ level: string; ref_id: string; name: string }[]>([]);
  const at = path[path.length - 1];
  const { data, error } = useQuery({
    queryKey: ["campus-dash", at?.level ?? "campus", at?.ref_id ?? ""],
    queryFn: () => api.get<Dash>(`/campus/staff/dashboard?level=${at?.level ?? "campus"}&ref_id=${at?.ref_id ?? ""}`),
  });
  if (error) return <p className="text-[13px] text-[var(--error)]">{(error as Error).message}</p>;
  if (!data) return <div className="h-48 animate-pulse rounded-[var(--radius-card)] bg-surface-2" />;
  const m = data.metrics;
  const cap = m.capacity;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-1 text-[13px]">
        <button type="button" onClick={() => setPath([])} className="text-cobalt-text hover:underline">College</button>
        {path.map((p, i) => (
          <span key={p.ref_id} className="inline-flex items-center gap-1">
            <ChevronRight className="size-3.5 text-text-3" />
            <button type="button" onClick={() => setPath(path.slice(0, i + 1))} className="text-cobalt-text hover:underline">{p.name}</button>
          </span>
        ))}
        <span className="ml-auto text-[12px] text-text-3">Updated {ago(data.updated_at)}</span>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {METRICS.filter(([k]) => m[k] != null).map(([k, label]) => (
          <div key={k} className="card p-4">
            <div className="text-[12px] text-text-3">{label}</div>
            <div className="num mt-1 text-[22px] font-semibold">{(m[k] ?? 0).toLocaleString("en-IN")}</div>
            {k === "students" && cap != null && <div className="text-[12px] text-text-3">{(cap - (m.students ?? 0)).toLocaleString("en-IN")} seats left of {cap.toLocaleString("en-IN")}</div>}
          </div>
        ))}
      </div>
      {!!data.children.length && (
        <div className="card divide-y divide-border">
          {data.children.map((c) => (
            <button
              key={`${c.level}:${c.ref_id}`}
              type="button"
              onClick={() => setPath([...path, { level: c.level, ref_id: c.ref_id, name: c.name ?? c.ref_id }])}
              className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-elevated"
            >
              <span className="w-20 shrink-0 text-[11.5px] tracking-wide text-text-3 uppercase">{c.level}</span>
              <span className="min-w-0 flex-1 truncate text-[14px]">{c.name}</span>
              <span className="num text-[13px] text-text-2">{(c.metrics.students ?? 0).toLocaleString("en-IN")} students</span>
              {c.metrics.capacity != null && <span className="num hidden text-[12px] text-text-3 sm:inline">/ {c.metrics.capacity.toLocaleString("en-IN")}</span>}
              <ChevronRight className="size-4 text-text-3" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** Keyset-paginated list that only renders the rows on screen (smooth with lakhs of rows). */
export function KeysetList<T extends { id: string }>({ url, queryKey, render, rowHeight = 64, empty }: { url: string; queryKey: unknown[]; render: (row: T) => ReactNode; rowHeight?: number; empty?: ReactNode }) {
  const q = useInfiniteQuery({
    queryKey,
    initialPageParam: "",
    queryFn: ({ pageParam }) => api.get<{ items: T[]; next_cursor: string | null }>(`${url}${url.includes("?") ? "&" : "?"}limit=50${pageParam ? `&cursor=${pageParam}` : ""}`),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const rows = q.data?.pages.flatMap((p) => p.items) ?? [];
  const box = useRef<HTMLDivElement>(null);
  const [scroll, setScroll] = useState(0);
  const height = 560;
  const first = Math.max(0, Math.floor(scroll / rowHeight) - 5);
  const last = Math.min(rows.length, Math.ceil((scroll + height) / rowHeight) + 5);
  useEffect(() => {
    if (last >= rows.length - 10 && q.hasNextPage && !q.isFetchingNextPage) q.fetchNextPage();
  }, [last, rows.length, q]);
  if (q.isLoading) return <div className="h-40 animate-pulse rounded-[var(--radius-card)] bg-surface-2" />;
  if (!rows.length) return <div className="card p-8 text-center text-[14px] text-text-2">{empty ?? "Nothing here."}</div>;
  return (
    <div ref={box} onScroll={(e) => setScroll(e.currentTarget.scrollTop)} className="card overflow-y-auto" style={{ height: Math.min(height, rows.length * rowHeight + 2) }}>
      <div style={{ height: rows.length * rowHeight, position: "relative" }}>
        {rows.slice(first, last).map((r, i) => (
          <div key={r.id} style={{ position: "absolute", top: (first + i) * rowHeight, left: 0, right: 0, height: rowHeight }} className="border-b border-border">
            {render(r)}
          </div>
        ))}
      </div>
    </div>
  );
}

"use client";

import { format, parseISO } from "date-fns";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { Overview } from "@/lib/types";
import { usd } from "@/lib/utils";

/**
 * Chart conventions: series colours come from --series-1/2 (validated for both themes; status colours are
 * never series), a recessive grid, 2px lines, rounded bar ends on the baseline, and a hover tooltip on every chart.
 */
const AXIS = { fill: "var(--text-3)", fontSize: 11 };

function ChartTooltip({ active, payload, label, money }: { active?: boolean; payload?: { name: string; value: number; color: string }[]; label?: string; money?: boolean }) {
  if (!active || !payload?.length || !label) return null;
  return (
    <div className="rounded-[var(--radius-control)] border border-border-strong bg-surface px-3 py-2 text-[12px] shadow-[var(--shadow-2)]">
      <div className="mb-1 font-medium text-text">{format(parseISO(label), "EEE, d MMM")}</div>
      {payload.map((p) => (
        <div key={p.name} className="flex items-center gap-2 text-text-2">
          <span className="size-2 rounded-full" style={{ background: p.color }} />
          {p.name}
          <span className="num ml-auto pl-3 text-text">{money ? usd(p.value, 3) : p.value}</span>
        </div>
      ))}
    </div>
  );
}

export function Legend({ items }: { items: { label: string; color: string; dashed?: boolean }[] }) {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-[12.5px] text-text-2">
      {items.map((i) => (
        <li key={i.label} className="flex items-center gap-2">
          <svg width="18" height="8" aria-hidden>
            <line x1="1" y1="4" x2="17" y2="4" stroke={i.color} strokeWidth="2" strokeDasharray={i.dashed ? "4 3" : undefined} strokeLinecap="round" />
          </svg>
          {i.label}
        </li>
      ))}
    </ul>
  );
}

/** Jobs matched (area) and applications sent (dashed line) per day. */
export function ActivityChart({ data }: { data: Overview["daily"] }) {
  return (
    <div className="space-y-3">
      <Legend
        items={[
          { label: "Matched", color: "var(--series-1)" },
          { label: "Applied", color: "var(--series-2)", dashed: true },
        ]}
      />
      <ResponsiveContainer width="100%" height={220}>
        <AreaChart data={data} margin={{ top: 8, right: 8, left: -24, bottom: 0 }}>
          <defs>
            <linearGradient id="gFound" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--series-1)" stopOpacity={0.28} />
              <stop offset="100%" stopColor="var(--series-1)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} stroke="var(--border)" />
          <XAxis dataKey="day" tickFormatter={(d) => format(parseISO(d), "d MMM")} tick={AXIS} axisLine={false} tickLine={false} minTickGap={24} />
          <YAxis allowDecimals={false} tick={AXIS} axisLine={false} tickLine={false} />
          <Tooltip content={<ChartTooltip />} cursor={{ stroke: "var(--border-strong)" }} />
          <Area type="monotone" dataKey="found" name="Matched" stroke="var(--series-1)" strokeWidth={2} fill="url(#gFound)" activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--surface)" }} />
          <Line type="monotone" dataKey="applied" name="Applied" stroke="var(--series-2)" strokeWidth={2} strokeDasharray="5 4" dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--surface)" }} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

/** LLM spend per day: one series, so the title names it and no legend is needed. */
export function SpendChart({ data }: { data: Overview["daily"] }) {
  return (
    <ResponsiveContainer width="100%" height={180}>
      <BarChart data={data.map((d) => ({ ...d, cost_usd: Number(d.cost_usd) }))} margin={{ top: 8, right: 8, left: -12, bottom: 0 }} barCategoryGap={2}>
        <CartesianGrid vertical={false} stroke="var(--border)" />
        <XAxis dataKey="day" tickFormatter={(d) => format(parseISO(d), "d MMM")} tick={AXIS} axisLine={false} tickLine={false} minTickGap={24} />
        <YAxis tick={AXIS} axisLine={false} tickLine={false} tickFormatter={(v: number) => `$${v.toFixed(2)}`} width={52} />
        <Tooltip content={<ChartTooltip money />} cursor={{ fill: "var(--elevated)" }} />
        <Bar dataKey="cost_usd" name="Spend" fill="var(--series-1)" radius={[4, 4, 0, 0]} maxBarSize={28} />
      </BarChart>
    </ResponsiveContainer>
  );
}

/**
 * Horizontal bars in plain HTML: each row is labelled with its value, so it reads without colour
 * and doubles as the table view.
 */
export function BarList({ rows, unit = "", empty }: { rows: { label: string; value: number; note?: string }[]; unit?: string; empty: string }) {
  if (!rows.length) return <p className="py-4 text-[13px] text-text-3">{empty}</p>;
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <ul className="space-y-3">
      {rows.map((r) => (
        <li key={r.label} title={`${r.label}: ${r.value}${unit}${r.note ? ` · ${r.note}` : ""}`}>
          <div className="mb-1.5 flex items-baseline justify-between gap-3 text-[13px]">
            <span className="truncate text-text">{r.label}</span>
            <span className="num shrink-0 text-text-2">
              {r.value}
              {unit}
              {r.note && <span className="text-text-3"> · {r.note}</span>}
            </span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-elevated-2">
            <div className="h-full origin-left rounded-full bg-[var(--series-1)] transition-transform duration-[var(--dur-slow)] ease-[var(--ease)]" style={{ transform: `scaleX(${r.value / max})` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

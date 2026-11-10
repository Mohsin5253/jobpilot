import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/** A tiny 7-day trend line: pure SVG, no chart library, scales to its container. */
export function Sparkline({ data, className }: { data: number[]; className?: string }) {
  if (data.length < 2) return null;
  const max = Math.max(...data, 1);
  const min = Math.min(...data, 0);
  const span = max - min || 1;
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * 100},${28 - ((v - min) / span) * 24}`).join(" ");
  return (
    <svg viewBox="0 0 100 30" preserveAspectRatio="none" aria-hidden className={cn("h-7 w-full", className)}>
      <polyline points={pts} fill="none" stroke="var(--cobalt)" strokeWidth="1.5" vectorEffect="non-scaling-stroke" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/**
 * Label, mono value, sub-line, 7-day sparkline and delta chip. When the value is zero, `empty`
 * explains why ("No replies yet. First replies usually arrive in 5–10 days").
 */
export function StatCard({
  label,
  value,
  sub,
  trend,
  delta,
  empty,
  icon,
  href,
  highlight,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  trend?: number[];
  /** Change vs the previous period, in the value's own unit. */
  delta?: { value: number; suffix?: string; goodWhenUp?: boolean };
  empty?: string;
  icon?: ReactNode;
  href?: string;
  highlight?: boolean;
}) {
  const isZero = value === 0 || value === "0" || value === "0%";
  const up = delta && delta.value > 0;
  const good = delta && (delta.goodWhenUp ?? true) === (delta.value > 0);
  const body = (
    <div
      className={cn(
        "card group flex h-full min-w-0 flex-col p-4 transition-colors duration-[var(--dur-fast)] [container-type:inline-size]",
        href && "hover:border-border-strong",
        highlight && "border-[color-mix(in_oklab,var(--your-turn-fill)_35%,transparent)]",
      )}
    >
      <div className="flex items-center justify-between gap-2 text-[13px] text-text-2">
        <span className="truncate">{label}</span>
        {icon && <span className="text-text-3 [&_svg]:size-4">{icon}</span>}
      </div>
      <div className="mt-2 flex items-baseline gap-2">
        <span className="num text-[28px] leading-none font-semibold tracking-[-0.02em]">{value}</span>
        {delta && delta.value !== 0 && (
          <span
            className={cn("num inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[11.5px] font-medium [&_svg]:size-3")}
            style={{ color: good ? "var(--done)" : "var(--error)", background: `color-mix(in oklab, ${good ? "var(--done)" : "var(--error)"} 12%, transparent)` }}
          >
            {up ? <ArrowUpRight /> : <ArrowDownRight />}
            {Math.abs(delta.value)}
            {delta.suffix}
          </span>
        )}
      </div>
      <div className="mt-1 min-h-[18px] text-[12.5px] leading-snug text-text-3">{isZero && empty ? empty : sub}</div>
      {trend && trend.some((v) => v > 0) && <Sparkline data={trend} className="mt-auto pt-2" />}
    </div>
  );
  return href ? (
    <Link href={href} className="block h-full rounded-[var(--radius-card)]">
      {body}
    </Link>
  ) : (
    body
  );
}

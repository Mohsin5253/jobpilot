"use client";

import { motion, useReducedMotion } from "motion/react";

import { cn } from "@/lib/utils";

/** <50 rose · 50–74 amber · 75–89 green · 90+ green with a soft glow. */
export function scoreColor(score: number) {
  if (score >= 75) return "var(--score-good)";
  if (score >= 50) return "var(--score-mid)";
  return "var(--score-low)";
}

function Ring({ pct, size, stroke, color, glow, children, label }: { pct: number; size: number; stroke: number; color: string; glow?: boolean; children: React.ReactNode; label: string }) {
  const reduce = useReducedMotion();
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  return (
    <div role="img" aria-label={label} className="relative grid shrink-0 place-items-center" style={{ width: size, height: size, filter: glow ? `drop-shadow(0 0 6px color-mix(in oklab, ${color} 55%, transparent))` : undefined }}>
      <svg width={size} height={size} className="-rotate-90" aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--elevated-2)" strokeWidth={stroke} />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={c}
          initial={{ strokeDashoffset: reduce ? c * (1 - pct) : c }}
          animate={{ strokeDashoffset: c * (1 - pct) }}
          transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
        />
      </svg>
      <span className="absolute inset-0 grid place-items-center">{children}</span>
    </div>
  );
}

export function ScoreRing({ score, size = 44, stroke = 4, className, label = true }: { score: number; size?: number; stroke?: number; className?: string; label?: boolean }) {
  const s = Math.max(0, Math.min(100, score));
  return (
    <div className={className}>
      <Ring pct={s / 100} size={size} stroke={stroke} color={scoreColor(s)} glow={s >= 90} label={`Match score ${Math.round(s)} out of 100`}>
        {label && (
          <span className="num font-semibold" style={{ fontSize: Math.max(11, size * 0.3) }}>
            {Math.round(s)}
          </span>
        )}
      </Ring>
    </div>
  );
}

/** The weekly goal: the value always sits inside the ring ("3/10"), never an empty ring. */
export function GoalRing({
  value,
  goal,
  size = 64,
  label = "Quality applications this week",
  hideLabel = false,
  className,
}: {
  value: number;
  goal: number;
  size?: number;
  label?: string;
  /** The label still names the ring for screen readers; hide it when the caller shows its own. */
  hideLabel?: boolean;
  className?: string;
}) {
  const pct = goal > 0 ? Math.min(1, value / goal) : 0;
  return (
    <div className={cn("flex items-center gap-3", className)}>
      <Ring pct={pct} size={size} stroke={Math.max(4, size * 0.08)} color="var(--cobalt)" label={`${label}: ${value} of ${goal}`}>
        <span className="num font-semibold leading-none" style={{ fontSize: size * 0.22 }}>
          {value}
          <span className="text-text-3">/{goal}</span>
        </span>
      </Ring>
      {!hideLabel && <span className="text-[13px] leading-snug text-text-2">{label}</span>}
    </div>
  );
}

export function ScoreBar({ label, value, hint }: { label: string; value: number | null; hint?: string }) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between text-[13px]">
        <span className="text-text-2">{label}</span>
        <span className="num">{value == null ? <span className="text-text-3">{hint ?? "n/a"}</span> : Math.round(value)}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-elevated-2">
        <motion.div
          className="h-full rounded-full"
          style={{ background: value == null ? "transparent" : scoreColor(value) }}
          initial={{ width: 0 }}
          animate={{ width: `${value ?? 0}%` }}
          transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
        />
      </div>
    </div>
  );
}

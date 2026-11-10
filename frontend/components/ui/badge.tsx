import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

type Tone = "neutral" | "accent" | "success" | "warning" | "danger" | "outline";

const mix = (v: string, pct: number) => `color-mix(in oklab, var(${v}) ${pct}%, transparent)`;

const tones: Record<Tone, React.CSSProperties> = {
  neutral: {},
  accent: { color: "var(--cobalt-text)", background: "var(--cobalt-subtle)", borderColor: mix("--cobalt", 25) },
  success: { color: "var(--done)", background: mix("--done", 10), borderColor: mix("--done", 25) },
  warning: { color: "var(--your-turn)", background: mix("--your-turn-fill", 12), borderColor: mix("--your-turn-fill", 30) },
  danger: { color: "var(--error)", background: mix("--error", 10), borderColor: mix("--error", 25) },
  outline: { background: "transparent", borderColor: "var(--border-strong)" },
};

export function Badge({ tone = "neutral", className, style, ...props }: HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[12px] leading-4 font-medium whitespace-nowrap [&_svg]:size-3",
        tone === "neutral" && "border-border bg-elevated text-text-2",
        tone === "outline" && "text-text-2",
        className,
      )}
      style={{ ...tones[tone], ...style }}
      {...props}
    />
  );
}

export function Dot({ className }: { className?: string }) {
  return <span className={cn("inline-block size-1.5 rounded-full bg-current", className)} />;
}

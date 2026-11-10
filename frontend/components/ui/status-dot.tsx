import type { AgentStatus } from "@/components/agents/agent-avatar";
import { cn } from "@/lib/utils";

const COLOR: Record<AgentStatus, string> = {
  idle: "var(--text-3)",
  off: "var(--text-3)",
  running: "var(--running)",
  done: "var(--done)",
  "your-turn": "var(--your-turn-fill)",
  error: "var(--error)",
};

const LABEL: Record<AgentStatus, string> = { idle: "Idle", off: "Skipped", running: "Running", done: "Done", "your-turn": "Your turn", error: "Error" };

/** Status as a dot and (optionally) a word: colour never carries the meaning alone. */
export function StatusDot({ status, label, className }: { status: AgentStatus; label?: boolean | string; className?: string }) {
  const pulsing = status === "running" || status === "your-turn";
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-[12.5px] text-text-2", className)}>
      <span className="relative inline-flex size-2">
        {pulsing && <span className="absolute inset-0 animate-ping rounded-full opacity-60" style={{ background: COLOR[status] }} />}
        <span className="relative size-2 rounded-full" style={{ background: COLOR[status] }} />
      </span>
      {label !== false && <span>{typeof label === "string" ? label : LABEL[status]}</span>}
    </span>
  );
}

export function StatusPill({ status, children }: { status: AgentStatus; children?: React.ReactNode }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[12px] font-medium"
      style={{ borderColor: `color-mix(in oklab, ${COLOR[status]} 30%, transparent)`, background: `color-mix(in oklab, ${COLOR[status]} 10%, transparent)`, color: status === "idle" || status === "off" ? "var(--text-2)" : COLOR[status] }}
    >
      <span className="size-1.5 rounded-full bg-current" />
      {children ?? LABEL[status]}
    </span>
  );
}

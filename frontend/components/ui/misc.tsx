import type { ReactNode } from "react";

import { AgentAvatar, AgentHero } from "@/components/agents/agent-avatar";
import { AGENTS, type AgentKey } from "@/config/agents";
import { cn } from "@/lib/utils";

/** Loading placeholder. With `agent`, the responsible agent's working image (64px) sits above it. */
export function Skeleton({ className, agent }: { className?: string; agent?: AgentKey }) {
  if (!agent) return <div aria-hidden className={cn("skeleton", className)} />;
  return (
    <div role="status" aria-live="polite" className={cn("flex flex-col items-center justify-center gap-3 rounded-[var(--radius-card)] border border-border bg-surface", className)}>
      <AgentAvatar agent={agent} status="running" size={64} decorative />
      <span className="text-[13px] text-text-2">{AGENTS[agent].name} is working…</span>
      <div className="w-2/3 max-w-sm space-y-2">
        <div className="skeleton h-3" />
        <div className="skeleton h-3 w-4/5" />
      </div>
    </div>
  );
}

/**
 * Empty state, said in first person by the responsible agent (160px character), with one action.
 * Without `agent`, a quiet icon version for dense views.
 */
export function EmptyState({
  icon,
  agent,
  title,
  description,
  action,
  className,
}: {
  icon?: ReactNode;
  agent?: AgentKey;
  title?: string;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  const copy = agent ? AGENTS[agent].empty : null;
  return (
    <div className={cn("flex flex-col items-center justify-center px-6 py-14 text-center", className)}>
      {agent ? (
        <AgentHero agent={agent} size={160} priority={false} className="mb-6" />
      ) : (
        icon && <div className="mb-4 grid size-11 place-items-center rounded-[var(--radius-card)] border border-border bg-elevated text-text-2 [&_svg]:size-5">{icon}</div>
      )}
      {agent && <div className="eyebrow mb-1.5">{AGENTS[agent].name}</div>}
      <h3 className="text-[16px] font-semibold tracking-[-0.01em]">{title ?? copy?.title}</h3>
      {(description ?? copy?.body) && <p className="mt-1 max-w-sm text-[14px] text-text-2">{description ?? copy?.body}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="num rounded-[5px] border border-border-strong bg-elevated px-1.5 py-0.5 text-[11px] text-text-2">{children}</kbd>;
}

export function PageHeader({ title, description, action, eyebrow }: { title: string; description?: ReactNode; action?: ReactNode; eyebrow?: string }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && <div className="eyebrow mb-1.5">{eyebrow}</div>}
        <h1 className="font-display text-[clamp(24px,3vw,32px)] leading-[1.1]">{title}</h1>
        {description && <p className="mt-1.5 max-w-2xl text-[14px] text-text-2">{description}</p>}
      </div>
      {action}
    </div>
  );
}

export function Segmented<T extends string>({ value, onChange, options }: { value: T; onChange: (v: T) => void; options: { value: T; label: ReactNode }[] }) {
  return (
    <div role="tablist" className="inline-flex rounded-[var(--radius-control)] border border-border bg-elevated p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="tab"
          aria-selected={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            "min-h-11 rounded-[6px] px-3 py-1 text-[13px] font-medium transition-colors duration-[var(--dur-fast)] md:min-h-0",
            value === o.value ? "bg-surface text-text shadow-[var(--highlight)] ring-1 ring-border" : "text-text-2 hover:text-text",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

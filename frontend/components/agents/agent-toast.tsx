"use client";

import { toast } from "sonner";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { AGENTS, type AgentKey } from "@/config/agents";

/**
 * Toasts are said by the responsible agent: "Outreach · Drafted 4 emails for your review".
 * 32px avatar, agent name, message, one optional action.
 */
export function agentToast(agent: AgentKey, message: string, opts?: { action?: { label: string; onClick: () => void }; duration?: number }) {
  return toast.custom(
    (id) => (
      <div role="status" className="panel flex w-[min(380px,calc(100vw-32px))] items-start gap-3 p-3.5">
        <AgentAvatar agent={agent} size={32} decorative />
        <div className="min-w-0 flex-1">
          <div className="text-[12px] font-medium text-text-3">{AGENTS[agent].name}</div>
          <div className="text-[13.5px] leading-snug text-text">{message}</div>
        </div>
        {opts?.action && (
          <button
            type="button"
            onClick={() => {
              opts.action!.onClick();
              toast.dismiss(id);
            }}
            className="shrink-0 rounded-[var(--radius-control)] px-2 py-1 text-[13px] font-medium text-[var(--cobalt-text)] hover:bg-[var(--cobalt-subtle)]"
          >
            {opts.action.label}
          </button>
        )}
      </div>
    ),
    { duration: opts?.duration ?? 6000 },
  );
}

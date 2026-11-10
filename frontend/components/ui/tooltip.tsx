"use client";

import * as T from "@radix-ui/react-tooltip";
import type { ReactNode } from "react";

export const TooltipProvider = T.Provider;

/** A label for icon-only controls (the sidebar rail). `disabled` renders the child alone. */
export function Tooltip({ label, side = "right", disabled = false, children }: { label: ReactNode; side?: "top" | "right" | "bottom" | "left"; disabled?: boolean; children: ReactNode }) {
  if (disabled) return <>{children}</>;
  return (
    <T.Root>
      <T.Trigger asChild>{children}</T.Trigger>
      <T.Portal>
        <T.Content
          side={side}
          sideOffset={8}
          className="z-[95] rounded-[var(--radius-control)] border border-border-strong bg-elevated px-2 py-1 text-[12.5px] font-medium text-text shadow-[var(--shadow-2)] data-[state=delayed-open]:animate-[fade-in_var(--dur-fast)_var(--ease)]"
        >
          {label}
        </T.Content>
      </T.Portal>
    </T.Root>
  );
}

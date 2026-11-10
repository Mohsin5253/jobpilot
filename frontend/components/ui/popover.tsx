"use client";

import * as P from "@radix-ui/react-popover";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export const Popover = P.Root;
export const PopoverTrigger = P.Trigger;
export const PopoverClose = P.Close;

/** A floating panel that stays inside the viewport (12px from every edge on phones). */
export function PopoverContent({ children, className, align = "end", side = "bottom", label }: { children: ReactNode; className?: string; align?: "start" | "center" | "end"; side?: "top" | "right" | "bottom" | "left"; label?: string }) {
  return (
    <P.Portal>
      <P.Content
        align={align}
        side={side}
        sideOffset={8}
        collisionPadding={12}
        aria-label={label}
        className={cn("panel z-[85] overflow-hidden outline-none data-[state=open]:animate-[pop-in_var(--dur-base)_var(--ease)]", className)}
      >
        {children}
      </P.Content>
    </P.Portal>
  );
}

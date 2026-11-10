"use client";

import * as D from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export const Sheet = D.Root;
export const SheetTrigger = D.Trigger;
export const SheetClose = D.Close;

/**
 * A side sheet on desktop (right, or left for the nav drawer) that becomes a bottom sheet under 768px.
 * `full` makes it full-screen on mobile (e.g. a job's detail).
 */
export function SheetContent({
  title,
  description,
  side = "right",
  full = false,
  hideHeader = false,
  children,
  className,
}: {
  title: string;
  description?: ReactNode;
  side?: "right" | "left";
  full?: boolean;
  hideHeader?: boolean;
  children: ReactNode;
  className?: string;
}) {
  return (
    <D.Portal>
      <D.Overlay className="fixed inset-0 z-[80] bg-black/50 data-[state=open]:animate-[fade-in_var(--dur-base)_var(--ease)]" />
      <D.Content
        className={cn(
          "fixed z-[81] flex flex-col bg-surface outline-none",
          // mobile: bottom sheet (or full screen)
          full ? "inset-0" : "inset-x-0 bottom-0 max-h-[88dvh] rounded-t-[var(--radius-panel)] border-t border-border",
          "data-[state=open]:animate-[sheet-up_var(--dur-slow)_var(--ease)]",
          // ≥768px: a side sheet
          "md:inset-y-0 md:bottom-auto md:h-dvh md:max-h-none md:w-[min(560px,92vw)] md:rounded-none md:border-t-0",
          side === "right" ? "md:right-0 md:left-auto md:border-l md:data-[state=open]:animate-[sheet-left_var(--dur-slow)_var(--ease)]" : "md:right-auto md:left-0 md:border-r md:data-[state=open]:animate-[sheet-right_var(--dur-slow)_var(--ease)]",
          className,
        )}
      >
        {!full && <span aria-hidden className="mx-auto mt-2 h-1 w-10 rounded-full bg-border-strong md:hidden" />}
        <div className={cn("flex items-start justify-between gap-4 border-b border-border px-5 py-4", hideHeader && "sr-only")}>
          <div className="min-w-0">
            <D.Title className="truncate text-[15px] font-semibold">{title}</D.Title>
            {description ? <D.Description className="mt-0.5 text-[13px] text-text-2">{description}</D.Description> : <D.Description className="sr-only">{title}</D.Description>}
          </div>
          <D.Close aria-label="Close" className="grid size-11 shrink-0 place-items-center rounded-[var(--radius-control)] text-text-3 hover:bg-elevated hover:text-text md:size-8">
            <X className="size-4" />
          </D.Close>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">{children}</div>
      </D.Content>
    </D.Portal>
  );
}

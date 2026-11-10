"use client";

import * as D from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export const Dialog = D.Root;
export const DialogTrigger = D.Trigger;
export const DialogClose = D.Close;

const overlay = "fixed inset-0 z-[80] bg-black/55 backdrop-blur-[2px] data-[state=open]:animate-[fade-in_var(--dur-base)_var(--ease)]";

/** Centered modal: focus-trapped, Esc to close, labelled by its title. */
export function DialogContent({ title, description, children, className }: { title: string; description?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <D.Portal>
      <D.Overlay className={overlay} />
      <D.Content
        className={cn(
          "panel fixed top-1/2 left-1/2 z-[81] w-[calc(100vw-32px)] max-w-lg -translate-x-1/2 -translate-y-1/2 p-6 outline-none data-[state=open]:animate-[dialog-in_var(--dur-base)_var(--ease)]",
          className,
        )}
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <D.Title className="text-[16px] font-semibold tracking-[-0.01em]">{title}</D.Title>
            {description ? <D.Description className="mt-1 text-[13.5px] text-text-2">{description}</D.Description> : <D.Description className="sr-only">{title}</D.Description>}
          </div>
          <D.Close aria-label="Close" className="grid size-8 place-items-center rounded-[var(--radius-control)] text-text-3 hover:bg-elevated hover:text-text">
            <X className="size-4" />
          </D.Close>
        </div>
        {children}
      </D.Content>
    </D.Portal>
  );
}

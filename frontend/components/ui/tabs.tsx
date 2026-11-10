"use client";

import * as T from "@radix-ui/react-tabs";
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

export const Tabs = T.Root;

export function TabsList({ className, ...props }: ComponentProps<typeof T.List>) {
  return <T.List className={cn("flex gap-1 overflow-x-auto border-b border-border [scrollbar-width:none]", className)} {...props} />;
}

export function TabsTrigger({ className, ...props }: ComponentProps<typeof T.Trigger>) {
  return (
    <T.Trigger
      className={cn(
        "relative -mb-px inline-flex h-10 shrink-0 items-center gap-1.5 border-b-2 border-transparent px-3 text-[13.5px] font-medium text-text-2 transition-colors duration-[var(--dur-fast)] hover:text-text data-[state=active]:border-[var(--cobalt)] data-[state=active]:text-text [&_svg]:size-4",
        className,
      )}
      {...props}
    />
  );
}

export function TabsContent({ className, ...props }: ComponentProps<typeof T.Content>) {
  return <T.Content className={cn("outline-none data-[state=active]:animate-[fade-in_var(--dur-base)_var(--ease)]", className)} {...props} />;
}

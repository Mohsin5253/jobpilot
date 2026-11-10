import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/utils";

/** 12px card: 1px border + top inner highlight. */
export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("card", className)} {...props} />;
}

/** 16px panel: a larger grouping surface (e.g. Pilot Console + Flight path). */
export function Panel({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("panel", className)} {...props} />;
}

export function CardHeader({ title, description, action, icon }: { title: ReactNode; description?: ReactNode; action?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 px-5 pt-5">
      <div className="flex min-w-0 items-start gap-3">
        {icon && <div className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-[var(--radius-control)] border border-border bg-elevated text-text-2 [&_svg]:size-4">{icon}</div>}
        <div className="min-w-0">
          <h3 className="text-[15px] font-semibold tracking-[-0.01em]">{title}</h3>
          {description && <p className="mt-0.5 text-[13px] text-text-2">{description}</p>}
        </div>
      </div>
      {action}
    </div>
  );
}

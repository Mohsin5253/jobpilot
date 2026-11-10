import { forwardRef, type InputHTMLAttributes, type ReactNode, type TextareaHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

const field =
  "w-full rounded-[var(--radius-control)] border border-border bg-surface px-3 text-sm text-text placeholder:text-text-3 transition-[border-color,box-shadow] duration-[var(--dur-fast)] hover:border-border-strong focus:border-[var(--cobalt)] focus:outline-none focus:ring-2 focus:ring-[var(--cobalt-subtle)]";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...p }, ref) {
  return <input ref={ref} className={cn(field, "h-10", className)} {...p} />;
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea(
  { className, ...p },
  ref,
) {
  return <textarea ref={ref} className={cn(field, "min-h-24 py-2.5 leading-relaxed", className)} {...p} />;
});

export function Field({ label, hint, children, className }: { label: ReactNode; hint?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <label className={cn("block space-y-1.5", className)}>
      <span className="text-[13px] font-medium text-fg">{label}</span>
      {children}
      {hint && <span className="block text-xs text-subtle">{hint}</span>}
    </label>
  );
}

export function Switch({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label?: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border transition-colors",
        checked ? "border-transparent bg-cobalt" : "border-border-strong bg-elevated-2",
      )}
    >
      <span className={cn("size-4 rounded-full bg-white shadow transition-transform duration-[var(--dur-base)] ease-[var(--ease)]", checked ? "translate-x-[18px]" : "translate-x-0.5")} />
    </button>
  );
}

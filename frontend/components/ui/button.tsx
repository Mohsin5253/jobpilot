import { Loader2 } from "lucide-react";
import { forwardRef, type ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "ghost" | "outline" | "danger" | "success";
type Size = "sm" | "md" | "lg" | "icon";

const variants: Record<Variant, string> = {
  primary: "bg-[var(--cobalt)] text-[var(--on-cobalt)] shadow-[inset_0_1px_0_rgba(255,255,255,0.18)] hover:bg-[var(--cobalt-hover)]",
  secondary: "bg-elevated text-text border border-border shadow-[var(--highlight)] hover:border-border-strong hover:bg-elevated-2",
  ghost: "text-text-2 hover:text-text hover:bg-elevated",
  outline: "border border-border-strong text-text hover:bg-elevated",
  danger: "text-[var(--error)] border border-[color-mix(in_oklab,var(--error)_30%,transparent)] hover:bg-[color-mix(in_oklab,var(--error)_10%,transparent)]",
  success: "text-[var(--done)] border border-[color-mix(in_oklab,var(--done)_30%,transparent)] hover:bg-[color-mix(in_oklab,var(--done)_10%,transparent)]",
};
const sizes: Record<Size, string> = {
  sm: "h-8 px-3 text-[13px] gap-1.5",
  md: "h-9 px-3.5 text-sm gap-2",
  lg: "h-11 px-5 text-[15px] gap-2",
  icon: "size-9",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
}

const base =
  "inline-flex select-none items-center justify-center rounded-[var(--radius-control)] font-medium whitespace-nowrap transition-[background-color,border-color,color,opacity,transform] duration-[var(--dur-fast)] ease-[var(--ease)] active:translate-y-px disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0";

/** Button styling for links that act as buttons (`<Link className={buttonClass(...)}>`). */
export function buttonClass({ variant = "secondary", size = "md", className }: { variant?: Variant; size?: Size; className?: string } = {}) {
  return cn(base, variants[variant], sizes[size], className);
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", loading, className, children, disabled, ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={buttonClass({ variant, size, className })}
      {...props}
    >
      {loading && <Loader2 className="animate-spin" />}
      {children}
    </button>
  );
});

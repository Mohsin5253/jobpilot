import { clsx, type ClassValue } from "clsx";
import { formatDistanceToNowStrict } from "date-fns";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function ago(iso?: string | null) {
  if (!iso) return "—";
  return formatDistanceToNowStrict(new Date(iso), { addSuffix: true });
}

export function usd(n: number, digits = 2) {
  if (!n) return "$0.00";
  if (n < 0.01) return `$${n.toPrecision(digits)}`; // sub-cent LLM calls: show significant digits, not $0.0000
  return `$${n.toFixed(2)}`;
}

export function ms(n?: number | null) {
  if (n == null) return "—";
  if (n < 1000) return `${Math.round(n)} ms`;
  if (n < 60_000) return `${(n / 1000).toFixed(1)} s`;
  return `${Math.floor(n / 60_000)}m ${Math.round((n % 60_000) / 1000)}s`;
}

export function compact(n: number) {
  return Intl.NumberFormat("en", { notation: "compact" }).format(n);
}

export function scoreTone(score: number) {
  if (score >= 75) return "text-success";
  if (score >= 55) return "text-accent";
  if (score >= 40) return "text-warning";
  return "text-subtle";
}

export function salary(min?: number | null, max?: number | null) {
  if (!min && !max) return null;
  const f = (n: number) => Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 }).format(n);
  return min && max ? `${f(min)}–${f(max)}` : f((min ?? max)!);
}

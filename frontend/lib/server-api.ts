/**
 * Server-side calls to the API (server components only; the browser goes through the /api rewrite).
 * The origin is normalised like in next.config.ts: a trailing "/" or "/api" is dropped.
 */
export const API_URL = (process.env.API_URL?.trim() || "http://localhost:8000").replace(/\/+$/, "").replace(/\/api$/, "");

export type PublicStats = {
  beta: boolean;
  postings_verified: number;
  scams_flagged: number;
  applications_approved: number;
  runs_counted: number;
  avg_cost_inr_per_run: number | null;
  usd_inr_rate: number;
  cost_window_days: number;
  as_of: string;
};

/**
 * Live beta counters, cached for five minutes (the API caches for the same time). The free-tier API can be
 * asleep, so the wait is capped: the page renders without numbers rather than waiting a minute for them.
 */
export async function getPublicStats(): Promise<PublicStats | null> {
  try {
    const res = await fetch(`${API_URL}/api/public/stats`, { next: { revalidate: 300 }, signal: AbortSignal.timeout(4000) });
    return res.ok ? ((await res.json()) as PublicStats) : null;
  } catch {
    return null;
  }
}

/** "₹0.42" for small amounts, "₹12" for larger ones. */
export function formatInr(n: number): string {
  return `₹${n < 10 ? n.toFixed(2) : Math.round(n).toLocaleString("en-IN")}`;
}

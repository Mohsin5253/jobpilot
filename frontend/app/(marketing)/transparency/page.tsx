import type { Metadata } from "next";
import Link from "next/link";

import { API_URL } from "@/lib/server-api";

export const metadata: Metadata = {
  title: "Transparency report",
  description: "Monthly totals from JobPilot's own tables: postings verified, scams blocked, applications approved, scam checks and the average AI cost per run.",
  alternates: { canonical: "/transparency" },
};
export const revalidate = 3600;

type Month = { month: string; postings_verified: number; scams_flagged: number; sends_approved: number; scam_checks: number; avg_cost_inr: number | null };

async function load(): Promise<Month[] | null> {
  try {
    const r = await fetch(`${API_URL}/api/public/transparency`, { next: { revalidate: 3600 }, signal: AbortSignal.timeout(4000) });
    return r.ok ? (await r.json()).months : null;
  } catch {
    return null;
  }
}

const n = (v: number) => v.toLocaleString("en-IN");
const monthName = (m: string) => new Date(`${m}-01T00:00:00Z`).toLocaleDateString("en-IN", { month: "long", year: "numeric", timeZone: "UTC" });

export default async function TransparencyPage() {
  const months = await load();
  return (
    <article className="mx-auto max-w-4xl px-4 py-16 sm:px-6">
      <div className="eyebrow mb-3">Transparency</div>
      <h1 className="font-display text-[clamp(34px,6vw,52px)] leading-[1.04]">What JobPilot did, month by month.</h1>
      <p className="mt-4 text-[16px] leading-relaxed text-text-2">
        Totals computed every day from our own tables: counts only, never anyone’s data. Demo accounts are excluded from the cost. See the{" "}
        <Link href="/trust" className="text-cobalt-text hover:underline">
          Trust page
        </Link>{" "}
        for how each number is checked.
      </p>
      {months?.length ? (
        <div className="card mt-10 overflow-x-auto">
          <table className="w-full min-w-[560px] text-left text-[14px]">
            <caption className="sr-only">Monthly totals</caption>
            <thead className="border-b border-border bg-elevated text-[12.5px] text-text-3">
              <tr>
                {["Month", "Postings verified", "Scams blocked", "Scam checks", "Applications approved", "Avg AI cost / run"].map((h) => (
                  <th key={h} scope="col" className="px-4 py-2.5 font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="num divide-y divide-border">
              {months.map((m) => (
                <tr key={m.month}>
                  <th scope="row" className="px-4 py-3 font-sans font-medium text-text">
                    {monthName(m.month)}
                  </th>
                  <td className="px-4 py-3">{n(m.postings_verified)}</td>
                  <td className="px-4 py-3">{n(m.scams_flagged)}</td>
                  <td className="px-4 py-3">{n(m.scam_checks)}</td>
                  <td className="px-4 py-3">{n(m.sends_approved)}</td>
                  <td className="px-4 py-3">{m.avg_cost_inr == null ? "—" : `₹${m.avg_cost_inr.toFixed(2)}`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="mt-10 text-[15px] text-text-2">The first report appears after the first full day of the beta.</p>
      )}
    </article>
  );
}

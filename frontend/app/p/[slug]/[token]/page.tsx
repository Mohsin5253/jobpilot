import { BadgeCheck, CalendarCheck, ShieldCheck, Trophy } from "lucide-react";
import type { Metadata } from "next";
import { headers } from "next/headers";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Logo } from "@/components/logo";
import { ProofView } from "@/components/proof-card";
import { API_URL } from "@/lib/server-api";
import type { PublicProof } from "@/lib/types";

type Application = {
  student: string;
  role: string;
  company: string;
  approved_at: string;
  applications_this_week: number;
  claims_source_verified: boolean;
  github_verified: boolean;
  github_username: string | null;
  codeforces_rating: number | null;
};
type Data = { proof: PublicProof; application: Application; signature: string; public_key: string; verify_url: string };

// Every request is one server-side view, so this page is never cached.
export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Proof of work", robots: { index: false, follow: false } };

async function load(slug: string, token: string): Promise<Data | null> {
  const ua = (await headers()).get("user-agent") ?? "";
  const res = await fetch(`${API_URL}/api/public/proof-link/${encodeURIComponent(slug)}/${encodeURIComponent(token)}`, {
    cache: "no-store",
    headers: { "x-viewer-ua": ua.slice(0, 300) },
  });
  return res.ok ? res.json() : null;
}

const fmt = (iso: string) => new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "long", year: "numeric", hour: "numeric", minute: "2-digit", timeZone: "Asia/Kolkata" });

export default async function SignedProofPage({ params }: { params: Promise<{ slug: string; token: string }> }) {
  const { slug, token } = await params;
  const data = await load(slug, token);
  if (!data) notFound();
  const { proof, application: a } = data;
  const facts = [
    { icon: CalendarCheck, text: `Human-approved by the student on ${fmt(a.approved_at)} IST` },
    { icon: ShieldCheck, text: a.claims_source_verified ? "All claims source-verified" : "Resume not tailored for this application", ok: a.claims_source_verified },
    { icon: BadgeCheck, text: a.github_verified ? `GitHub ownership verified (@${a.github_username})` : "GitHub not linked", ok: a.github_verified },
    ...(a.codeforces_rating ? [{ icon: Trophy, text: `Codeforces rating ${a.codeforces_rating}`, ok: true }] : []),
  ];
  return (
    <div className="min-h-dvh">
      <main className="relative mx-auto max-w-4xl px-4 py-12 sm:px-6">
        <div className="eyebrow">
          Application to {a.company} · {a.role}
        </div>
        <h1 className="mt-3 font-display text-[44px] leading-[1.02] sm:text-[60px]">{proof.name}</h1>
        {proof.headline && <p className="mt-2 text-[16px] text-muted">{proof.headline}</p>}
        <ul className="mt-6 grid gap-2 sm:grid-cols-2">
          {facts.map((f) => (
            <li key={f.text} className="card flex items-center gap-2.5 px-4 py-3 text-[14px]">
              <f.icon className="size-4 shrink-0" style={{ color: f.ok === false ? "var(--text-3)" : "var(--done)" }} /> {f.text}
            </li>
          ))}
          <li className="card flex items-center gap-2.5 px-4 py-3 text-[14px]">
            <span className="num font-semibold">{a.applications_this_week}</span> applications sent by this student that week
          </li>
        </ul>
        <div className="hairline my-10" />
        <ProofView proof={proof} />
        <details className="card mt-10 p-5 text-[13px] text-muted">
          <summary className="cursor-pointer font-medium text-fg">Verify this page</summary>
          <p className="mt-3">
            This page is signed with Ed25519. Check it at{" "}
            <a href={data.verify_url} className="text-accent underline">
              {data.verify_url}
            </a>
            : it returns the signed payload, the signature and JobPilot’s public key, so you can verify it yourself.
          </p>
          <p className="mt-2 break-all font-mono text-[11.5px]">Public key: {data.public_key}</p>
        </details>
        <footer className="mt-12 flex items-center justify-center gap-2 text-[12.5px] text-subtle">
          <Logo size={18} /> Evidence gathered from public sources by{" "}
          <Link href="/" className="text-accent hover:underline">
            JobPilot
          </Link>
        </footer>
      </main>
    </div>
  );
}

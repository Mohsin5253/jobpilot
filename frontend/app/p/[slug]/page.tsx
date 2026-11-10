import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Logo } from "@/components/logo";
import { ProofView } from "@/components/proof-card";
import type { PublicProof } from "@/lib/types";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

async function load(slug: string): Promise<PublicProof | null> {
  const res = await fetch(`${API_URL}/api/public/proof/${encodeURIComponent(slug)}`, { next: { revalidate: 300 } });
  return res.ok ? res.json() : null;
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const proof = await load((await params).slug);
  return { title: proof ? `${proof.name} · Proof of work` : "Proof of work", robots: { index: false } };
}

export default async function PublicProofPage({ params }: { params: Promise<{ slug: string }> }) {
  const proof = await load((await params).slug);
  if (!proof) notFound();
  return (
    <div className="min-h-dvh">
      <div className="spotlight pointer-events-none absolute inset-x-0 top-0 h-80" />
      <main className="relative mx-auto max-w-4xl px-4 py-14 sm:px-6">
        <div className="eyebrow">Proof of work</div>
        <h1 className="mt-3 font-display text-[52px] leading-[1.02] sm:text-[64px]">{proof.name}</h1>
        {proof.headline && <p className="mt-2 text-[16px] text-muted">{proof.headline}</p>}
        <div className="hairline my-10" />
        <ProofView proof={proof} />
        <footer className="mt-14 flex items-center justify-center gap-2 text-[12.5px] text-subtle">
          <Logo size={18} /> Evidence gathered from public sources by{" "}
          <Link href="/" className="text-accent hover:underline">
            JobPilot
          </Link>
        </footer>
      </main>
    </div>
  );
}

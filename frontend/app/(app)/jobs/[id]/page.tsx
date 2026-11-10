"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { use } from "react";

import { GrowthPanel } from "@/components/growth";
import { MatchDetail } from "@/components/jobs/match-detail";

export default function MatchDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return (
    <div className="space-y-4">
      <Link href="/jobs" className="inline-flex min-h-11 items-center gap-1.5 text-[13px] text-text-2 hover:text-text md:min-h-0">
        <ArrowLeft className="size-3.5" /> Matches
      </Link>
      <MatchDetail id={id} />
      <GrowthPanel matchId={id} />
    </div>
  );
}

"use client";

import { Ledger } from "@/components/growth";
import { PageHeader } from "@/components/ui/misc";

export default function StipendsPage() {
  return (
    <div className="space-y-6">
      <PageHeader eyebrow="Stipend & PPO ledger" title="Stipends, from students" description="Verified reports only. Numbers appear once three students have reported a company." />
      <Ledger />
    </div>
  );
}

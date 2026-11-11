"use client";

import { Suspense } from "react";

import { PlansAndPayments } from "@/components/billing";
import { CampusPlans } from "@/components/marketing/campus-pricing";
import { Card, CardHeader } from "@/components/ui/card";
import { PageHeader, Skeleton } from "@/components/ui/misc";
import { useMe } from "@/lib/queries";

export default function BillingPage() {
  const { data: me } = useMe();
  const pro = me?.plan === "pro";
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Plans & payments"
        title={pro ? "Your plan" : "Get Pro"}
        description={pro ? "Your Pro is active. Invoices and plan details are below." : "Same Pro in every option: a Week Pass for a sprint, Monthly for steady applying, or a Year Pass for the whole placement season."}
      />
      <Suspense fallback={<Skeleton className="h-96" />}>
        <PlansAndPayments />
      </Suspense>
      <Card id="campus">
        <CardHeader title="For colleges" description="Placement-cell plans: TPO, HOD and faculty accounts, a live placement pipeline and AI job matches your staff approve. Flat yearly prices invoiced to the college (GST extra), 30-day refund, 25% off for government colleges; students don't pay." />
        <div className="space-y-3 p-5 pt-3">
          <CampusPlans compact onPick={(plan) => (window.location.href = `/campus-pricing?plan=${plan}#enquire`)} />
          <a href="/campus-pricing" className="inline-block text-[13px] font-medium text-cobalt-text">
            Compare campus plans in full →
          </a>
        </div>
      </Card>
    </div>
  );
}

"use client";

import { Suspense } from "react";

import { PlansAndPayments } from "@/components/billing";
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
    </div>
  );
}

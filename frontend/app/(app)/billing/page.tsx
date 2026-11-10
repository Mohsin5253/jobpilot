"use client";

import { Suspense } from "react";

import { PlansAndPayments } from "@/components/billing";
import { PageHeader, Skeleton } from "@/components/ui/misc";

export default function BillingPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Plans & payments"
        title="Get Pro"
        description="Same Pro in every option: a Week Pass for a sprint, Monthly for steady applying, or a Year Pass for the whole placement season."
      />
      <Suspense fallback={<Skeleton className="h-96" />}>
        <PlansAndPayments />
      </Suspense>
    </div>
  );
}

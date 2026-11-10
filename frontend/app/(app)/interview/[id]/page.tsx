"use client";

import { use } from "react";

import { InterviewRunner } from "@/components/growth";

export default function InterviewPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <InterviewRunner id={id} />;
}

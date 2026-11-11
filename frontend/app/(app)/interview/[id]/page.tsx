"use client";

import { use } from "react";

import { InterviewRoom } from "@/components/interview/interview-room";

export default function InterviewPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <InterviewRoom id={id} />;
}

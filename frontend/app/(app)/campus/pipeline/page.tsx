"use client";

import { AlumniUpload } from "@/components/campus-v2";
import { CampusJobs, PipelineBoard, StudentAudit, useStaffMe } from "@/components/placement-cell";
import { Skeleton } from "@/components/ui/misc";

/** AI match proposals staff approve, then rounds to placed; college-only jobs; the AI's precision. */
export default function PipelinePage() {
  const me = useStaffMe();
  if (me.error) return <p className="text-[13px] text-text-2">The AI pipeline opens once your staff account is linked to this college. Ask your TPO.</p>;
  if (!me.data) return <Skeleton agent="pilot" className="min-h-96" />;
  return (
    <div className="space-y-6">
      <PipelineBoard me={me.data} />
      <CampusJobs me={me.data} />
      <StudentAudit />
      <AlumniUpload />
    </div>
  );
}

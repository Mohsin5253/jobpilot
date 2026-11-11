"use client";

import { useMutation } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { AtsReportView } from "@/components/resume/ats-report";
import { AtsTarget, emptyTarget, targetBody, type Target } from "@/components/resume/ats-target";
import { ResumeBuilder } from "@/components/resume/builder";
import { ResumeDropzone } from "@/components/resume-dropzone";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { PageHeader, Skeleton } from "@/components/ui/misc";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import type { AtsReport } from "@/lib/ats-types";
import { useProfile } from "@/lib/queries";

function ResumeStudio() {
  const params = useSearchParams();
  const { data: profile, isLoading } = useProfile();
  const [target, setTarget] = useState<Target>(() => emptyTarget(params.get("match")));
  const [tab, setTab] = useState(params.get("tab") === "builder" ? "builder" : "check");
  const check = useMutation({ mutationFn: (body: object) => api.post<AtsReport>("/ats/score", body) });
  const ready = target.kind !== "match" || !!target.matchId;
  const run = () => ready && check.mutate(targetBody(target));
  useEffect(() => {
    if (profile?.has_resume) run();
    // Score once the profile loads and whenever the target changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile?.has_resume, JSON.stringify(target.kind === "paste" ? { ...target, description: "" } : target)]);

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Resume"
        title="Resume & ATS"
        description="How applicant tracking systems in your field read your resume: the score, the gaps, what to improve first, and an ATS-friendly builder."
      />
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="check">ATS check</TabsTrigger>
          <TabsTrigger value="builder">Resume builder</TabsTrigger>
        </TabsList>
        <TabsContent value="check" className="mt-4 space-y-4">
          {isLoading ? (
            <Skeleton className="min-h-60" />
          ) : !profile?.has_resume ? (
            <Card className="space-y-3 p-5">
              <p className="text-[14px]">Upload your resume to see its ATS score, or build one from scratch in the Resume builder tab.</p>
              <ResumeDropzone />
            </Card>
          ) : (
            <>
              <Card className="space-y-3 p-5">
                <AtsTarget value={target} onChange={setTarget} />
                {target.kind === "paste" && (
                  <Button variant="primary" onClick={run} loading={check.isPending} disabled={target.description.trim().length < 40}>
                    Score against this job
                  </Button>
                )}
                {profile.resume_filename && <p className="text-[12.5px] text-text-3">Checking {profile.resume_filename}, including how its file parses.</p>}
              </Card>
              {check.error && <p className="text-[13px] text-[var(--error)]">{(check.error as Error).message}</p>}
              {check.isPending && !check.data ? <Skeleton className="min-h-80" /> : check.data && <AtsReportView r={check.data} jobTitle={target.title} jobDescription={target.description} />}
            </>
          )}
        </TabsContent>
        <TabsContent value="builder" className="mt-4">
          {isLoading ? <Skeleton className="min-h-80" /> : <ResumeBuilder initial={profile?.resume} target={target} setTarget={setTarget} />}
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default function ResumePage() {
  return (
    <Suspense>
      <ResumeStudio />
    </Suspense>
  );
}

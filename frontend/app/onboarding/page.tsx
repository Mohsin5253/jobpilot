"use client";

import { ArrowLeft, ArrowRight, Check, Play } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { AgentHero } from "@/components/agents/agent-avatar";
import { MailCard } from "@/components/account-settings";
import { Logo } from "@/components/logo";
import { ResumeDropzone } from "@/components/resume-dropzone";
import { Button, buttonClass } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, Switch } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/misc";
import { TagInput } from "@/components/ui/tag-input";
import { CREW_HERO } from "@/config/agents";
import { useOverview, useProfile, useSaveProfile, useStartRun } from "@/lib/queries";
import { cn } from "@/lib/utils";

const STEPS = ["Resume", "Profile", "Preferences", "Email"] as const;

/** Pilot speaks each step: the flow's one large character, pointing at the step's content. */
function PilotSays({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-4 md:flex-col md:gap-5">
      <div className="shrink-0 md:hidden">
        <AgentHero agent="pilot" size={72} />
      </div>
      <div className="hidden md:block">
        <AgentHero agent="pilot" size={176} />
      </div>
      <div className="relative min-w-0 flex-1 rounded-[var(--radius-card)] border border-border-strong bg-elevated px-4 py-3 md:w-full">
        <span aria-hidden className="absolute top-5 -left-[7px] size-3 rotate-45 border-b border-l border-border-strong bg-elevated md:-top-[7px] md:left-16 md:rotate-[135deg]" />
        <div className="mb-1 text-[13px] font-semibold">Pilot</div>
        <p aria-live="polite" className="text-[14.5px] leading-relaxed">
          {children}
        </p>
      </div>
    </div>
  );
}

function Nav({ back, next, nextLabel = "Continue", disabled, loading }: { back?: () => void; next: () => void; nextLabel?: string; disabled?: boolean; loading?: boolean }) {
  return (
    <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:items-center">
      {back && (
        <Button variant="ghost" className="h-11 md:h-9" onClick={back}>
          <ArrowLeft /> Back
        </Button>
      )}
      <Button variant="primary" className="h-11 sm:ml-auto md:h-9" onClick={next} disabled={disabled} loading={loading}>
        {nextLabel} {!loading && <ArrowRight />}
      </Button>
    </div>
  );
}

export default function OnboardingPage() {
  const router = useRouter();
  const { data: profile, isLoading } = useProfile();
  const { data: overview } = useOverview();
  const save = useSaveProfile();
  const start = useStartRun();
  const [step, setStep] = useState(0);
  const [keywords, setKeywords] = useState<string[]>([]);
  const [locations, setLocations] = useState<string[]>([]);
  const [remote, setRemote] = useState(true);
  const [internships, setInternships] = useState(true);

  // Returning with a resume already parsed starts at "confirm your profile".
  useEffect(() => {
    if (profile?.has_resume) setStep((s) => (s === 0 ? 1 : s));
    if (profile) {
      setKeywords(profile.preferences.keywords);
      setLocations(profile.preferences.locations);
      setRemote(profile.preferences.remote_ok);
      setInternships(profile.preferences.internships_only);
    }
  }, [profile]);

  const online = !!overview && overview.llm_mode !== "offline";
  const r = profile?.resume;
  const done = step >= STEPS.length;

  const savePrefs = () =>
    profile &&
    save.mutate({ preferences: { ...profile.preferences, keywords, locations, remote_ok: remote, internships_only: internships } }, { onSuccess: () => setStep(3) });

  const launch = () => start.mutate(undefined, { onSuccess: () => router.replace("/dashboard") });

  return (
    <div className="min-h-dvh bg-bg">
      <header className="border-b border-border">
        <div className="mx-auto flex h-16 max-w-[1100px] items-center gap-3 px-4 md:px-6">
          <Logo size={26} />
          <span className="text-[16px] font-semibold tracking-[-0.02em]">JobPilot</span>
          <Link href="/dashboard" className="ml-auto inline-flex min-h-11 items-center rounded-[var(--radius-control)] px-3 text-[13.5px] text-text-2 hover:text-text">
            Skip for now
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-[1100px] px-4 py-8 md:px-6 md:py-12">
        {/* Progress */}
        {!done && (
          <ol aria-label="Setup progress" className="mb-8 grid grid-cols-4 gap-2 md:mb-12">
            {STEPS.map((s, i) => (
              <li key={s} aria-current={i === step ? "step" : undefined}>
                <div className={cn("h-1 rounded-full transition-colors duration-[var(--dur-base)]", i <= step ? "bg-cobalt" : "bg-elevated-2")} />
                <div className={cn("mt-2 flex items-center gap-1.5 text-[12.5px]", i <= step ? "text-text" : "text-text-3")}>
                  {i < step && <Check className="size-3.5 text-done" aria-label="Done" />}
                  <span className="num">{i + 1}</span> <span className="hidden sm:inline">{s}</span>
                </div>
              </li>
            ))}
          </ol>
        )}

        {isLoading || !profile ? (
          <Skeleton agent="pilot" className="min-h-80" />
        ) : done ? (
          /* Crew reveal */
          <div className="text-center">
            <div className="dark relative mx-auto max-w-[900px] overflow-hidden rounded-[var(--radius-panel)] border border-border bg-bg">
              <Image src={CREW_HERO.src} alt={CREW_HERO.alt} width={CREW_HERO.width} height={CREW_HERO.height} priority sizes="(min-width: 960px) 900px, 100vw" className="aspect-[16/9] w-full object-cover object-[80%_30%] animate-[fade-in_var(--dur-slow)_var(--ease)]" />
            </div>
            <h1 className="font-display mt-8 text-[clamp(30px,4.4vw,48px)] leading-tight">Your crew is ready.</h1>
            <p className="mx-auto mt-3 max-w-lg text-[15.5px] text-text-2">Ten agents, briefed on your resume and preferences. They’ll find, score and prepare. Nothing goes out until you approve it.</p>
            <div className="mt-7 flex flex-col justify-center gap-2 sm:flex-row">
              <Button variant="primary" size="lg" onClick={launch} loading={start.isPending}>
                {!start.isPending && <Play className="fill-current" />} Send the crew out
              </Button>
              <Link href="/dashboard" className={buttonClass({ variant: "ghost", size: "lg" })}>
                Go to the dashboard
              </Link>
            </div>
          </div>
        ) : (
          <div className="grid gap-8 md:grid-cols-[220px_minmax(0,1fr)] md:gap-12">
            <PilotSays>
              {step === 0 && "Hi, I’m Pilot. Upload your resume once and my crew works from it on every run. Tailor is never allowed to add a skill that isn’t on it."}
              {step === 1 && "Here’s what I read from your resume. If something’s missing, fix it in Settings and I’ll use the corrected version."}
              {step === 2 && "Tell Scout what to look for. Keywords like “machine learning intern”, and the cities you’d work in."}
              {step === 3 &&
                (online
                  ? "Last step: connect your own email so approved applications go from your address, with the tailored resume attached. You can skip this and use Gmail drafts instead."
                  : "Last step: connect your email. I’m in offline mode right now, so the crew will score with embeddings and rules until an LLM key is set.")}
            </PilotSays>

            <div className="min-w-0">
              {step === 0 && (
                <>
                  <h1 className="font-display text-[clamp(24px,3vw,32px)]">Upload your resume</h1>
                  <p className="mt-1 text-[14px] text-text-2">PDF or DOCX. It stays private to your account.</p>
                  <Card className="mt-5 p-2">
                    <ResumeDropzone filename={profile.resume_filename} />
                  </Card>
                  <Nav next={() => setStep(1)} disabled={!profile.has_resume} />
                </>
              )}

              {step === 1 && r && (
                <>
                  <h1 className="font-display text-[clamp(24px,3vw,32px)]">Does this look right?</h1>
                  <Card className="mt-5 divide-y divide-border">
                    <div className="p-5">
                      <div className="text-[16px] font-semibold">{r.name || "Your name"}</div>
                      <div className="text-[13.5px] text-text-2">{[r.email, r.location].filter(Boolean).join(" · ")}</div>
                    </div>
                    <div className="p-5">
                      <div className="eyebrow mb-2">Skills · {r.skills.length}</div>
                      <div className="flex flex-wrap gap-1.5">
                        {r.skills.slice(0, 24).map((s) => (
                          <span key={s} className="rounded-[6px] border border-border bg-elevated px-2 py-0.5 text-[12.5px]">
                            {s}
                          </span>
                        ))}
                        {r.skills.length > 24 && <span className="text-[12.5px] text-text-3">+{r.skills.length - 24} more</span>}
                      </div>
                    </div>
                    <div className="grid gap-5 p-5 sm:grid-cols-2">
                      <div>
                        <div className="eyebrow mb-2">Experience · {r.experience.length}</div>
                        <ul className="space-y-1.5 text-[13.5px]">
                          {r.experience.map((e, i) => (
                            <li key={i}>
                              <span className="font-medium">{e.title}</span>
                              {e.organization && <span className="text-text-2"> · {e.organization}</span>}
                            </li>
                          ))}
                          {!r.experience.length && <li className="text-text-3">None found</li>}
                        </ul>
                      </div>
                      <div>
                        <div className="eyebrow mb-2">Projects · {r.projects.length}</div>
                        <ul className="space-y-1.5 text-[13.5px]">
                          {r.projects.map((p, i) => (
                            <li key={i} className="font-medium">
                              {p.name}
                            </li>
                          ))}
                          {!r.projects.length && <li className="text-text-3">None found</li>}
                        </ul>
                      </div>
                    </div>
                  </Card>
                  <p className="mt-3 text-[13px] text-text-3">
                    Something wrong?{" "}
                    <Link href="/settings#resume" className="font-medium text-cobalt-text hover:underline">
                      Edit it in Settings
                    </Link>{" "}
                    or upload a new version.
                  </p>
                  <Nav back={() => setStep(0)} next={() => setStep(2)} nextLabel="Looks right" />
                </>
              )}

              {step === 2 && (
                <>
                  <h1 className="font-display text-[clamp(24px,3vw,32px)]">What should Scout look for?</h1>
                  <Card className="mt-5 space-y-5 p-5">
                    <Field label="Role keywords" hint="Press Enter or comma after each one.">
                      <TagInput value={keywords} onChange={setKeywords} placeholder="e.g. machine learning intern" />
                    </Field>
                    <Field label="Locations" hint="Add “Remote” to include remote roles.">
                      <TagInput value={locations} onChange={setLocations} placeholder="e.g. Bengaluru" />
                    </Field>
                    <label className="flex min-h-11 items-center justify-between gap-3 text-[14px]">
                      Include remote roles
                      <Switch checked={remote} onChange={setRemote} label="Include remote roles" />
                    </label>
                    <label className="flex min-h-11 items-center justify-between gap-3 text-[14px]">
                      Internships and fresher roles only
                      <Switch checked={internships} onChange={setInternships} label="Internships and fresher roles only" />
                    </label>
                  </Card>
                  <p className="mt-3 text-[13px] text-text-3">More options, like company boards and run times, are in Settings.</p>
                  <Nav back={() => setStep(1)} next={savePrefs} nextLabel="Save and continue" disabled={!keywords.length} loading={save.isPending} />
                </>
              )}

              {step === 3 && (
                <>
                  <h1 className="font-display text-[clamp(24px,3vw,32px)]">Connect your email</h1>
                  <p className="mt-1 text-[14px] text-text-2">Optional. Without it, approving a draft opens it in Gmail or your mail app for you to send.</p>
                  <div className="mt-5">
                    <MailCard />
                  </div>
                  <Nav back={() => setStep(2)} next={() => setStep(4)} nextLabel="Finish" />
                </>
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

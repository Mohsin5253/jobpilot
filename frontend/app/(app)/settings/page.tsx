"use client";

import { Building2, CalendarClock, FileText, GraduationCap, Search, Sparkles, Telescope } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { ConsentCard, DataCard, QuotaCard, RightsCard, ExtensionCard, MailCard, PlanCard, SecurityCard, WhatsAppCard } from "@/components/account-settings";
import { ResumeDropzone } from "@/components/resume-dropzone";
import { RunButton } from "@/components/shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Field, Input, Switch } from "@/components/ui/input";
import { PageHeader, Skeleton } from "@/components/ui/misc";
import { TagInput } from "@/components/ui/tag-input";
import { isActive, useConfig, useOverview, useProfile, useResearch, useResearchNow, useSaveProfile } from "@/lib/queries";
import { ago } from "@/lib/utils";
import type { Preferences } from "@/lib/types";

function ResumeCard() {
  const { data: p } = useProfile();
  if (!p) return <Skeleton className="h-64" />;
  const r = p.resume;
  return (
    <Card>
      <CardHeader icon={<FileText className="size-4" />} title="Resume" description="Parsed once, used by every agent. The Tailor can only rephrase what’s here." />
      <div className="space-y-5 p-5">
        <ResumeDropzone filename={p.resume_filename} className="py-7" />
        {p.has_resume && (
          <>
            <div>
              <div className="text-[15px] font-semibold">{r.name}</div>
              <div className="text-[13px] text-muted">{[r.email, r.location].filter(Boolean).join(" · ")}</div>
            </div>
            <div>
              <div className="mb-2 text-[12px] font-medium tracking-wide text-subtle uppercase">Skills · {r.skills.length}</div>
              <div className="flex flex-wrap gap-1.5">
                {r.skills.map((s) => (
                  <Badge key={s} tone="accent">
                    {s}
                  </Badge>
                ))}
              </div>
            </div>
            {[...r.experience.map((e) => ({ k: `e-${e.title}-${e.organization}`, h: [e.title, e.organization].filter(Boolean).join(" · "), b: e.bullets, icon: Building2 })),
              ...r.projects.map((pr) => ({ k: `p-${pr.name}`, h: pr.name, b: pr.bullets, icon: Sparkles })),
            ].map(({ k, h, b, icon: Icon }) => (
              <div key={k} className="rounded-[var(--radius-card)] border border-border bg-surface-2/40 p-4">
                <div className="mb-2 flex items-center gap-2 text-[13.5px] font-semibold">
                  <Icon className="size-3.5 text-subtle" /> {h}
                </div>
                <ul className="space-y-1.5">
                  {b.map((x, i) => (
                    <li key={i} className="flex gap-2 text-[13px] leading-relaxed text-muted">
                      <span className="mt-2 size-1 shrink-0 rounded-full bg-border-strong" />
                      {x}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
            {!!r.additional?.length && (
              <div className="rounded-[var(--radius-card)] border border-success/25 bg-success/5 p-4">
                <div className="mb-2 flex items-center gap-2 text-[13.5px] font-semibold">
                  <Sparkles className="size-3.5 text-success" /> Confirmed in Skill check
                </div>
                <ul className="space-y-1.5">
                  {r.additional.map((a, i) => (
                    <li key={i} className="text-[13px] leading-relaxed text-muted">
                      <span className="font-medium text-fg">{a.skill}:</span> {a.details}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {r.education.map((e, i) => (
              <div key={i} className="flex items-center gap-2 text-[13px] text-muted">
                <GraduationCap className="size-4 text-subtle" /> {[e.degree, e.school, e.end].filter(Boolean).join(" · ")}
              </div>
            ))}
          </>
        )}
      </div>
    </Card>
  );
}

function ResearchCard({ prefs, set }: { prefs: Preferences; set: <K extends keyof Preferences>(k: K, v: Preferences[K]) => void }) {
  const { data: research } = useResearch();
  const { data: config } = useConfig();
  const runNow = useResearchNow();
  const { data: overview } = useOverview();
  const busy = isActive(overview?.last_run);
  return (
    <Card id="research">
      <CardHeader
        icon={<Telescope className="size-4" />}
        title="Research agent"
        description="Keeps discovering companies that hire for your profile and re-runs the agents, so new openings reach you fast"
        action={
          <Button size="sm" variant="primary" onClick={() => runNow.mutate()} loading={runNow.isPending} disabled={busy || !prefs.research_enabled}>
            Research now
          </Button>
        }
      />
      <div className="space-y-4 p-5">
        <div className="flex items-center justify-between rounded-[var(--radius-card)] border border-border px-4 py-3">
          <div>
            <div className="text-[13.5px] font-medium">Continuous research</div>
            <div className="text-[12px] text-subtle">
              {research?.last_research_at ? `Last search ${ago(research.last_research_at)} · ${research.checked} company boards checked` : "Hasn’t run yet"}
            </div>
          </div>
          <Switch checked={prefs.research_enabled} onChange={(v) => set("research_enabled", v)} label="Continuous research" />
        </div>
        <Field
          label={`Check job sources every ${prefs.refresh_minutes} minute${prefs.refresh_minutes === 1 ? "" : "s"}`}
          hint="Job sources are checked for everyone at once (company career boards every ~2 min); when a new posting is close to your resume your agents wake up and the fit is pushed to your dashboard the moment it's scored. Your plan sets the shortest gap."
        >
          <input type="range" min={1} max={60} step={1} value={prefs.refresh_minutes} onChange={(e) => set("refresh_minutes", Number(e.target.value))} className="w-full accent-[var(--accent)]" disabled={!prefs.research_enabled} />
        </Field>
        <div className="flex items-center justify-between rounded-[var(--radius-card)] border border-border px-4 py-3">
          <div>
            <div className="text-[13.5px] font-medium">LinkedIn · Indeed · Glassdoor · Naukri · Wellfound</div>
            <div className="text-[12px] text-subtle">
              {config?.jsearch_enabled
                ? "Connected through JSearch (Google for Jobs index) — every listing keeps its original apply links"
                : "Add a free JSearch key to include these boards: run backend/scripts/set_jsearch.py"}
            </div>
          </div>
          <span className={`size-2 rounded-full ${config?.jsearch_enabled ? "bg-success" : "bg-border-strong"}`} />
        </div>
        <div className="flex items-center justify-between rounded-[var(--radius-card)] border border-border px-4 py-3">
          <div>
            <div className="text-[13.5px] font-medium">
              <a href="https://www.adzuna.in" target="_blank" rel="noreferrer" className="hover:underline">Jobs by Adzuna</a> · Indian job boards
            </div>
            <div className="text-[12px] text-subtle">
              {config?.adzuna_enabled
                ? "Connected — one search per check, rotated across the roles your resume fits"
                : "Add a free Adzuna developer key to include it: run backend/scripts/set_adzuna.py"}
            </div>
          </div>
          <span className={`size-2 rounded-full ${config?.adzuna_enabled ? "bg-success" : "bg-border-strong"}`} />
        </div>
        <Field label={`Re-check for new jobs every ${prefs.research_interval_hours} hours`} hint="Each check runs the whole team: Researcher, Scout, Matcher, Interviewer, Tailor, Outreach. A new company search happens at most once a day.">
          <input type="range" min={2} max={24} step={1} value={prefs.research_interval_hours} onChange={(e) => set("research_interval_hours", Number(e.target.value))} className="w-full accent-[var(--accent)]" disabled={!prefs.research_enabled} />
        </Field>
        <div className="flex items-center justify-between rounded-[var(--radius-card)] border border-border px-4 py-3">
          <div>
            <div className="text-[13.5px] font-medium">Email me new matches</div>
            <div className="text-[12px] text-subtle">
              {config?.system_mail_enabled ? "A short summary to your account email when new fits arrive" : "Email alerts aren’t set up on this server yet. In-app and desktop alerts work without them."}
            </div>
          </div>
          <Switch checked={prefs.email_alerts && !!config?.system_mail_enabled} onChange={(v) => config?.system_mail_enabled && set("email_alerts", v)} label="Email alerts" />
        </div>
        {!!research?.added.length && (
          <div>
            <div className="mb-2 text-[12px] font-medium tracking-wide text-subtle uppercase">Companies the Researcher added</div>
            <div className="flex flex-wrap gap-1.5">
              {research.added.slice(0, 30).map((a) => (
                <span key={`${a.provider}:${a.token}`} title={`${a.provider} · ${a.roles} open roles · ${a.fits} fit your filters`} className="inline-flex items-center gap-1 rounded-md border border-border bg-surface-2/60 px-2 py-0.5 text-[12.5px]">
                  {a.company}
                  {!!a.fits && <span className="font-mono text-[11px] text-success">{a.fits}</span>}
                </span>
              ))}
            </div>
            <p className="mt-1.5 text-[11.5px] text-subtle">Green numbers = open roles that fit your filters right now. Remove any from the boards lists below.</p>
          </div>
        )}
      </div>
    </Card>
  );
}

function PreferencesCard() {
  const { data: p } = useProfile();
  const save = useSaveProfile();
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  useEffect(() => {
    if (p) setPrefs(p.preferences);
  }, [p]);
  if (!prefs || !p) return <Skeleton className="h-[520px]" />;

  const set = <K extends keyof Preferences>(k: K, v: Preferences[K]) => setPrefs({ ...prefs, [k]: v });
  const dirty = JSON.stringify(prefs) !== JSON.stringify(p.preferences);
  const localHour = (() => {
    const d = new Date();
    d.setUTCHours(prefs.daily_run_hour_utc, 0, 0, 0);
    return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  })();

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader icon={<Search className="size-4" />} title="What the Scout looks for" />
        <div className="space-y-4 p-5">
          <div>
            <div className="mb-1.5 text-[13px] font-medium">Role types</div>
            <div className="grid grid-cols-2 gap-2">
              {([
                ["technical", "Technical", "Engineering, data, ML, QA, IT, research"],
                ["non_technical", "Non-technical", "Marketing, HR, sales, finance, ops, design, content"],
              ] as const).map(([value, label, hint]) => {
                const on = prefs.tracks.includes(value);
                return (
                  <button
                    key={value}
                    type="button"
                    onClick={() => {
                      const next = on ? prefs.tracks.filter((t) => t !== value) : [...prefs.tracks, value];
                      if (next.length) set("tracks", next);
                    }}
                    className={`rounded-[var(--radius-card)] border px-3.5 py-3 text-left transition-colors ${on ? "border-accent bg-accent-soft" : "border-border hover:border-border-strong"}`}
                  >
                    <div className="text-[13.5px] font-medium">{label}</div>
                    <div className="text-[12px] text-subtle">{hint}</div>
                  </button>
                );
              })}
            </div>
          </div>
          <Field label="Focus keywords (optional)" hint="Leave empty to see every early-career role. If set, a posting must mention one of them.">
            <TagInput value={prefs.keywords} onChange={(v) => set("keywords", v)} placeholder="machine learning" />
          </Field>
          <Field label="Locations" hint="Used for Adzuna searches. Add “Remote” to include remote roles.">
            <TagInput value={prefs.locations} onChange={(v) => set("locations", v)} placeholder="Bengaluru" />
          </Field>
          <div className="flex items-center justify-between rounded-[var(--radius-card)] border border-border px-4 py-3">
            <div>
              <div className="text-[13.5px] font-medium">Internships & entry-level only</div>
              <div className="text-[12px] text-subtle">Interns, trainees, graduate / new-grad and junior roles; skips senior ones</div>
            </div>
            <Switch checked={prefs.internships_only} onChange={(v) => set("internships_only", v)} label="Internships only" />
          </div>
          <Field label={`Freshness · last ${prefs.max_age_days} days`} hint="Skip postings older than this. Jobs a source stops listing are hidden as closed.">
            <input type="range" min={7} max={90} step={1} value={prefs.max_age_days} onChange={(e) => set("max_age_days", Number(e.target.value))} className="w-full accent-[var(--accent)]" />
          </Field>
          <Field label={`Minimum fit score · ${prefs.min_score}`} hint="Jobs at or above this get a tailored resume, an application draft and a referral request.">
            <input type="range" min={30} max={90} step={5} value={prefs.min_score} onChange={(e) => set("min_score", Number(e.target.value))} className="w-full accent-[var(--accent)]" />
          </Field>
          <Field
            label={`Quality budget · ${prefs.weekly_application_cap} applications a week`}
            hint="Fewer, better applications get more interviews. Only your strongest fits are prepared, up to this many a week."
          >
            <input type="range" min={3} max={30} step={1} value={prefs.weekly_application_cap} onChange={(e) => set("weekly_application_cap", Number(e.target.value))} className="w-full accent-[var(--accent)]" />
          </Field>
        </div>
      </Card>

      <Card>
        <CardHeader icon={<Building2 className="size-4" />} title="Where the Scout looks" description="Real company career boards (Greenhouse, Lever, Ashby) and public job feeds" />
        <div className="space-y-4 p-5">
          <Field label="Greenhouse boards" hint={<>boards.greenhouse.io/<b>token</b> → e.g. stripe, databricks</>}>
            <TagInput value={prefs.greenhouse_boards} onChange={(v) => set("greenhouse_boards", v)} placeholder="board token" />
          </Field>
          <Field label="Lever boards" hint={<>jobs.lever.co/<b>company</b></>}>
            <TagInput value={prefs.lever_boards} onChange={(v) => set("lever_boards", v)} placeholder="company" />
          </Field>
          <Field label="Ashby boards" hint={<>jobs.ashbyhq.com/<b>company</b></>}>
            <TagInput value={prefs.ashby_boards} onChange={(v) => set("ashby_boards", v)} placeholder="company" />
          </Field>
          <div className="flex items-center justify-between rounded-[var(--radius-card)] border border-border px-4 py-3">
            <div>
              <div className="text-[13.5px] font-medium">Public job feeds</div>
              <div className="text-[12px] text-subtle">The Muse, Remotive and Jobicy — no key needed, credited with links back</div>
            </div>
            <Switch checked={prefs.public_job_feeds} onChange={(v) => set("public_job_feeds", v)} label="Public job feeds" />
          </div>
          <Field label="Adzuna country" hint="Two-letter code (in, gb, us…). Needs ADZUNA_APP_ID / KEY on the server.">
            <Input value={prefs.adzuna_country} maxLength={2} onChange={(e) => set("adzuna_country", e.target.value.toLowerCase())} className="w-24" />
          </Field>
        </div>
      </Card>

      <ResearchCard prefs={prefs} set={set} />

      <Card>
        <CardHeader icon={<CalendarClock className="size-4" />} title="Daily run" />
        <div className="space-y-4 p-5">
          <div className="flex items-center justify-between rounded-[var(--radius-card)] border border-border px-4 py-3">
            <div>
              <div className="text-[13.5px] font-medium">Run every morning</div>
              <div className="text-[12px] text-subtle">Agents run at {localHour} your time; drafts wait for your approval</div>
            </div>
            <Switch checked={prefs.daily_runs_enabled} onChange={(v) => set("daily_runs_enabled", v)} label="Daily runs" />
          </div>
          <Field label="Hour (UTC)">
            <Input type="number" min={0} max={23} value={prefs.daily_run_hour_utc} onChange={(e) => set("daily_run_hour_utc", Math.max(0, Math.min(23, Number(e.target.value))))} className="w-24" />
          </Field>
        </div>
      </Card>

      <div className="sticky bottom-4 flex justify-end">
        <Button variant="primary" size="lg" disabled={!dirty} loading={save.isPending} onClick={() => save.mutate({ preferences: prefs })} className="shadow-xl">
          Save preferences
        </Button>
      </div>
    </div>
  );
}

function Onboarding() {
  const params = useSearchParams();
  const { data: p } = useProfile();
  if (!params.get("onboarding")) return null;
  return (
    <div className="mb-6 flex flex-wrap items-center justify-between gap-4 rounded-[var(--radius-card)] border border-[color-mix(in_oklab,var(--cobalt)_30%,transparent)] bg-cobalt-subtle p-5">
      <div>
        <div className="text-[15px] font-semibold">Welcome aboard</div>
        <div className="text-[13px] text-text-2">{p?.has_resume ? "Resume parsed. Check the keywords, then send the agents out." : "Upload your resume, adjust what the Scout looks for, then run the agents."}</div>
      </div>
      {p?.has_resume ? <RunButton /> : <Link href="#resume" className="text-[13px] font-medium text-accent">Upload resume ↓</Link>}
    </div>
  );
}

export default function SettingsPage() {
  return (
    <div>
      <PageHeader title="Settings" description="Your resume, what the crew searches for, and your account." />
      <Suspense>
        <Onboarding />
      </Suspense>
      <div className="grid gap-6 xl:grid-cols-2 [&>*]:min-w-0" id="resume">
        <div className="space-y-6">
          <ResumeCard />
          <MailCard />
          <QuotaCard />
          <WhatsAppCard />
          <ExtensionCard />
          <PlanCard />
          <ConsentCard />
          <RightsCard />
          <SecurityCard />
          <DataCard />
        </div>
        <PreferencesCard />
      </div>
    </div>
  );
}

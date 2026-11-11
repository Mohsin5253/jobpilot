export type Stage = "found" | "shortlisted" | "applied" | "interview" | "offer" | "rejected" | "archived";

export interface User {
  id: string;
  email: string;
  name: string;
  created_at: string;
  plan: "free" | "pro";
  is_demo: boolean;
  is_admin: boolean;
  expires_at: string | null;
  adult_confirmed_at?: string | null;
  language?: "en" | "hi" | "mr";
}

export interface Usage {
  plan: "free" | "pro";
  limits: { drafts_per_day: number; manual_runs_per_day: number; min_refresh_minutes: number; llm_usd_per_day: number };
  drafts: number;
  manual_runs: number;
  llm_usd: number;
  drafts_left: number;
  runs_left: number;
  ai_budget_left: number;
  week_applications: number;
  weekly_cap: number;
  week_left: number;
  pro_requested: boolean;
}

export interface MailAccount {
  connected: boolean;
  provider?: "smtp" | "gmail_oauth" | null;
  google_available?: boolean;
  host: string | null;
  port: number | null;
  from_email: string | null;
  from_name: string | null;
  verified_at: string | null;
}

export interface AdminMetrics {
  generated_at: string;
  users: { total: number; new_7d: number; active_1d: number; active_7d: number; pro: number; demo_sessions_7d: number };
  jobs: { open: number; new_24h: number; matches_24h: number; applications_7d: number; drafts_24h: number; interview_rate?: number | null; applications_total?: number };
  queue: Record<string, number>;
  runs_24h: Record<string, number>;
  sources: { source: string; targets: number; wanted: number; failing: number; overdue: number; last_fetch: string | null }[];
  llm: { usd_24h: number; by_agent: Record<string, number>; usd_per_active_user: number };
  pro_requests: { email: string; name: string; requested_at: string }[];
}

export interface Experience { title: string; organization: string; location?: string; start: string; end: string; bullets: string[]; tech?: string[] }
export interface SkillGroup { name: string; items: string[] }
export interface Project { name: string; tech: string[]; bullets: string[] }
export interface Education { school: string; degree: string; start: string; end: string; details: string }

export interface AdditionalSkill { skill: string; details: string }

export interface Resume {
  name: string;
  email: string;
  phone: string;
  location: string;
  links: string[];
  summary: string;
  skills: string[];
  skill_groups?: SkillGroup[];
  experience: Experience[];
  projects: Project[];
  education: Education[];
  certifications?: string[];
  additional: AdditionalSkill[];
}

export type Track = "technical" | "non_technical";

export interface Preferences {
  keywords: string[];
  locations: string[];
  tracks: Track[];
  internships_only: boolean;
  remote_ok: boolean;
  max_age_days: number;
  min_score: number;
  greenhouse_boards: string[];
  lever_boards: string[];
  ashby_boards: string[];
  career_pages?: string[];
  public_job_feeds: boolean;
  adzuna_country: string;
  daily_run_hour_utc: number;
  daily_runs_enabled: boolean;
  research_enabled: boolean;
  research_interval_hours: number;
  refresh_minutes: number;
  email_alerts: boolean;
  max_jobs_per_source: number;
  weekly_application_cap: number;
}

export interface Profile {
  resume_filename: string | null;
  resume: Resume;
  preferences: Preferences;
  has_resume: boolean;
  updated_at: string | null;
}

export interface Job {
  id: string;
  source: string;
  company: string;
  title: string;
  location: string;
  remote: boolean;
  url: string;
  description: string;
  salary_min: number | null;
  salary_max: number | null;
  recruiter_email: string | null;
  skills: string[];
  track: Track;
  posted_at: string | null;
  last_seen_at: string;
  publisher: string | null;
  apply_links: { publisher: string | null; url: string; direct: boolean }[];
  link_status: "ok" | "unverified" | "dead" | null;
  verified_at: string | null;
  ghost_risk: "low" | "medium" | "high";
  ghost_reasons: string[];
  /** The Verifier's verdict; null until it has checked this job. */
  legit_status: "verified" | "caution" | "suspicious" | null;
  legit_reasons: string[];
}

export interface Match {
  id: string;
  job: Job;
  score: number;
  semantic_score: number;
  skill_score: number;
  llm_score: number | null;
  strengths: string[];
  gaps: string[];
  explanation: string;
  stage: Stage;
  stage_changed_at: string;
  applied_at: string | null;
  follow_up_at: string | null;
  notes: string;
  user_rating: number | null;
  created_at: string;
  outcome: Outcome;
  outcome_at: string | null;
  rejection_reason: string;
  resume_variant: "A" | "B";
  ppo_status: "none" | "eligible" | "offered" | "converted";
  has_tailored: boolean;
  pending_draft: boolean;
  approved_draft: boolean;
  sent_draft: boolean;
  proof_views?: number;
  proof_last_viewed_at?: string | null;
}

export type Outcome = "none" | "no_reply" | "replied" | "interview" | "offer" | "rejected";

export interface SourceRef { id: string; kind: "resume" | "proof"; label: string }
export interface TailoredBullet {
  source_id: string;
  original: string;
  rewritten: string;
  keywords: string[];
  reverted: boolean;
  declined?: boolean;
  source_refs?: SourceRef[];
  revert_reason?: string;
}
export interface QuotaState { cap: number; used: number; remaining: number; max: number; resets_at: string }

export interface Contact {
  id: string;
  domain: string;
  email: string;
  kind: "person" | "generic";
  first_name: string;
  last_name: string;
  position: string;
  seniority: string;
  department: string;
  source: "posting" | "website" | "hunter";
  confidence: number;
  verification: string;
  sources: { uri: string; last_seen_on: string | null }[];
  linkedin: string | null;
}

export interface ContactsOut { domain: string | null; hunter_enabled: boolean; contacts: Contact[] }

export interface Draft {
  id: string;
  match_id: string;
  kind: "application" | "referral";
  run_id: string | null;
  subject: string;
  email_body: string;
  linkedin_note: string;
  to_email: string | null;
  contact_id: string | null;
  contact: Contact | null;
  cc_email: string | null;
  status: "pending" | "approved" | "rejected" | "sent";
  decided_at: string | null;
  sent_at: string | null;
  created_at: string;
}

export interface DraftWithJob extends Draft {
  company: string;
  title: string;
  score: number;
  job_url: string;
  job_source: string;
  recruiter_email: string | null;
  legit_status?: "verified" | "caution" | "suspicious" | null;
  legit_reasons?: string[];
  ghost_score?: number | null;
  send_worthiness?: number | null;
  worthiness_parts?: Record<string, number>;
}

export interface MatchDetail extends Match {
  tailored: {
    bullets: TailoredBullet[];
    guard_report: { passed: boolean; checked: number; violations: Record<string, unknown>[]; note?: string };
    model: string;
    created_at: string;
  } | null;
  drafts: Draft[];
}

export interface RunStep { agent: string; status: string; started_at?: string | null; ended_at?: string | null; detail: string }

export type RunStatus = "queued" | "running" | "awaiting_approval" | "resume_queued" | "completed" | "failed";

export interface Run {
  id: string;
  trigger: string;
  status: RunStatus;
  current_step: string | null;
  steps: RunStep[];
  stats: Record<string, number>;
  error: string | null;
  cost_usd: number;
  input_tokens: number;
  output_tokens: number;
  llm_calls: number;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

export interface LLMCall {
  agent: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  latency_ms: number;
  attempts: number;
  success: boolean;
  error: string | null;
  created_at: string;
}

export interface RunDetail extends Run { calls: LLMCall[] }

export interface Overview {
  stage_counts: Record<Stage, number>;
  total_matches: number;
  strong_matches: number;
  avg_score: number;
  pending_approvals: number;
  open_questions: number;
  unread_notifications: number;
  due_reminders: number;
  response_rate: number;
  cost_30d: number;
  runs_30d: number;
  avg_run_latency_ms: number;
  agent_costs: { agent: string; calls: number; cost_usd: number; avg_latency_ms: number; input_tokens: number; output_tokens: number }[];
  daily: { day: string; found: number; applied: number; cost_usd: number }[];
  last_run: Run | null;
  llm_mode: "groq" | "anthropic" | "offline";
  llm_models: string[];
}

export interface Reminder { id: string; match_id: string; kind: string; message: string; due_at: string; company: string; title: string }

export interface SkillQuestion {
  id: string;
  skill: string;
  question: string;
  status: "open" | "yes" | "no" | "dismissed";
  answer: string;
  unlocks: number;
  jobs: string[];
  created_at: string;
}

export interface AnswersResult { answered: number; skills_added: string[]; rematch_run_id: string | null; rechecking_jobs: number }

export interface AppNotification {
  id: string;
  kind: "new_match" | "research" | "skills" | string;
  title: string;
  body: string;
  match_id: string | null;
  read_at: string | null;
  created_at: string;
}

export interface ResearchState {
  last_research_at: string | null;
  checked: number;
  added: { provider: string; token: string; company: string; roles: number; fits: number; local: number; at: string }[];
  next_run_at: string | null;
}

export interface AppConfig { smtp_enabled: boolean; smtp_from: string | null; system_mail_enabled: boolean; hunter_enabled: boolean; jsearch_enabled: boolean; adzuna_enabled: boolean; llm: string }

// ---------- v2: proof pack, insights, campus, consent, WhatsApp, extension ----------

export interface GithubEvidence {
  username: string;
  url: string;
  name: string;
  public_repos: number;
  followers: number;
  since: string;
  active_repos_90d: number;
  stars: number;
  languages: Record<string, number>;
  top_repos: { name: string; url: string; description: string; language: string; stars: number; topics: string[]; pushed_at: string }[];
  verified: boolean;
  verified_at: string | null;
  fetched_at: string;
}

export interface CodeforcesEvidence { handle: string; url: string; rating: number | null; max_rating: number | null; rank: string; max_rank: string }

export interface EvidenceItem { id: string; kind: string; title: string; url: string; live: boolean | null; self_reported: boolean }

export interface Evidence {
  github: GithubEvidence | null;
  codeforces: CodeforcesEvidence | null;
  items: EvidenceItem[];
  verify_code: string | null;
  skills: string[];
  public: boolean;
  slug: string | null;
}

export interface PublicProof {
  name: string;
  headline: string;
  github: (Omit<GithubEvidence, "name" | "followers" | "verified_at" | "fetched_at">) | null;
  codeforces: CodeforcesEvidence | null;
  items: EvidenceItem[];
  skills: string[];
}

export interface InsightGroup { key: string; applied: number; replies: number; interviews: number; interview_rate: number | null; reply_rate: number | null; enough_data: boolean }

export interface Insights {
  applied: number;
  interview_rate: number | null;
  reply_rate: number | null;
  funnel: { applied: number; replied: number; interview: number; offer: number; rejected: number; no_reply: number; awaiting: number };
  by_variant: InsightGroup[];
  by_band: InsightGroup[];
  by_source: InsightGroup[];
  by_track: InsightGroup[];
  rejection_gaps: { skill: string; count: number; share: number | null }[];
  reasons: { reason: string; count: number }[];
  needs_outcome: { match_id: string; company: string; title: string; applied_at: string }[];
  reason_options: string[];
  min_sample: number;
}

export interface Academics { college: string; branch: string; grad_year: number | null; cgpa: number | null; backlogs: number | null }

export interface DriveRound { name: string; type: "aptitude" | "coding" | "technical" | "group_discussion" | "hr"; date: string | null }

export interface Drive {
  id: string;
  company: string;
  role: string;
  kind: "internship" | "full_time";
  compensation: string;
  eligibility: { min_cgpa?: number | null; branches?: string[]; max_backlogs?: number | null; grad_years?: number[] };
  register_by: string | null;
  rounds: DriveRound[];
  notes: string;
  posted_by_college: boolean;
  editable: boolean;
  eligible: boolean | null;
  eligibility_notes: string[];
  status: "interested" | "registered" | "in_rounds" | "selected" | "rejected" | "skipped";
  round_index: number;
  upcoming: boolean;
  prep: { round: string; type: string; checklist: string[] }[];
  eligible_students?: number;
  statuses?: Record<string, number>;
}

export interface Campus {
  academics: Partial<Academics>;
  college: { name: string; role: "student" | "officer"; sharing: boolean } | null;
  drives: Drive[];
  timeline: { at: string; kind: "deadline" | "round" | "off_campus"; title: string; drive_id?: string; match_id?: string; outcome?: Outcome }[];
  ppo: { match_id: string; company: string; title: string; ppo_status: Match["ppo_status"] }[];
  summary: { eligible_upcoming: number; in_rounds: number; selected: number; off_campus_applied: number };
}

export interface CollegeDashboard {
  college: { name: string; invite_code: string };
  students: number;
  sharing: number;
  active_7d: number;
  cohort: Insights | null;
  offers: number;
  ppo_converted: number;
  top_gaps: Insights["rejection_gaps"];
  drives: Drive[];
  per_student: { name: string; email: string; branch: string; cgpa: number | null; applications: number; interviews: number; offers: number; ppo: number; last_active: string | null }[];
}

export interface ConsentNotice { data: string; why: string; retention: string; withdraw: string }
export interface ConsentState {
  version: string;
  purposes: { purpose: string; description: string; granted: boolean; granted_at: string | null; required: boolean; notice_version?: string | null; method?: string | null; notice?: ConsentNotice }[];
}
export interface RightsRequest { id: string; kind: string; details: string; status: "open" | "resolved"; response: string; created_at: string; due_at: string; resolved_at: string | null; contact_email?: string; overdue?: boolean }
export interface RightsState { self_service: Record<string, string>; sla_days: number; requests: RightsRequest[] }

export interface WhatsAppState { available: boolean; number: string | null; hour: number; enabled: boolean; last_sent_at: string | null }

export interface ExtensionToken { id: string; name: string; prefix: string; created_at: string; last_used_at: string | null }

export interface MyProofLink { id: string; url: string; company: string; role: string; approved_at: string; views: number; last_viewed_at: string | null; revoked_at: string | null }

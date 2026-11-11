import type { Resume } from "@/lib/types";

export type CheckStatus = "pass" | "warn" | "fail";

export interface AtsCheck {
  id: string;
  category: "format" | "sections";
  label: string;
  status: CheckStatus;
  detail: string;
  fix: string;
  weight: number;
}

export interface AtsKeyword {
  term: string;
  weight: number;
  importance: "required" | "preferred" | "core" | "nice";
  soft: boolean;
  in_context?: boolean;
  via?: string;
}

export interface AtsReport {
  score: number;
  grade: "Excellent" | "Good" | "Fair" | "Needs work";
  industry: string;
  industry_name: string;
  track?: { key: string; label: string } | null;
  detected_industry: string;
  mode: "job" | "industry";
  breakdown: { key: string; label: string; score: number; weight: number; points: number }[];
  keywords: { coverage: number; matched: AtsKeyword[]; missing: AtsKeyword[]; listed_only: string[] };
  checks: AtsCheck[];
  weak_bullets: { id: string; text: string; issues: string[]; suggestion: string }[];
  stats: { bullets: number; action_pct: number; quantified_pct: number; weak: number; words: number; skills: number };
  improvements: { area: string; title: string; detail: string; gain: number }[];
  gaps: string[];
  job?: { match_id: string; title: string };
}

export interface AtsCompare {
  industry: string;
  industry_name: string;
  original: AtsReport;
  tailored: AtsReport;
  delta: number;
  keywords_gained: string[];
  keywords_now_in_context: string[];
  keywords_still_missing: string[];
  tailored_ready: boolean;
  job: { match_id: string; title: string; company: string };
  bullets: { source_id: string; original: string; rewritten: string; changed: boolean; reverted: boolean; revert_reason: string; declined: boolean; keywords: string[]; sources: string[] }[];
  skills: { original: string[]; tailored_first: string[]; tailored_rest: string[] };
  sections: { original: string[]; tailored: string[] };
}

export interface BulletRewrite {
  issues: string[];
  tip: string;
  options: { text: string; issues: string[] }[];
  rejected: number;
  ai: boolean;
}

export type ScoreRequest = { resume?: Resume; industry?: string | null; match_id?: string | null; job_title?: string; job_description?: string };

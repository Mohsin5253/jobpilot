import type { AgentKey } from "@/config/agents";

export type InterviewerKey = "female" | "male";

export interface Interviewer {
  key: InterviewerKey;
  name: string;
  role: string;
  agent: AgentKey; // whose portrait (and depth map) plays the interviewer
  mouth: { x: number; y: number; w: number }; // lips in texture UV (y up), measured on the idle render
  voiceHints: string[];
  pitch: number;
}

export const INTERVIEWERS: Record<InterviewerKey, Interviewer> = {
  female: {
    key: "female",
    name: "Ananya",
    role: "Senior recruiter",
    agent: "interviewer",
    mouth: { x: 0.482, y: 0.563, w: 0.054 },
    voiceHints: ["heera", "neerja", "swara", "veena", "kalpana", "aditi", "raveena", "female", "zira", "samantha", "susan", "karen", "moira", "tessa", "google uk english female", "google us english"],
    pitch: 1.05,
  },
  male: {
    key: "male",
    name: "Arjun",
    role: "Hiring manager",
    agent: "pilot",
    mouth: { x: 0.488, y: 0.566, w: 0.046 },
    voiceHints: ["ravi", "rishi", "prabhat", "hemant", "madhur", "male", "daniel", "david", "alex", "fred", "google uk english male"],
    pitch: 0.95,
  },
};

/** The best installed voice for this interviewer: Indian English first, then any English voice of the right gender. */
export function pickVoice(iv: Interviewer): SpeechSynthesisVoice | null {
  if (typeof speechSynthesis === "undefined") return null;
  const voices = speechSynthesis.getVoices().filter((v) => v.lang.toLowerCase().startsWith("en"));
  const other = iv.key === "female" ? INTERVIEWERS.male.voiceHints : INTERVIEWERS.female.voiceHints;
  const fits = (v: SpeechSynthesisVoice) => iv.voiceHints.some((h) => v.name.toLowerCase().includes(h)) && !(iv.key === "male" && v.name.toLowerCase().includes("female"));
  const notOther = (v: SpeechSynthesisVoice) => !other.slice(0, 6).some((h) => v.name.toLowerCase().includes(h));
  return (
    voices.find((v) => v.lang === "en-IN" && fits(v)) ??
    voices.find((v) => fits(v)) ??
    voices.find((v) => v.lang === "en-IN" && notOther(v)) ??
    voices.find(notOther) ??
    voices[0] ??
    null
  );
}

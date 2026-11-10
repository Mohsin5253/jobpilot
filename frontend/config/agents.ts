/**
 * The JobPilot crew: one source of truth for every agent's name, role, tint, artwork, face crop and
 * first-person copy. Characters are original realistic-3D crew members in one uniform (graphite jacket,
 * off-white tee, cobalt piping, crew pin), lit with the same cobalt rim light the UI uses.
 */

export type AgentKey = "pilot" | "researcher" | "scout" | "verifier" | "matcher" | "interviewer" | "tailor" | "outreach" | "dispatch" | "tracker";
export type CrewKey = AgentKey | "you";

export interface AgentConfig {
  key: AgentKey;
  name: string;
  /** One line: what this agent does for you. */
  role: string;
  /** Signature prop, used in alt text. */
  prop: string;
  /** CSS variable for the identity tint (avatar backdrops at 10–14%, tiny accents only). */
  tint: string;
  images: { idle: string; working: string };
  /** object-position for the face crop at ≤40px, and how far to zoom in. */
  face: { x: number; y: number; zoom: number };
  /** Grayscale depth maps (white = near) for the 3D relief, one per pose. */
  depth: { idle: string; working: string };
  /** Cut-out masks (white = figure) for the landing stage, one per pose. */
  mask: { idle: string; working: string };
  /** Said by this agent when its view is empty. */
  empty: { title: string; body: string };
}

const img = (k: AgentKey) => ({ idle: `/agents/${k}-idle.webp`, working: `/agents/${k}-working.webp` });
const depth = (k: AgentKey) => ({ idle: `/agents/depth/${k}-idle.png`, working: `/agents/depth/${k}-working.png` });
const mask = (k: AgentKey) => ({ idle: `/agents/mask/${k}-idle.png`, working: `/agents/mask/${k}-working.png` });

export const AGENTS: Record<AgentKey, AgentConfig> = {
  pilot: {
    key: "pilot",
    name: "Pilot",
    role: "Leads the crew and keeps you posted",
    prop: "headset",
    tint: "var(--tint-pilot)",
    images: img("pilot"),
    depth: depth("pilot"),
    mask: mask("pilot"),
    face: { x: 49, y: 32, zoom: 2 },
    empty: { title: "I’m ready when you are", body: "Upload your resume and I’ll send the crew out." },
  },
  researcher: {
    key: "researcher",
    name: "Researcher",
    role: "Finds companies hiring for your profile",
    prop: "tablet with a company map",
    tint: "var(--tint-researcher)",
    images: img("researcher"),
    depth: depth("researcher"),
    mask: mask("researcher"),
    face: { x: 50, y: 33, zoom: 2 },
    empty: { title: "No new companies yet", body: "I’ll look again on the next run." },
  },
  scout: {
    key: "scout",
    name: "Scout",
    role: "Watches job boards for live openings",
    prop: "binoculars",
    tint: "var(--tint-scout)",
    images: img("scout"),
    depth: depth("scout"),
    mask: mask("scout"),
    face: { x: 46, y: 25, zoom: 2.1 },
    empty: { title: "Scouting new roles", body: "Check back after the next run." },
  },
  verifier: {
    key: "verifier",
    name: "Verifier",
    role: "Checks every job is real before you see it",
    prop: "magnifying glass and a verified shield",
    tint: "var(--tint-verifier)",
    images: img("verifier"),
    depth: depth("verifier"),
    mask: mask("verifier"),
    face: { x: 50, y: 30, zoom: 2 },
    empty: { title: "Nothing to check yet", body: "I check every new job for scams the moment Scout finds it." },
  },
  matcher: {
    key: "matcher",
    name: "Matcher",
    role: "Scores how well each job fits you",
    prop: "glowing score ring",
    tint: "var(--tint-matcher)",
    images: img("matcher"),
    depth: depth("matcher"),
    mask: mask("matcher"),
    face: { x: 52, y: 28, zoom: 2 },
    empty: { title: "Nothing to score yet", body: "I score every new posting the moment Scout finds it." },
  },
  interviewer: {
    key: "interviewer",
    name: "Interviewer",
    role: "Asks about skills you might be missing",
    prop: "notebook of question cards",
    tint: "var(--tint-interviewer)",
    images: img("interviewer"),
    depth: depth("interviewer"),
    mask: mask("interviewer"),
    face: { x: 48, y: 30, zoom: 2.1 },
    empty: { title: "No questions right now", body: "I’ll ask when a job you nearly match needs one skill." },
  },
  tailor: {
    key: "tailor",
    name: "Tailor",
    role: "Tailors your resume to each job",
    prop: "tape measure and stylus",
    tint: "var(--tint-tailor)",
    images: img("tailor"),
    depth: depth("tailor"),
    mask: mask("tailor"),
    face: { x: 49, y: 29, zoom: 2 },
    empty: { title: "Add projects so I can tailor better", body: "Link GitHub or add a project to your proof pack." },
  },
  outreach: {
    key: "outreach",
    name: "Outreach",
    role: "Drafts emails and referral requests",
    prop: "paper plane",
    tint: "var(--tint-outreach)",
    images: img("outreach"),
    depth: depth("outreach"),
    mask: mask("outreach"),
    face: { x: 47, y: 30, zoom: 2.1 },
    empty: { title: "All caught up", body: "Nothing waiting for you." },
  },
  dispatch: {
    key: "dispatch",
    name: "Dispatch",
    role: "Sends what you approve",
    prop: "courier satchel",
    tint: "var(--tint-dispatch)",
    images: img("dispatch"),
    depth: depth("dispatch"),
    mask: mask("dispatch"),
    face: { x: 50, y: 28, zoom: 2 },
    empty: { title: "Nothing to send", body: "I only send what you approve." },
  },
  tracker: {
    key: "tracker",
    name: "Tracker",
    role: "Tracks applications and follow-ups",
    prop: "kanban clipboard",
    tint: "var(--tint-tracker)",
    images: img("tracker"),
    depth: depth("tracker"),
    mask: mask("tracker"),
    face: { x: 47, y: 28, zoom: 2 },
    empty: { title: "No applications yet", body: "When you apply, I’ll track replies and remind you to follow up." },
  },
};

/** The crew in pipeline order; "you" is the approval stage. */
export const FLIGHT_PATH: CrewKey[] = ["researcher", "scout", "verifier", "matcher", "interviewer", "tailor", "outreach", "you", "dispatch", "tracker"];

/** Pipeline step keys used by the API (the "you" stage is the approval step). */
export const STEP_TO_CREW: Record<string, CrewKey> = {
  researcher: "researcher",
  scout: "scout",
  verifier: "verifier",
  matcher: "matcher",
  interviewer: "interviewer",
  tailor: "tailor",
  outreach: "outreach",
  approval: "you",
  dispatch: "dispatch",
  tracker: "tracker",
};

export const CREW_HERO = { src: "/agents/crew-hero.webp", width: 2400, height: 1340, alt: "The JobPilot crew: Pilot with Scout, Researcher, Matcher and Outreach" };

export const agentAlt = (k: AgentKey) => `${AGENTS[k].name}, the agent that ${AGENTS[k].role.charAt(0).toLowerCase()}${AGENTS[k].role.slice(1)}`;

/** Where the head sits in a portrait (UV, y up) and its radius, for the 3D head rig. From the face crop. */
export const headOf = (k: AgentKey) => ({ x: AGENTS[k].face.x / 100, y: 1 - (AGENTS[k].face.y + 1) / 100, r: 0.14 });

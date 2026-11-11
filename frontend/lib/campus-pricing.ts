/** Campus (placement cell) plans: one list for the landing page, the pricing page and Billing. Flat yearly prices in
 * rupees, GST extra. Change the numbers here and every page follows. */
export type CampusPlan = {
  key: "pilot" | "department" | "institution" | "university";
  name: string;
  price: string;
  per: string;
  note: string;
  bestFor: string;
  features: string[];
  cta: string;
  highlight?: boolean;
};

export const CAMPUS_PILOT_STUDENTS = 200;
export const CAMPUS_DEPARTMENT_INR = 4999;
export const CAMPUS_DEPARTMENT_STUDENTS = 300;
export const CAMPUS_COLLEGE_INR = 29999;
export const CAMPUS_COLLEGE_STUDENTS = 2000;
export const CAMPUS_UNIVERSITY_INR = 99999;
export const CAMPUS_GOVT_DISCOUNT = 25; // % off for government and government-aided colleges
export const CAMPUS_REFUND_DAYS = 30;

export const inr = (n: number) => `₹${n.toLocaleString("en-IN")}`;
/** The lowest paid campus price, for the landing page's "from" figure. */
export const CAMPUS_FROM_INR = CAMPUS_DEPARTMENT_INR;

export const CAMPUS_PLANS: CampusPlan[] = [
  {
    key: "pilot",
    name: "Pilot",
    price: "₹0",
    per: "one placement season",
    note: `Up to ${CAMPUS_PILOT_STUDENTS} students · 1 TPO + 3 staff`,
    bestFor: "Trying it with one batch",
    features: ["Student invite code and staff code", "Drives with automatic eligibility checks", "Live placement pipeline", "AI match proposals for staff to approve"],
    cta: "Start a free pilot",
  },
  {
    key: "department",
    name: "Department",
    price: inr(CAMPUS_DEPARTMENT_INR),
    per: "per year",
    note: `One department, up to ${CAMPUS_DEPARTMENT_STUDENTS} students · HOD + 5 faculty`,
    bestFor: "A single HOD running placements",
    features: ["Everything in Pilot", "Jobs posted from recruiter links, matched to students in minutes", "Department-scoped views", "Precision report on the AI's proposals", "Email support"],
    cta: "Get started",
  },
  {
    key: "institution",
    name: "College",
    price: inr(CAMPUS_COLLEGE_INR),
    per: "per year",
    note: `Whole college, up to ${CAMPUS_COLLEGE_STUDENTS.toLocaleString("en-IN")} students · unlimited staff`,
    bestFor: "The whole placement cell",
    features: [
      "Every department, unlimited TPO / HOD / faculty accounts",
      "Department-scoped views for HODs and faculty",
      "Live updates to every staff dashboard as students move through rounds",
      "Audit log of every staff view of student data",
      "Alumni referrals, cohort reports, priority support",
    ],
    cta: "Get a quote",
    highlight: true,
  },
  {
    key: "university",
    name: "University",
    price: inr(CAMPUS_UNIVERSITY_INR),
    per: "per university / year",
    note: "One price for the whole university: every campus and constituent college, unlimited students and staff",
    bestFor: "Universities and college groups",
    features: ["Everything in College, for every campus", "Each campus with its own staff, codes and data", "Combined placement reports across campuses, on request", "Data processing agreement (DPDP Act)", "A named success manager"],
    cta: "Talk to us",
  },
];

/** The terms colleges sign up to, in plain words. */
export const CAMPUS_TERMS: string[] = [
  "Prices are per year, billed annually by GST invoice (GST extra). Pay by bank transfer or UPI.",
  `Government and government-aided colleges get ${CAMPUS_GOVT_DISCOUNT}% off any paid plan.`,
  `Full refund within ${CAMPUS_REFUND_DAYS} days of payment if it isn't working for you.`,
  "No lock-in: renew each year only if you want to. We'll remind you 30 days before renewal; the price is fixed for your first two renewals.",
  "Going over your student limit mid-year never cuts anyone off; we'll talk about the next plan at renewal.",
  "Your college owns its data. Students decide whether to share their progress, and can stop at any time.",
  "Students never pay for anything the college plan covers; Pro stays optional for them.",
  "Cancel any time: on request we delete the college's workspace data within 30 days (export first if you need it).",
];

export const CAMPUS_FAQ: { q: string; a: string }[] = [
  {
    q: "Can staff see every student's data?",
    a: "No. Staff see college-wide numbers for everyone, but a student's name, applications and pipeline only if that student chose to share their progress with the college. The database itself enforces this, and every staff view is written to an audit log.",
  },
  {
    q: "Who can join as staff?",
    a: "HODs and faculty join with your college's staff code, and you can require an email on your college domain. The code is stored only as a hash and shown once when issued. TPO access is granted by us or by another TPO, never self-selected.",
  },
  {
    q: "What do the AI match proposals do?",
    a: "When you post a job (or a student's own agents find a strong one), JobPilot ranks your sharing students for it: nearest profiles first, then a requirement-by-requirement review that quotes each resume. You approve or reject each proposal; approved students are shortlisted and told. Your decisions measure the AI's precision.",
  },
  {
    q: "How is the University plan priced?",
    a: `One flat price per university (${inr(CAMPUS_UNIVERSITY_INR)} a year), however many campuses, constituent colleges, students or staff it has.`,
  },
  { q: "Do students pay anything?", a: "No. Students use JobPilot free; Pro stays optional for them. The college plan covers the placement-cell tools." },
];

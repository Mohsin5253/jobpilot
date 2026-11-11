/** Campus (placement cell) plans: one list for the landing page, the pricing page and Billing. Prices in rupees, per year. */
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

export const CAMPUS_PER_STUDENT_INR = 99;
export const CAMPUS_MIN_STUDENTS = 500;
export const CAMPUS_DEPARTMENT_INR = 19999;
export const CAMPUS_PILOT_STUDENTS = 300;

const inr = (n: number) => `₹${n.toLocaleString("en-IN")}`;

export const CAMPUS_PLANS: CampusPlan[] = [
  {
    key: "pilot",
    name: "Pilot",
    price: "₹0",
    per: "one placement season",
    note: `Up to ${CAMPUS_PILOT_STUDENTS} students · 1 TPO + 5 staff`,
    bestFor: "Trying it with one batch",
    features: ["Student invite code and staff code", "Drives with automatic eligibility checks", "Live placement pipeline", "AI match proposals for staff to approve"],
    cta: "Start a free pilot",
  },
  {
    key: "department",
    name: "Department",
    price: inr(CAMPUS_DEPARTMENT_INR),
    per: "per year",
    note: "One department, up to 400 students",
    bestFor: "A single HOD running placements",
    features: ["Everything in Pilot", "HOD + up to 10 faculty accounts", "Jobs posted from recruiter links, matched to students in minutes", "Precision report on the AI's proposals", "Email support"],
    cta: "Talk to us",
  },
  {
    key: "institution",
    name: "Institution",
    price: inr(CAMPUS_PER_STUDENT_INR),
    per: "per student / year",
    note: `Minimum ${CAMPUS_MIN_STUDENTS} students (${inr(CAMPUS_PER_STUDENT_INR * CAMPUS_MIN_STUDENTS)}/year)`,
    bestFor: "The whole college's placement cell",
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
    name: "University / Group",
    price: "Custom",
    per: "several campuses",
    note: "Several campuses, data processing agreement",
    bestFor: "Universities and college groups",
    features: ["Everything in Institution", "Several campuses, each with its own staff, codes and data", "Data processing agreement (DPDP Act)", "Custom reports for accreditation (NAAC / NIRF placement data)", "A named success manager"],
    cta: "Contact sales",
  },
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
  { q: "Do students pay anything?", a: "No. Students use JobPilot free; Pro stays optional for them. The college plan covers the placement-cell tools." },
  { q: "How do we pay?", a: "By invoice, with GST, through bank transfer or UPI. The Pilot is free for one placement season, no card needed." },
];

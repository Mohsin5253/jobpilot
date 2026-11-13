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
export const CAMPUS_COLLEGE_STUDENTS = 2_000_000; // 20 lakh, per college or per branch
export const CAMPUS_UNIVERSITY_INR = 99999;
export const CAMPUS_GOVT_DISCOUNT = 25; // % off for government and government-aided colleges
export const CAMPUS_REFUND_DAYS = 30;

export const inr = (n: number) => `₹${n.toLocaleString("en-IN")}`;
/** 20,00,000 -> "20 lakh"; smaller numbers as they are. */
export const students = (n: number) => (n >= 100_000 && n % 100_000 === 0 ? `${n / 100_000} lakh` : n.toLocaleString("en-IN"));
/** The lowest paid campus price, for the landing page's "from" figure. */
export const CAMPUS_FROM_INR = CAMPUS_DEPARTMENT_INR;

export const CAMPUS_PLANS: CampusPlan[] = [
  {
    key: "pilot",
    name: "Pilot",
    price: "₹0",
    per: "one placement season",
    note: `Up to ${CAMPUS_PILOT_STUDENTS} students · unlimited staff`,
    bestFor: "Trying it with one batch",
    features: ["Student invite code and staff code", "Drives with automatic eligibility checks", "Live placement pipeline", "AI match proposals for staff to approve"],
    cta: "Start a free pilot",
  },
  {
    key: "department",
    name: "Department",
    price: inr(CAMPUS_DEPARTMENT_INR),
    per: "per year",
    note: `One department, up to ${CAMPUS_DEPARTMENT_STUDENTS} students · unlimited staff`,
    bestFor: "A single HOD running placements",
    features: ["Everything in Pilot", "Register your department yourself: live after we verify it", "The HOD runs it: setup, staff, roster and seats", "Jobs posted from recruiter links, matched to students in minutes", "Precision report on the AI's proposals", "Email support"],
    cta: "Get started",
  },
  {
    key: "institution",
    name: "College",
    price: inr(CAMPUS_COLLEGE_INR),
    per: "per year",
    note: `Whole college or one branch, up to ${students(CAMPUS_COLLEGE_STUDENTS)} students · unlimited staff`,
    bestFor: "The whole placement cell",
    features: [
      "Every department and field, unlimited TPO / HOD / faculty accounts",
      "Up to 20 lakh students: degrees, departments, programmes and batches set up your way",
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
    note: "One price for the whole university: every campus, branch and constituent college, no limit on students or staff",
    bestFor: "Universities and college groups",
    features: ["Everything in College, for every campus and branch", "Branches with different fields under one name (e.g. Engineering and Law), each with its own staff, codes and data", "Combined placement reports across campuses, on request", "Data processing agreement (DPDP Act)", "A named success manager"],
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
    a: "Two kinds of data, two rules. College records (name, roll number, degree, department, batch, score and pending subjects) come from your college and are visible to authorised staff for the students in their scope. Everything a student creates in JobPilot (applications, resume, matches, internships, roles, awards and proof files) is shown to staff by name only if that student chooses to share it with the college; otherwise staff see only totals. The database enforces both rules, and every staff view is written to an audit log.",
  },
  {
    q: "Who can join as staff?",
    a: "Only verified staff: they need your college's staff code (locked after repeated wrong tries), must confirm an email on your college's own domain (personal addresses like Gmail are refused), and get no access until the TPO or Principal approves them. Students can't open the staff portal. The code is stored only as a hash and shown once. TPO access is granted by us or by another TPO, and TPOs and Principals confirm a one-time code each time they sign in.",
  },
  {
    q: "What do the AI match proposals do?",
    a: "When you post a job (or a student's own agents find a strong one), JobPilot ranks your sharing students for it: nearest profiles first, then a requirement-by-requirement review that quotes each resume. You approve or reject each proposal; approved students are shortlisted and told. Your decisions measure the AI's precision.",
  },
  {
    q: "How is the University plan priced?",
    a: `One flat price per university (${inr(CAMPUS_UNIVERSITY_INR)} a year), however many campuses, branches, constituent colleges, students or staff it has: there's no student limit.`,
  },
  {
    q: "Our college has an engineering branch and a law branch under the same name. How does that work?",
    a: `Each branch is set up as its own campus under your college's name: its own fields, degrees, departments, staff, staff code and data, and up to ${students(CAMPUS_COLLEGE_STUDENTS)} students each. Your TPO adds a branch in Campus → Setup and switches between them in the portal. The College plan covers one branch; the University plan covers them all.`,
  },
  {
    q: "Can one department sign up without the whole college?",
    a: `Yes, on the Department plan. The HOD registers the department (for example Computer Science or Electronics and Computer Science) in Campus (Staff) with an email on the college's own domain. We check it belongs to that college and then it's live with ${CAMPUS_DEPARTMENT_STUDENTS} student seats and its own staff code. Several departments of one college can each have their own plan. When a department is full, new students wait on a list rather than being turned away silently.`,
  },
  { q: "Do students pay anything?", a: "No. Students use JobPilot free; Pro stays optional for them. The college plan covers the placement-cell tools." },
];

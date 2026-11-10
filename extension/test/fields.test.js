const test = require("node:test");
const assert = require("node:assert/strict");
const { planFill, resumeInput } = require("../src/fields.js");

const data = {
  applicant: {
    first_name: "Aarav", last_name: "Mehta", full_name: "Aarav Mehta", email: "aarav@example.com", phone: "+91 98765 43210",
    linkedin: "https://linkedin.com/in/aarav", github: "https://github.com/aarav", website: "", location: "Mumbai",
    school: "Mumbai University", degree: "B.E. Computer Engineering", graduation_year: "2027",
  },
  cover_note: "Hi team, ...",
};
const byKey = (plan) => Object.fromEntries(plan.map((p) => [p.key, p.value]));

test("greenhouse form", () => {
  const fields = [
    { id: "first_name", name: "job_application[first_name]", label: "First Name", type: "text", tag: "input" },
    { id: "last_name", name: "job_application[last_name]", label: "Last Name", type: "text", tag: "input" },
    { id: "email", name: "job_application[email]", label: "Email", type: "text", tag: "input" },
    { id: "phone", name: "job_application[phone]", label: "Phone", type: "text", tag: "input" },
    { id: "resume", name: "resume", label: "Resume/CV", type: "file", tag: "input" },
    { id: "cover_letter_text", name: "cover_letter_text", label: "Cover Letter", type: "textarea", tag: "textarea" },
    { id: "q1", name: "question_1", label: "LinkedIn Profile", type: "text", tag: "input" },
    { id: "q2", name: "question_2", label: "What are your salary expectations?", type: "text", tag: "input" },
  ];
  const plan = byKey(planFill(fields, data));
  assert.equal(plan.first_name, "Aarav");
  assert.equal(plan.last_name, "Mehta");
  assert.equal(plan.email, "aarav@example.com");
  assert.equal(plan.linkedin, "https://linkedin.com/in/aarav");
  assert.equal(plan.cover_letter, "Hi team, ...");
  assert.ok(!Object.values(plan).includes(undefined));
  assert.equal(planFill(fields, data).find((p) => p.id === "q2"), undefined, "salary is never filled");
  assert.equal(resumeInput(fields).id, "resume");
});

test("lever form", () => {
  const fields = [
    { id: "name", name: "name", label: "Full name", type: "text", tag: "input" },
    { id: "email", name: "email", label: "Email", type: "email", tag: "input" },
    { id: "org", name: "org", label: "Current company", type: "text", tag: "input" },
    { id: "li", name: "urls[LinkedIn]", label: "LinkedIn URL", type: "text", tag: "input" },
    { id: "gh", name: "urls[GitHub]", label: "GitHub URL", type: "text", tag: "input" },
    { id: "comments", name: "comments", label: "Additional information", type: "textarea", tag: "textarea" },
  ];
  const plan = byKey(planFill(fields, data));
  assert.equal(plan.full_name, "Aarav Mehta");
  assert.equal(plan.github, "https://github.com/aarav");
  assert.equal(plan.cover_letter, "Hi team, ...");
  assert.equal(plan.org, undefined, "fields it doesn't know are left alone");
});

test("sensitive and empty values are skipped", () => {
  const fields = [
    { id: "g", name: "gender", label: "Gender", type: "text", tag: "input" },
    { id: "w", name: "website", label: "Website", type: "text", tag: "input" },
    { id: "p", name: "password", label: "Password", type: "password", tag: "input" },
  ];
  assert.deepEqual(planFill(fields, data), []);
});

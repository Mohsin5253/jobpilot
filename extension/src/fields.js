// Which value goes in which application-form field (Greenhouse, Lever, Ashby). Pure, so it is unit-tested
// in Node and shared with the content script. A field is {id, name, label, type, autocomplete, tag}.
(function (root) {
  const RULES = [
    // key, applicant field, matchers on autocomplete / name / label (first match wins, most specific first)
    ["first_name", "first_name", [/given-name/, /^first[_ ]?name$/, /\bfirst name\b/, /\bpreferred first name\b/]],
    ["last_name", "last_name", [/family-name/, /^last[_ ]?name$/, /\blast name\b/, /\bsurname\b/]],
    ["full_name", "full_name", [/^name$/, /\bfull name\b/, /^your name$/, /\blegal name\b/]],
    ["email", "email", [/^email$/, /e-?mail/]],
    ["phone", "phone", [/^tel$/, /phone|mobile|contact number/]],
    ["linkedin", "linkedin", [/linkedin/]],
    ["github", "github", [/github/]],
    ["website", "website", [/portfolio|personal (web)?site|^website$|urls\[other\]/]],
    ["location", "location", [/^(city|location)$/, /current location|where are you (based|located)|\bcity\b/]],
    ["school", "school", [/school|university|college|institution/]],
    ["degree", "degree", [/\bdegree\b|qualification/]],
    ["graduation_year", "graduation_year", [/graduat(ion|e) (year|date)|year of graduation|passing year/]],
    ["cover_letter", "cover_note", [/cover[_ ]?letter|additional information|^comments$|why (do you want|are you interested)/]],
  ];
  const NEVER = /password|salary|ctc|compensation|visa|sponsor|gender|race|ethnic|veteran|disab|pronoun|date of birth|\bdob\b|aadhaar|pan\b|captcha/;

  function describe(f) {
    return [f.autocomplete, f.name, f.id, f.label].filter(Boolean).map((x) => String(x).toLowerCase().trim());
  }

  function planFill(fields, data) {
    const applicant = (data && data.applicant) || {};
    const values = { ...applicant, cover_note: (data && data.cover_note) || "" };
    const used = new Set();
    const plan = [];
    for (const f of fields) {
      if (f.type === "file" || f.type === "hidden" || f.type === "submit" || f.type === "checkbox" || f.type === "radio") continue;
      const texts = describe(f);
      if (texts.some((t) => NEVER.test(t))) continue; // sensitive questions are always left to you
      for (const [key, source, matchers] of RULES) {
        if (used.has(key)) continue;
        if (key === "cover_letter" && f.tag !== "textarea") continue;
        if (!texts.some((t) => matchers.some((m) => m.test(t)))) continue;
        const value = values[source];
        if (!value) break;
        plan.push({ id: f.id, key, value: String(value) });
        used.add(key);
        break;
      }
    }
    // A form with one "name" field and no first/last ones gets the full name.
    return plan;
  }

  function resumeInput(fields) {
    const files = fields.filter((f) => f.type === "file");
    return (
      files.find((f) => describe(f).some((t) => /resume|cv/.test(t))) ||
      files.find((f) => !describe(f).some((t) => /cover/.test(t))) ||
      null
    );
  }

  const api = { planFill, resumeInput, NEVER };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.JobPilotFields = api;
})(typeof globalThis !== "undefined" ? globalThis : this);

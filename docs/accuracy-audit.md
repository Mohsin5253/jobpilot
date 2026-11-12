# JobPilot accuracy and safety audit

Status as of 13 Nov 2026. Covers every phase of the hardening plan:
- Phase 0: the audit.
- Safety rails.
- Input hygiene.
- Accuracy.
- Evals with a CI gate and a red-team suite.
- Observability: a quality dashboard and Approvals risk flags.

Section 8 has the measured numbers. Section 9 lists what still needs real data or your decision.

Legend: ✅ enforced in code and proven by a test · ⚠️ partly enforced, or enforced but not yet proven · ❌ missing.
"Before" is the state found by the audit; "Now" is after this change.

## 1. Inventory: every AI feature

All AI calls go through one client (`app/llm.py`). It validates every reply against a Pydantic schema; a bad reply is
re-asked with the validation error, up to 2 times (`LLM_MAX_REPAIRS`), then the call fails and the feature falls back to
its offline version. Models are set in one place (`app/config.py`, `PROVIDER_MODELS`):
- fast tier: `openai/gpt-oss-20b`;
- smart tier: `openai/gpt-oss-120b`;
- dictation clean-up: `qwen/qwen3.8-27b`, falling back to `openai/gpt-oss-20b`;
- speech-to-text: `whisper-large-v3-turbo`, falling back to `whisper-large-v3`.

Prompts live inline in each module. They aren't yet versioned files (see §7).

| Feature | Agent / tier | Prompt in | Tools it can reach | Side effects | Validation | Tests |
|---|---|---|---|---|---|---|
| Researcher (find company boards) | researcher · fast | `agents/researcher.py` | egress `sources` (ATS APIs) | adds boards to the student's preferences | schema | `test_research_and_apply.py` |
| Scout (fetch postings) | no LLM | `services/job_store.py`, `sources/*` | egress `sources`, `career_page` | inserts jobs | dedupe, ingest scam filter | `test_sources.py`, `test_india_sources.py`, `test_jsearch_and_refresh.py` |
| Verifier | rules, then verifier · fast (second opinion, can only make a verdict worse) | `agents/verifier.py` | egress `link_check` | job verdict; voids drafts of blocked or closed postings (new) | rule engine + schema | `test_verifier.py`, `test_scam_shield.py`, `test_v10_safety.py` |
| Matcher | matcher · fast (cached, new) | `agents/matcher.py` | none | match rows | schema + quote check (`audit_review`) | `test_pipeline.py`, `test_v10_safety.py` |
| Tailor | tailor · smart and fast | `agents/tailor.py` | none | tailored resume rows | schema + guard (`agents/guard.py`: reverts unprovided tools, skills, numbers) | `test_skills_and_guard.py` |
| Outreach | outreach · smart | `agents/outreach.py` | contacts lookup | pending drafts only | schema + freeform guard | `test_pipeline.py`, `test_contacts.py` |
| Contacts (domain guess) | contacts · fast | `services/contacts.py` | egress `contacts` | contact rows | homepage must name the company; recipient policy (new) | `test_contacts.py`, `test_v10_safety.py` |
| Dispatch | no LLM | `services/applications.py` | `email.send` (the only caller) | sends email | mandate + policy + recipient checks (new) | `test_v10_safety.py`, `test_research_and_apply.py` |
| Scam Shield | scam_shield · fast | `api/routes/scam.py` | egress `scam_shield`, `rdap` | a verdict row (hash, status) | rule engine; LLM can only make it stricter | `test_scam_shield.py`, `test_v10_safety.py` |
| Resume parse / restructure | resume_parser · smart | `services/resume_restructure.py` | none | profile resume | schema + entity checks | `test_v5_report_resume_stt.py` |
| ATS score and boost | score in code (`services/ats.py`); tailor · smart/fast rewrites | `services/ats_boost.py`, `services/resume_improve.py` | none | resume edits the student confirms | proven-skills only | `test_ats_interview.py`, `test_v6_boost_panel.py` |
| Mock interview (questions, follow-ups, scoring, panel, report) | interviewer · fast and smart | `services/interview_*.py`, `agents/interviewer.py` | none | interview rows | schema; hire band computed in code (`interview_panel.verdict`) | `test_interview_v3.py`, `test_v6_boost_panel.py` |
| Code review | interviewer · smart | `services/code_review.py` | none | review text | schema; code runs only in the student's browser | `test_coding_bank.py` |
| Dictation | Whisper + qwen clean-up | `dictation/*` | Groq ASR | none stored (timings only) | hallucination guards, clean-up guardrail | `test_v8_dictation.py`, `test_v9_flowtype.py` |
| Proof page | no LLM | `services/evidence.py` | egress `evidence` | public page (consent `public_proof`) | GitHub bio-code ownership | `test_v2.py`, `test_proof_links.py` |
| WhatsApp digest | no LLM | `services/whatsapp.py` | `whatsapp.send` | template messages | policy + consent (new) | `test_whatsapp_approvals.py`, `test_v10_safety.py` |

## 2. Promise-to-code matrix

| Public promise | Enforced in | Proven by | Before | Now |
|---|---|---|---|---|
| Nothing is sent without approval of that specific item | `safety/mandates.py` (payload-hash grant, single use, 30 min) · `services/applications.py` (Dispatch checks it) · `api/routes/drafts.py` (edit voids it) | `test_an_approval_sends_one_exact_email_once`, `test_a_forged_approved_status_without_a_grant_sends_nothing`, `test_editing_after_approval_needs_a_fresh_approval`, `test_a_changed_body_or_attachment_after_approval_is_not_sent`, `test_an_expired_approval_is_not_used` | ⚠️ an approved draft could be edited and then sent without a fresh approval, and `send_application` didn't check the status | ✅ |
| No bulk sends, no timers | no "approve all" route exists; approve shortcuts open a confirm step naming the recipient (`components/approvals/reviewer.tsx`) | route list; static check | ⚠️ the A / ⌘↵ shortcuts approved straight away | ✅ (UI behaviour not covered by an automated browser test) |
| Sends ≥ 90 s apart | `services/mailer.py` (row lock per mailbox) | `test_sends_are_spaced_and_the_kill_switch_stops_everything` | ✅ | ✅ |
| Free 5/day by default (max 10), Pro 50/day | `services/quota.py` | `test_provenance_quota.py` | ✅ | ✅ (an edited approval now gives the day's send back) |
| Never logs in to, automates or scrapes LinkedIn or the never-used boards; government portals linked only | `safety/egress.py`: denylist on every request and every redirect hop, for every purpose | `test_denied_domains_are_never_fetched` (13 domains × 7 purposes), `test_redirects_to_a_denied_domain_are_refused` | ⚠️ only the career-page and pasted-link paths checked the list; apply-link checks could open a LinkedIn or Naukri URL | ✅ |
| Pasted and forwarded job-board links are stored, never opened | `services/ingest.py` + egress denylist | `test_ingest.py`, egress tests | ✅ | ✅ |
| Greenhouse/Lever/Ashby ≤ 30 req/min; Adzuna/JSearch/Jobicy/Remotive/GitHub ≤ 1/min; The Muse ≤ 4/min | `safety/egress.py`: shared one-minute buckets in Postgres, ceilings read from the `sources` table shown on /trust | `test_source_rate_limits_hold_across_callers` | ❌ only per-source refresh intervals existed; nothing counted requests | ✅ |
| Career pages: robots.txt, ≤ 1 req/min per domain, cached | `sources/india.py` + egress bucket per domain (shared across replicas) | `test_india_sources.py` | ⚠️ the per-domain gap was per process | ✅ |
| Postings with a serious red flag are blocked: never matched, can't be approved | `agents/verifier.py` · routes · database triggers `jp_block_scam_match` / `jp_block_scam_draft` (migration 0027) · open drafts voided | `test_scam_flagged_postings_cannot_be_approved_or_sent` | ⚠️ enforced in code only | ✅ (in the database too) |
| Anything asking for money is blocked | Verifier `_PAY_TO_WORK` + Scam Shield fee/UPI checks, including Hinglish (`₹1999 advance dena hoga`) | eval gate `verifier.money_recall` on 300 postings · `test_hinglish_money_requests_are_blocked_and_no_fee_promises_are_not` | ⚠️ 88.9% money-request recall; Hinglish 56.5% | ✅ 100% on the synthetic set |
| Tailor guard reverts any tool, skill or number the student didn't provide; every revert logged | `agents/guard.py`: now also new company/product names and seniority upgrades ("built" → "led") | eval gate `tailor.*` (66 traps) · `test_guard_reverts_new_names_and_seniority_upgrades` | ⚠️ a new employer name slipped through | ✅ 0 fabrications slipped, every rephrase kept |
| Contacts: publicly listed, or a provider citing sources; never guessed | `safety/recipients.py` (company domain, no free-mail or lookalikes, Hunter only `valid` + confidence ≥ 80 + cited sources), applied when contacts are found and again at Dispatch | `test_recipient_policy`, `test_contacts.py` | ⚠️ Hunter `accept_all` and `unknown` addresses were used; no domain check | ✅ |
| Gmail is send-only, never reads the inbox | `services/gmail.py` scope `gmail.send`, checked at connect | `test_google_signin.py` | ✅ | ✅ |
| Run traces keep only timings, tokens and cost, never prompts or AI replies | `llm.py` traces; stored errors scrubbed (`content_free_error`, `scrub_error`) | `test_stored_llm_errors_hold_no_model_output` | ❌ a failed reply's text could be saved in `llm_calls.error` (Pydantic's `input_value=…` and Groq's `failed_generation`) | ✅ |
| Sentry receives no personal data | `safety/scrub.py` `before_send`, no local variables, no request bodies | `test_sentry_events_are_scrubbed` | ⚠️ `send_default_pii=False` only: exception messages and frame variables could still carry text | ✅ (backend; the website doesn't use Sentry) |
| Scam Shield: no sign-in, nothing you paste is stored | `api/routes/scam.py` stores {hash, verdict, check statuses} | `test_scam_shield_stores_and_logs_nothing_pasted` (scans every table and the logs for the pasted text) | ⚠️ true in code, not proven | ✅ |
| Extension fills forms and never clicks Submit | `extension/content.js` | `test_extension_never_submits_a_form` | ⚠️ not tested | ✅ |
| One-click apply only after the target ATS score is reached and the student confirms | `services/applications.check_target` in Dispatch + the mandate | `test_research_and_apply.py`, `test_v7…` | ✅ | ✅ |
| Proof page: off by default, GitHub verified, Codeforces from the API, unverified items labelled | `services/evidence.py`, consent `public_proof` | `test_v2.py`, `test_proof_links.py` | ✅ | ✅ |
| Campus: officers see totals unless the student shares more; enforced in the database; every view logged | RLS policies, `audit_events` | `test_campus_v2.py`, `test_v7_placement_portal.py` | ✅ | ✅ |
| Anonymous ledger: figures only with ≥ 3 students | `api/routes/ledger.py`: k ≥ 3, reports join in pairs, rounded figures, banded counts, no exact min/max, rates from 5 reports | `test_ledger_resists_differencing`, `test_growth.py` | ⚠️ exact min, max and rates at n = 3 identified individuals; one new report changed the page | ✅ |
| Retention: AI usage 90 d, notifications 60 d, demo 24 h, inactive 12 months with 30 d notice; deletion removes everything | `services/retention.py`, cascades | `test_dpdp.py` | ✅ | ✅ (the new cache is deleted after 30 days and with the account) |
| Transparency counters exclude demo accounts | `api/routes/public.py` | `test_public.py` | ✅ | ✅ |
| Users are 18+ | `api/routes/auth.py` | `test_v2.py` | ✅ | ✅ |
| Kill switch stops every send | `safety/policy.py`: `KILL_SWITCH` env or admin toggle, applied to every outside effect | `test_sends_are_spaced_and_the_kill_switch_stops_everything` | ❌ | ✅ |

## 3. Safety that relied on a prompt (each one moved into code)

| Where | Prompt said | Now enforced by |
|---|---|---|
| Outreach / Dispatch | "never send without approval" (the approval queue existed, but an edited approved draft could still be sent) | payload-bound grants, re-checked at send |
| Verifier second opinion | "judge only from the posting" | its answer can only make a verdict worse; the hard rules run first in code |
| Every prompt containing a job post | nothing: posting text was pasted straight into prompts | `safety/untrusted.py`: cleaned, scanned for injection, fenced; every prompt with a fence carries the "data, not instructions" note; flagged postings never reach Tailor, Outreach or Dispatch |
| Contacts | "use real public contacts" | `safety/recipients.py`, at lookup and at send |
| Tailor | "don't invent" | `agents/guard.py` (already in code) |

## 4. Where outside text reaches a model

| Input | Path | Now |
|---|---|---|
| Job posts (all sources) | Verifier, Matcher, Tailor, Outreach prompts | cleaned + fenced; injection-flagged posts kept out of Tailor and Outreach |
| Career pages | parsed JSON-LD only, then as job posts | same as job posts |
| Pasted offers / links (Scam Shield) | Scam Shield second opinion | rule engine first; LLM can only make it stricter |
| Resume PDFs / DOCX | restructure, ATS | white, invisible or under-2 pt text removed before parsing and flagged; never scored (`test_hidden_resume_text_is_removed_and_reported`) |
| Forwarded alert emails | link extraction only, no model | stored as links, boards never fetched |
| GitHub READMEs | not sent to a model | proof page shows metadata only |
| Interview answers and code | scoring, panel, follow-ups, code review | fenced as untrusted (code kept intact) |

## 5. Non-determinism: is each score computed by code?

| Score shown to students | Computed by | Same input, 5 runs |
|---|---|---|
| ATS score | code (`services/ats.py`) | identical by construction |
| Interview hire band | code from attribute scores (`interview_panel.verdict`) | identical given the same attribute scores |
| Match % | code blend: 25% semantic + 25% skills + 50% fit, where fit is now computed in code from requirement-by-requirement evidence (must 3 / nice 1; met 1 / partial 0.5; no MET without a resume quote; a skill taxonomy upgrades what the resume provably shows). The model's own number is no longer used | **before:** AI fit 82, 87, 86, 78, 83 (σ 3.2, so match % moved by up to 4.5 points) · temperature 0 tried: 70, 83, 68, 82, one failure (σ 6.8, worse: Groq's reasoning models don't sample deterministically) · **now:** the AI fit review is cached by a hash of model + prompt + schema, so 5 runs give one identical score (`test_ai_scored_features_repeat_exactly_for_the_same_input`) |
| Verifier verdict | rules in code; AI second opinion only for doubtful posts | rules identical; the second opinion is cached per posting |
| Interview attribute scores (1–4) | AI judge | ⚠️ not cached or calibrated yet (§7) |

The live re-measurement after caching was cut short: the Groq account hit its daily token limit (200,000 tokens a day
on `openai/gpt-oss-20b`). The determinism test above proves the cached path without a live call.

## 6. What changed in this step

- **New modules:** `app/safety/` holds
  - the tool registry with risk tiers;
  - the default-deny policy with its kill switch;
  - the egress gate;
  - approval mandates;
  - the recipient policy;
  - untrusted-content handling;
  - Sentry scrubbing.
- **Migrations:**
  - 0027: `approval_grants`, `system_flags`, voided drafts, required reject reasons, `jobs.injection_signals`, and the database triggers that block scam postings.
  - 0028: `ai_feature_cache`.
- **Admin:** `GET/POST /api/admin/kill-switch`.
- **Approvals page:** every approval, including the keyboard shortcuts, opens a confirm step naming the recipient and their domain; rejecting needs a reason.
- **Tests:**
  - 36 new adversarial and promise tests in `tests/test_v10_safety.py`;
  - the whole suite: 311 backend tests pass.

## 7. Accuracy, evals and observability (the later steps)

- **Input hygiene:**
  - Hidden resume text (white fill, invisible render mode, fonts under 2 pt, hidden DOCX runs) is removed before parsing and recorded in the profile.
  - Interview answers, candidate code and written approaches are fenced before the AI reads them.
- **Verifier:**
  - Hinglish payment phrasings added to the shared scam engine, so Scam Shield gets them too.
  - RDAP domain age for employers that aren't on a known careers system: under 180 days asks for care.
  - The AI second opinion is cached per posting.
- **Matcher:** the fit is computed in code from evidenced requirements, after a skill-taxonomy pass (sklearn = scikit-learn).
- **Tailor guard:** also reverts new company or product names and seniority upgrades.
- **Ledger:** protected against differencing.
- **Prompts:**
  - Every system prompt is hashed into `evals/data/prompt_versions.json`.
  - A test fails when a prompt changes without updating it (`python -m evals.prompts --update`).
  - Each AI call stores its prompt hash (`llm_calls.prompt_version`, migration 0029), never the text.
- **Eval gate** (`evals/gate.py`, run by `make eval` and in CI with the report in the run summary):
  - Golden sets in `evals/datasets/` (built by `python -m evals.datasets.build`).
  - Hard thresholds, plus a failure on any metric falling more than 2 points below `evals/baseline.json`.
- **Admin:** an `/admin/quality` section (`GET /api/admin/quality`), built from metadata only. It shows:
  - verdict mix and VERIFIED share against the previous window;
  - injection-flagged posts and the guard revert rate;
  - AI failure and repair rates by agent, with p95 latency;
  - approval, grant and reject-reason counts;
  - reply rate and ₹ per run;
  - alerts on suspicious shifts.
- **Approvals:**
  - Each card shows why the recipient is trusted (on the posting, on the company site, verified with sources, or typed by you), or why it isn't allowed.
  - It also flags injection, and shows void and reject reasons.
  - A new Voided view lists drafts taken out of the queue.

## 8. Measured (eval gate, 13 Nov 2026)

| Suite | Cases | Result | Required |
|---|---|---|---|
| Verifier: VERIFIED precision | 300 postings (106 in Hindi, Marathi or Hinglish) | 100% | ≥ 99% |
| Verifier: money-request recall | 90 | 100% (was 88.9%; Hinglish was 56.5%) | 100% |
| Verifier: scam recall | 150 | 100% | ≥ 95% |
| Verifier: legitimate postings blocked | 150 (30 mention "no fee") | 0% | ≤ 3% |
| Tailor traps: fabrications that slipped through | 60 traps (tools, numbers, seniority, companies) | 0 (was 1: a new employer name) | 0 |
| Tailor: honest rephrases kept | 6 | 100% | ≥ 90% |
| Egress decisions | 40 | 100% | 100% |
| Red team: injections flagged | 20 attacks in 4 languages | 100% | 100% |
| Red team: ordinary job text flagged | 15 | 0% | 0% |
| Recipient policy | 13 | 100% | 100% |
| Determinism (ATS score, match fit, 5 runs) | 2 | identical | identical |
| Scam Shield (hand-labelled set / held-out set) | 48 / 12 | 100% / 91.7% | ≥ 95% / reported |
| Backend tests | 323 | all pass | all |

**Caveats.** The golden sets are synthetic: written from public descriptions of Indian internship and task scams, with fictional companies. They prove the rules work and stop regressions. They aren't a substitute for real labelled postings, and the 100% figures will drop on real data.

## 9. Still open: needs real data, or your decision

- **Real labelled data:**
  - human-labelled resume–JD pairs for Matcher correlation (target ≥ 0.8);
  - human-rated interview sessions to calibrate the AI judges (target κ ≥ 0.6);
  - recorded Indian-English clips for transcription WER (≤ 10%; ≤ 5% on vocabulary terms);
  - real postings and offers to replace the synthetic Verifier set.
  
  These need data you collect, or consented student data. I didn't fabricate any.
- **Coding rounds:** code runs only in the student's browser. A server sandbox, and checking stated Big-O against runtime measurements, would be new infrastructure (CPU-limited, network-free workers). That's a hosting cost to decide on.
- **Prompts:** they still live in the code as constants. Each is versioned by hash, so a change is caught, but they aren't split into `prompts/<feature>/vN.md` files.
- **Decisions for you:**
  - the 30-minute approval expiry (`APPROVAL_GRANT_TTL_MIN`);
  - Hunter contacts now needing a `valid` verification;
  - whether to add the optional "help improve accuracy" consent purpose. It changes the Trust page, so it isn't built.

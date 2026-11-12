# JobPilot accuracy and safety audit

Status as of 13 Nov 2026. Covers Phase 0 (the audit) and the first two delivery steps of the hardening plan: safety
rails, and input hygiene. Later steps are listed at the end with what's left.

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
| Anything asking for money is blocked | Verifier `_PAY_TO_WORK` + Scam Shield fee/UPI checks | `test_scam_shield.py` (golden set) | ✅ English/Hindi/Marathi on the current golden set | ⚠️ the 300-posting golden set and its recall numbers are still to build (§7) |
| Tailor guard reverts any tool, skill or number the student didn't provide; every revert logged | `agents/guard.py` | `test_skills_and_guard.py` | ✅ | ✅ (the 60-case trap set is still to build) |
| Contacts: publicly listed, or a provider citing sources; never guessed | `safety/recipients.py` (company domain, no free-mail or lookalikes, Hunter only `valid` + confidence ≥ 80 + cited sources), applied when contacts are found and again at Dispatch | `test_recipient_policy`, `test_contacts.py` | ⚠️ Hunter `accept_all` and `unknown` addresses were used; no domain check | ✅ |
| Gmail is send-only, never reads the inbox | `services/gmail.py` scope `gmail.send`, checked at connect | `test_google_signin.py` | ✅ | ✅ |
| Run traces keep only timings, tokens and cost, never prompts or AI replies | `llm.py` traces; stored errors scrubbed (`content_free_error`, `scrub_error`) | `test_stored_llm_errors_hold_no_model_output` | ❌ a failed reply's text could be saved in `llm_calls.error` (Pydantic's `input_value=…` and Groq's `failed_generation`) | ✅ |
| Sentry receives no personal data | `safety/scrub.py` `before_send`, no local variables, no request bodies | `test_sentry_events_are_scrubbed` | ⚠️ `send_default_pii=False` only: exception messages and frame variables could still carry text | ✅ (backend; the website doesn't use Sentry) |
| Scam Shield: no sign-in, nothing you paste is stored | `api/routes/scam.py` stores {hash, verdict, check statuses} | `test_scam_shield_stores_and_logs_nothing_pasted` (scans every table and the logs for the pasted text) | ⚠️ true in code, not proven | ✅ |
| Extension fills forms and never clicks Submit | `extension/content.js` | `test_extension_never_submits_a_form` | ⚠️ not tested | ✅ |
| One-click apply only after the target ATS score is reached and the student confirms | `services/applications.check_target` in Dispatch + the mandate | `test_research_and_apply.py`, `test_v7…` | ✅ | ✅ |
| Proof page: off by default, GitHub verified, Codeforces from the API, unverified items labelled | `services/evidence.py`, consent `public_proof` | `test_v2.py`, `test_proof_links.py` | ✅ | ✅ (the PII scan of the rendered page is still to add) |
| Campus: officers see totals unless the student shares more; enforced in the database; every view logged | RLS policies, `audit_events` | `test_campus_v2.py`, `test_v7_placement_portal.py` | ✅ | ✅ |
| Anonymous ledger: figures only with ≥ 3 students | `api/routes/ledger.py` `K_MIN = 3` | `test_v2.py` | ⚠️ no protection against differencing | ⚠️ (§7) |
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
| Resume PDFs | restructure, ATS | ⚠️ hidden-text detection for keyword stuffing is still to add (§7) |
| Forwarded alert emails | link extraction only, no model | stored as links, boards never fetched |
| GitHub READMEs | not sent to a model | proof page shows metadata only |
| Interview answers | interview scoring prompts | ⚠️ not yet fenced (§7) |

## 5. Non-determinism: is each score computed by code?

| Score shown to students | Computed by | Same input, 5 runs |
|---|---|---|
| ATS score | code (`services/ats.py`) | identical by construction |
| Interview hire band | code from attribute scores (`interview_panel.verdict`) | identical given the same attribute scores |
| Match % | code blend: 25% semantic + 25% skills + 50% AI fit | **before:** AI fit 82, 87, 86, 78, 83 (σ 3.2, so match % moved by up to 4.5 points) · temperature 0 tried: 70, 83, 68, 82, one failure (σ 6.8, worse: Groq's reasoning models don't sample deterministically) · **now:** the AI fit review is cached by a hash of model + prompt + schema, so 5 runs give one identical score (`test_ai_scored_features_repeat_exactly_for_the_same_input`) |
| Verifier verdict | rules in code; AI second opinion only for doubtful posts | rules identical; the second opinion isn't cached yet (§7) |
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

## 7. Still to do (later steps of the plan)

- **Evals:** golden datasets (`evals/datasets/*.jsonl`), LLM-judge calibration, the CI eval gate and the red-team suite. None of the Phase 4 metric targets (VERIFIED precision ≥ 99%, scam recall ≥ 95%, κ ≥ 0.6, transcription WER) have been measured yet. Building them needs labelled data: synthetic, or with consent.
- **Verifier:** RDAP domain age and homoglyph checks applied to job postings (Scam Shield has them); a cached second opinion.
- **Matcher:** per-requirement MET/PARTIAL/NOT_MET with resume spans, and a score fully computed in code.
- **Inputs:** hidden-text detection in resume PDFs; fencing interview answers.
- **Ledger:** suppression against differencing.
- **Prompts:** versioned prompt files (`prompts/<feature>/vN.md`) with the model ID and prompt version logged per call.
- **Approvals UX:** the full card (match table with resume quotes, every Verifier check with its evidence, risk flags).
- **Admin:** an `/admin/quality` dashboard.
- **Decisions for you:**
  - The 30-minute approval expiry can make a draft approved early in a long review session need approving again. It's configurable (`APPROVAL_GRANT_TTL_MIN`).
  - Hunter contacts now need a `valid` verification. That will leave some companies with only the address on the posting.

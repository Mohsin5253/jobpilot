# Personal data breach response runbook

India's DPDP Act, 2023 and the DPDP Rules, 2025 require a Data Fiduciary to inform the **Data Protection Board of
India** and **each affected user** of a personal data breach. The Rules set a detailed report to the Board within
**72 hours** of becoming aware of it. This runbook is the order of work. The on-call owner is the Grievance Officer
named on `/trust` until a team exists.

## 0. What counts

Any unauthorised access to, or disclosure, change, loss or destruction of, personal data. Examples: a leaked
`ENCRYPTION_KEY` or `JWT_SECRET`, a database dump outside Render, a bug that shows one user's matches or drafts to
another, a compromised admin account, or a leaked Google OAuth client secret.

## 1. Contain (first hour)

| Leaked or suspected | Do now |
|---|---|
| `JWT_SECRET` | Change it on Render. Every session is signed out. |
| `ENCRYPTION_KEY` | Rotate it, then delete all `mail_accounts` rows (`DELETE FROM mail_accounts;`) so no stored credential can be decrypted, and ask users to reconnect. For Gmail OAuth, also reset the client secret in Google Cloud: that invalidates every refresh token. |
| `GOOGLE_CLIENT_SECRET` | Reset it in Google Cloud Console → Credentials and update Render. |
| Database credentials | Rotate in Render (Database → Credentials). Check the access logs. |
| A code bug exposing data | Roll back the deploy in Render or Vercel, then fix. |
| An admin account | Remove it from `ADMIN_EMAILS`, run "sign out everywhere" for it, reset its password. |

Write down the times as you go: when you became aware, what you did, and when you did it.

## 2. Assess (first 24 hours)

- Which data: account emails, resumes, drafts, mailbox tokens, phone numbers (WhatsApp), consent records?
- Whose: a list of affected `users.id` values. Never copy their personal data into tickets or chat.
- Since when: Render logs, Sentry and `api.request` logs. The logs carry no personal data by design.
- Likely consequences for users: phishing, account misuse, a sent email they didn't approve.

## 3. Notify

1. **Data Protection Board**: give an initial intimation without delay. Within **72 hours**, send the detailed
   report: nature, extent, timing and location of the breach, likely impact, the mitigation, the findings about the
   cause, and the user notifications made. Use the Board's official channel as published at the time.
2. **Each affected user**, in plain language, by email (system SMTP) and an in-app notification. Tell them what
   happened, when, what data, the likely consequences, what we've done, what they should do (for example, revoke
   JobPilot at myaccount.google.com/permissions or change a reused password), and the Grievance Officer's contact.
3. Gmail OAuth incidents: check Google's API Services terms for any duty to tell Google as well.

## 4. Recover and learn

- Fix the root cause, add a test that would have caught it, and deploy.
- Within 2 weeks, write a blameless postmortem in `docs/incidents/` (no personal data in it).
- Keep the record of the breach and the actions taken for at least one year.

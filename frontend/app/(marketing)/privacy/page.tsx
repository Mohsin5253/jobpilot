import { CONTACT_EMAIL, LegalPage } from "@/components/legal";

export const metadata = { title: "Privacy" };

export default function PrivacyPage() {
  return (
    <LegalPage title="Privacy policy" updated="4 November 2026">
      <section>
        <p>
          JobPilot helps you find internships and entry-level jobs and prepare applications. This policy explains what we collect, why,
          and the choices you have. It is written to meet India’s Digital Personal Data Protection Act, 2023 and similar laws.
        </p>
      </section>
      <section>
        <h2>What we collect</h2>
        <ul>
          <li>Your account: name, email address and a hashed password.</li>
          <li>Your resume and anything you add to it in the Skill check, plus your search preferences.</li>
          <li>What the agents produce for you: job matches, tailored resumes, drafts, and your application tracker.</li>
          <li>If you connect your mailbox: its server, address and an app password, stored encrypted and used only to send what you approve.</li>
          <li>Basic usage records (sign-in times, runs, AI usage) to keep the service working, fair and secure.</li>
        </ul>
      </section>
      <section>
        <h2>How we use it</h2>
        <ul>
          <li>To find jobs that fit you, score them, tailor your resume and draft outreach. That’s the whole product.</li>
          <li>To send an application only when you approve it, from your own mailbox.</li>
          <li>To send you service emails you asked for (password resets, new-match alerts).</li>
        </ul>
        <p className="mt-2">We don’t sell your data and we don’t use your resume to train AI models.</p>
      </section>
      <section>
        <h2>Who processes it for us</h2>
        <ul>
          <li>Hosting and database providers that run the service.</li>
          <li>An AI model provider (currently Groq), which processes your resume and job descriptions through its API to score fit and write drafts.</li>
          <li>Job and company-contact APIs. These receive search terms and company names, never your resume.</li>
          <li>Optional error monitoring, configured so it does not receive personal data.</li>
        </ul>
      </section>
      <section>
        <h2>How long we keep it</h2>
        <p>
          While your account is open. AI usage records are kept for 90 days and notifications for 60. Demo accounts are deleted after 24
          hours. When you delete your account, everything in it is deleted.
        </p>
      </section>
      <section>
        <h2>Your rights</h2>
        <ul>
          <li>Access and portability: download everything with <b>Settings → Your data → Export</b>.</li>
          <li>Correction: edit your resume and preferences in Settings at any time.</li>
          <li>Erasure: <b>Settings → Your data → Delete account</b> removes all of it right away.</li>
          <li>Questions or complaints: email {CONTACT_EMAIL}.</li>
        </ul>
      </section>
      <section>
        <h2>Security</h2>
        <p>
          Traffic is encrypted (HTTPS), passwords are hashed with bcrypt, mail passwords are encrypted at rest, sign-in attempts are
          rate-limited, and you can sign out of every device at once.
        </p>
      </section>
    </LegalPage>
  );
}

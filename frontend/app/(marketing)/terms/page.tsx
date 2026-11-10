import { CONTACT_EMAIL, LegalPage } from "@/components/legal";

export const metadata = { title: "Terms" };

export default function TermsPage() {
  return (
    <LegalPage title="Terms of service" updated="4 November 2026">
      <section>
        <h2>The service</h2>
        <p>
          JobPilot finds publicly listed jobs, estimates how well they fit you, and prepares tailored resumes and messages. It does not
          apply or send anything on its own: you review and approve every application.
        </p>
      </section>
      <section>
        <h2>Your responsibilities</h2>
        <ul>
          <li>Keep what you upload truthful. The agents only rephrase your resume, and you’re responsible for what you send.</li>
          <li>Use it for your own job search. No bulk messaging, spam, or contacting people who have asked not to be contacted.</li>
          <li>Keep your password safe, and connect only a mailbox you own.</li>
        </ul>
      </section>
      <section>
        <h2>Jobs and contacts</h2>
        <p>
          Listings come from company career boards and third-party job APIs, and contacts from public sources. We filter for scams and
          closed listings, but we can’t guarantee every posting, fit score or contact is accurate, or that you’ll get a reply or an offer.
          Always check a job on the employer’s own site before sharing personal documents, and never pay to apply.
        </p>
      </section>
      <section>
        <h2>Plans</h2>
        <p>
          The Free plan has daily limits. Pro raises them; during the beta it’s free on request. We’ll give notice before any paid plan
          starts, and you can stay on Free.
        </p>
      </section>
      <section>
        <h2>Ending your account</h2>
        <p>
          You can delete your account any time in Settings. We may suspend accounts that abuse the service or other people. We provide
          the service as is, and our liability is limited to the amount you paid us in the last 12 months.
        </p>
      </section>
      <section>
        <h2>Contact</h2>
        <p>{CONTACT_EMAIL}</p>
      </section>
    </LegalPage>
  );
}

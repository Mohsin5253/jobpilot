import type { ReactNode } from "react";

export const CONTACT_EMAIL = "privacy@jobpilot.app"; // replace with your real contact address before launch

export function LegalPage({ title, updated, children }: { title: string; updated: string; children: ReactNode }) {
  return (
    <article className="mx-auto max-w-3xl px-4 py-16 sm:px-6">
      <h1 className="text-3xl font-semibold tracking-tight">{title}</h1>
      <p className="mt-2 text-[13px] text-subtle">Last updated {updated}</p>
      <div className="mt-10 space-y-8 text-[15px] leading-relaxed text-muted [&_h2]:mb-2 [&_h2]:text-[17px] [&_h2]:font-semibold [&_h2]:text-fg [&_li]:ml-5 [&_li]:list-disc [&_ul]:space-y-1.5">
        {children}
      </div>
    </article>
  );
}

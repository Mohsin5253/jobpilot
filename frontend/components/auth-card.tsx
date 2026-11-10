import Link from "next/link";
import type { ReactNode } from "react";

import { Logo } from "@/components/logo";

/** The sign-in canvas: graphite, a faint grid and one cobalt glow behind the content. */
export function AuthCanvas({ children }: { children: ReactNode }) {
  return (
    <div className="relative isolate flex min-h-dvh flex-col overflow-hidden bg-bg">
      <div aria-hidden className="grid-canvas pointer-events-none absolute inset-0 -z-10 opacity-60 [mask-image:radial-gradient(ellipse_at_center,#000,transparent_72%)]" />
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10" style={{ background: "radial-gradient(640px 420px at 50% 38%, color-mix(in oklab, var(--cobalt) 14%, transparent), transparent 70%)" }} />
      <header className="mx-auto flex h-16 w-full max-w-[1100px] items-center px-4 md:px-6">
        <Link href="/" className="flex min-h-11 items-center gap-2.5">
          <Logo size={26} />
          <span className="text-[16px] font-semibold tracking-[-0.02em]">JobPilot</span>
        </Link>
      </header>
      <main className="grid flex-1 place-items-center px-4 pt-4 pb-12">{children}</main>
    </div>
  );
}

/** Small centered card for the secondary sign-in flows (forgot / reset password). */
export function AuthCard({ title, description, children }: { title: string; description?: ReactNode; children: ReactNode }) {
  return (
    <AuthCanvas>
      <div className="w-full max-w-sm">
        <div className="panel p-6">
          <h1 className="text-[20px] font-semibold tracking-[-0.02em]">{title}</h1>
          {description && <p className="mt-1.5 text-[13.5px] text-text-2">{description}</p>}
          <div className="mt-6">{children}</div>
        </div>
        <p className="mt-6 text-center text-[14px] text-text-2">
          <Link href="/login" className="inline-flex min-h-11 items-center font-medium text-cobalt-text hover:underline">
            Back to sign in
          </Link>
        </p>
      </div>
    </AuthCanvas>
  );
}

"use client";

import * as D from "@radix-ui/react-dialog";
import { ArrowRight, Menu, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Logo } from "@/components/logo";
import { buttonClass } from "@/components/ui/button";

const LINKS = [
  { href: "/#safety", label: "Safety" },
  { href: "/#crew", label: "Crew" },
  { href: "/#how", label: "How it works" },
  { href: "/#pricing", label: "Pricing" },
  { href: "/#campus", label: "Campus" },
  { href: "/trust", label: "Trust" },
];

/** Sticky marketing nav. Phones get a full-screen menu sheet. */
export function SiteHeader() {
  const [open, setOpen] = useState(false);
  return (
    <header className="sticky top-0 z-40 border-b border-border bg-bg/75 backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-[1200px] items-center gap-8 px-4 md:px-6">
        <Link href="/" aria-label="JobPilot, home" className="flex min-h-11 items-center gap-2.5 rounded-[var(--radius-control)]">
          <Logo size={28} />
          <span className="text-[17px] font-semibold tracking-[-0.02em]">JobPilot</span>
        </Link>
        <nav aria-label="Main" className="hidden items-center gap-1 text-[14px] text-text-2 lg:flex">
          {LINKS.map((l) => (
            <Link key={l.href} href={l.href} className="rounded-[var(--radius-control)] px-3 py-1.5 transition-colors hover:bg-elevated hover:text-text">
              {l.label}
            </Link>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <Link href="/login" className="hidden rounded-[var(--radius-control)] px-3 py-1.5 text-[14px] text-text-2 hover:text-text sm:block">
            Sign in
          </Link>
          <Link href="/register" className={buttonClass({ variant: "primary", className: "hidden sm:inline-flex" })}>
            Get started <ArrowRight />
          </Link>
          <D.Root open={open} onOpenChange={setOpen}>
            <D.Trigger asChild>
              <button type="button" aria-label="Open menu" className="grid size-11 place-items-center rounded-[var(--radius-control)] text-text-2 hover:bg-elevated hover:text-text lg:hidden">
                <Menu className="size-5" />
              </button>
            </D.Trigger>
            <D.Portal>
              <D.Content className="fixed inset-0 z-[90] flex flex-col bg-bg outline-none data-[state=open]:animate-[fade-in_var(--dur-base)_var(--ease)]">
                <D.Title className="sr-only">Menu</D.Title>
                <D.Description className="sr-only">Site navigation</D.Description>
                <div className="flex h-16 shrink-0 items-center justify-between border-b border-border px-4">
                  <Link href="/" onClick={() => setOpen(false)} className="flex min-h-11 items-center gap-2.5">
                    <Logo size={28} />
                    <span className="text-[17px] font-semibold tracking-[-0.02em]">JobPilot</span>
                  </Link>
                  <D.Close aria-label="Close menu" className="grid size-11 place-items-center rounded-[var(--radius-control)] text-text-2 hover:bg-elevated hover:text-text">
                    <X className="size-5" />
                  </D.Close>
                </div>
                <nav aria-label="Main" className="flex-1 overflow-y-auto px-2 py-4">
                  {LINKS.map((l) => (
                    <Link key={l.href} href={l.href} onClick={() => setOpen(false)} className="flex h-14 items-center rounded-[var(--radius-control)] px-4 text-[20px] font-medium tracking-[-0.01em] hover:bg-elevated">
                      {l.label}
                    </Link>
                  ))}
                </nav>
                <div className="grid shrink-0 gap-2 border-t border-border p-4 pb-[calc(16px+env(safe-area-inset-bottom))]">
                  <Link href="/register" onClick={() => setOpen(false)} className={buttonClass({ variant: "primary", size: "lg", className: "w-full" })}>
                    Get started <ArrowRight />
                  </Link>
                  <Link href="/login" onClick={() => setOpen(false)} className={buttonClass({ variant: "secondary", size: "lg", className: "w-full" })}>
                    Sign in
                  </Link>
                </div>
              </D.Content>
            </D.Portal>
          </D.Root>
        </div>
      </div>
    </header>
  );
}

const FOOTER = [
  { title: "Product", links: LINKS.slice(0, 5) },
  {
    title: "Account",
    links: [
      { href: "/register", label: "Create an account" },
      { href: "/login", label: "Sign in" },
    ],
  },
  {
    title: "Legal",
    links: [
      { href: "/trust", label: "Trust" },
      { href: "/privacy", label: "Privacy" },
      { href: "/terms", label: "Terms" },
    ],
  },
];

export function SiteFooter() {
  return (
    <footer className="border-t border-border">
      <div className="mx-auto grid max-w-[1200px] gap-10 px-4 py-12 md:grid-cols-[1.4fr_repeat(3,1fr)] md:px-6">
        <div>
          <div className="flex items-center gap-2.5">
            <Logo size={24} />
            <span className="text-[16px] font-semibold tracking-[-0.02em]">JobPilot</span>
          </div>
          <p className="mt-3 max-w-xs text-[13.5px] leading-relaxed text-text-2">Real internships. Zero scams. Every application approved by you.</p>
        </div>
        {FOOTER.map((col) => (
          <nav key={col.title} aria-label={col.title}>
            <div className="eyebrow mb-3">{col.title}</div>
            <ul className="space-y-1">
              {col.links.map((l) => (
                <li key={l.href}>
                  <Link href={l.href} className="inline-flex min-h-9 items-center text-[13.5px] text-text-2 hover:text-text">
                    {l.label}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        ))}
      </div>
      <div className="border-t border-border">
        <div className="mx-auto flex max-w-[1200px] flex-wrap justify-between gap-2 px-4 py-5 text-[12.5px] text-text-3 md:px-6">
          <span>© {new Date().getFullYear()} JobPilot · Beta</span>
          <span>Never automates LinkedIn · Real, public contacts only</span>
        </div>
      </div>
    </footer>
  );
}

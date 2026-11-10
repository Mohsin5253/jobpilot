import type { Metadata } from "next";

import { ScamChecker } from "@/components/scam-checker";

export const metadata: Metadata = {
  title: "Check an internship offer for scams",
  description: "Paste a WhatsApp, Telegram or email offer, a link, or an offer letter. Free, no sign-in, and nothing you paste is stored.",
  alternates: { canonical: "/scam-check" },
};

export default function ScamCheckPage() {
  return (
    <div className="mx-auto max-w-3xl px-4 py-12 sm:px-6 md:py-16">
      <div className="eyebrow mb-3">Scam Shield · free</div>
      <h1 className="font-display text-[clamp(34px,6vw,52px)] leading-[1.04]">Is this internship offer real?</h1>
      <p className="mt-4 text-[16px] leading-relaxed text-text-2">
        Paste the message you got on WhatsApp, Telegram or email, add the link, or upload the offer letter. We check it for fee demands, UPI IDs, lookalike company
        websites, fake government schemes, OTP requests and more, in English, Hindi and Marathi. No sign-in, and nothing you paste is stored.
      </p>
      <ScamChecker />
    </div>
  );
}

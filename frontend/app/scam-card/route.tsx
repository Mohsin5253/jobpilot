import { ImageResponse } from "next/og";

// The WhatsApp share card: the verdict, the score and the kinds of red flag, never anything from the message itself.
const LABELS: Record<string, string> = {
  fee: "Asks for a fee or deposit",
  upi: "Gives a UPI ID or QR code",
  free_mail: "Personal email for a company",
  lookalike: "Lookalike company website",
  no_interview: "Selected without an interview",
  stipend: "Too-good-to-be-true pay",
  urgency: "Pressure to act fast",
  ids: "Asks for OTP, PIN or ID documents",
  chat_only: "WhatsApp or Telegram only",
  task: "Paid likes or reviews (task scam)",
  gov: "Fake government internship",
  llm: "AI review flagged it",
};
const COLOR: Record<string, string> = { "Likely scam": "#ef4444", Suspicious: "#f59e0b", "Likely safe": "#22c55e" };

export function GET(req: Request) {
  const q = new URL(req.url).searchParams;
  const verdict = COLOR[q.get("v") ?? ""] ? (q.get("v") as string) : "Suspicious";
  const score = Math.max(0, Math.min(100, Number(q.get("s")) || 0));
  const reasons = (q.get("r") ?? "").split(",").map((r) => LABELS[r]).filter(Boolean).slice(0, 3);
  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column", background: "#0a0b0d", color: "#f4f4f5", padding: 64, fontFamily: "sans-serif" }}>
        <div style={{ fontSize: 28, color: "#8b9cff" }}>JobPilot Scam Shield</div>
        <div style={{ fontSize: 88, fontWeight: 700, color: COLOR[verdict], marginTop: 24 }}>{verdict}</div>
        <div style={{ fontSize: 32, color: "#a1a1aa", marginTop: 8 }}>{`Risk score ${score}/100`}</div>
        <div style={{ display: "flex", flexDirection: "column", marginTop: 32 }}>
          {reasons.map((r) => (
            <div key={r} style={{ fontSize: 32, marginTop: 10 }}>{`• ${r}`}</div>
          ))}
        </div>
        <div style={{ marginTop: "auto", fontSize: 28, color: "#d4d4d8" }}>Never pay to get an internship. Report scams: cybercrime.gov.in · 1930</div>
      </div>
    ),
    { width: 1200, height: 630 },
  );
}

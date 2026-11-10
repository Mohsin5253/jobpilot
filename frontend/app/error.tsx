"use client";

import { RotateCcw } from "lucide-react";
import { useEffect } from "react";

import { AgentHero } from "@/components/agents/agent-avatar";
import { AuthCanvas } from "@/components/auth-card";
import { Button, buttonClass } from "@/components/ui/button";

/** Error boundary: Pilot owns up and offers the retry. */
export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);
  return (
    <AuthCanvas>
      <div className="flex max-w-md flex-col items-center text-center">
        <AgentHero agent="pilot" status="error" size={180} />
        <h1 className="font-display mt-8 text-[clamp(26px,4vw,36px)] leading-tight">Something broke on our side.</h1>
        <p className="mt-2 text-[15px] text-text-2">Sorry about that. Your data is safe. Retry?</p>
        {error.digest && <p className="num mt-2 text-[12px] text-text-3">ref {error.digest}</p>}
        <div className="mt-6 flex flex-col gap-2 sm:flex-row">
          <Button variant="primary" size="lg" onClick={reset}>
            <RotateCcw /> Try again
          </Button>
          <a href="/dashboard" className={buttonClass({ variant: "ghost", size: "lg" })}>
            Go to the dashboard
          </a>
        </div>
      </div>
    </AuthCanvas>
  );
}

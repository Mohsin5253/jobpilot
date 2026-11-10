import Link from "next/link";

import { AgentHero } from "@/components/agents/agent-avatar";
import { AuthCanvas } from "@/components/auth-card";
import { buttonClass } from "@/components/ui/button";

/** 404: Scout, binoculars in hand, couldn't find it either. */
export default function NotFound() {
  return (
    <AuthCanvas>
      <div className="flex max-w-md flex-col items-center text-center">
        <AgentHero agent="scout" size={180} />
        <div className="num mt-8 text-[13px] text-text-3">404</div>
        <h1 className="font-display mt-2 text-[clamp(26px,4vw,36px)] leading-tight">Couldn’t find this page.</h1>
        <p className="mt-2 text-[15px] text-text-2">Scout looked everywhere. The link may be old, or the page has moved.</p>
        <div className="mt-6 flex flex-col gap-2 sm:flex-row">
          <Link href="/dashboard" className={buttonClass({ variant: "primary", size: "lg" })}>
            Go to the dashboard
          </Link>
          <Link href="/" className={buttonClass({ variant: "ghost", size: "lg" })}>
            Home page
          </Link>
        </div>
      </div>
    </AuthCanvas>
  );
}

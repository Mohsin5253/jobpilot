import type { ReactNode } from "react";

import { PortalNav } from "@/components/campus/portal";

/** The Campus portal: approved college staff only (the middleware and the API both check). */
export default function CampusPortalLayout({ children }: { children: ReactNode }) {
  return (
    <div className="space-y-6">
      <PortalNav />
      {children}
    </div>
  );
}

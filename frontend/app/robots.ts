import type { MetadataRoute } from "next";

import { SITE_URL } from "@/lib/site";

export default function robots(): MetadataRoute.Robots {
  // Public marketing pages only; the app, the API and proof pages (noindex) stay out of search.
  return {
    rules: { userAgent: "*", allow: ["/", "/scam-check", "/trust", "/transparency", "/privacy", "/terms"], disallow: ["/api/", "/p/", "/dashboard", "/settings"] },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}

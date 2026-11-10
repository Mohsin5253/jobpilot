/**
 * The site's public origin, for canonical URLs, Open Graph and the sitemap. Set NEXT_PUBLIC_SITE_URL when you add a
 * custom domain; otherwise Vercel's production domain is used (it's your custom domain once one is primary).
 */
const vercel = process.env.VERCEL_PROJECT_PRODUCTION_URL;
export const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL?.trim() || (vercel ? `https://${vercel}` : "http://localhost:3000")).replace(/\/+$/, "");

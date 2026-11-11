import type { NextConfig } from "next";

// The API's origin only. A trailing "/" or "/api" (an easy mistake in the Vercel dashboard) would send
// requests to //api/... or /api/api/..., which the API answers with 404, so both are dropped.
const API_URL = (process.env.API_URL?.trim() || "http://localhost:8000").replace(/\/+$/, "").replace(/\/api$/, "");
const PROD = process.env.NODE_ENV === "production";

// Same-origin everything (the API is proxied under /api). 'unsafe-inline' covers the pre-paint theme
// script and Next's inline bootstrap; dev also needs 'unsafe-eval' for fast refresh.
const CSP = [
  "default-src 'self'",
  // blob:, jsDelivr and wasm-unsafe-eval are for the mock-interview code runner (lib/code-runner.ts): candidate code
  // runs in a Web Worker inside an opaque-origin sandboxed frame, and Python runs on Pyodide (WebAssembly).
  `script-src 'self' 'unsafe-inline' blob: https://cdn.jsdelivr.net 'wasm-unsafe-eval'${PROD ? "" : " 'unsafe-eval'"}`,
  "worker-src 'self' blob:",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  "connect-src 'self' https://cdn.jsdelivr.net",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  // Crew artwork ships as 1024px WebP; next/image serves AVIF/WebP at the displayed size.
  images: { formats: ["image/avif", "image/webp"], deviceSizes: [640, 828, 1080, 1280, 1920], imageSizes: [24, 32, 40, 64, 96, 128, 200, 256, 384, 480] },
  eslint: { ignoreDuringBuilds: true },
  // The browser only ever talks to this origin; /api is proxied to FastAPI so the session
  // cookie is first-party (no cross-site cookies between Vercel and Render).
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/api/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          // The microphone is for spoken answers in mock interviews (this site only; nothing is recorded or uploaded).
          { key: "Permissions-Policy", value: "camera=(), microphone=(self), geolocation=()" },
          { key: "Content-Security-Policy", value: CSP },
          ...(PROD ? [{ key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains; preload" }] : []),
        ],
      },
    ];
  },
};

export default nextConfig;

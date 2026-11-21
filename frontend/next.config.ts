import type { NextConfig } from "next";

// Security headers for every response; the per-request CSP with a nonce is set in src/proxy.ts (blueprint 17.3).
const config: NextConfig = {
  // Lets a verification build run beside a live one (tools use NEXT_DIST_DIR); the default is .next.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  poweredByHeader: false,
  reactStrictMode: true,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
};

export default config;

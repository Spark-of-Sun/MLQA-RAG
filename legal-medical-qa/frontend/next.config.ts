import type { NextConfig } from "next";

// The nonce-based CSP is set per request in src/proxy.ts. A per-request nonce forces dynamic rendering,
// so static generation of HTML is not available (accepted: doc 17.3, DEF-61); static assets stay cacheable.
const config: NextConfig = {
  output: "standalone", // a container build behind the same ingress as the API (doc 17.3)
  poweredByHeader: false,
  reactStrictMode: true,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
          { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains; preload" },
        ],
      },
      // The SSE stream must never be buffered or compressed by an intermediary (doc 4.8).
      {
        source: "/api/v1/query",
        headers: [
          { key: "Cache-Control", value: "no-store, no-transform" },
          { key: "X-Accel-Buffering", value: "no" },
        ],
      },
    ];
  },
};

export default config;

import type { NextConfig } from "next";

// Security headers for every response; the per-request CSP with a nonce is set in src/proxy.ts (blueprint 17.3).
const config: NextConfig = {
  // Lets a verification build run beside a live one (tools use NEXT_DIST_DIR); the default is .next.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  // A verification build type-checks only its own route types, so stale types in a live build's folder (for example
  // a route that was just removed) cannot fail it.
  ...(process.env.NEXT_DIST_DIR ? { typescript: { tsconfigPath: "tsconfig.verify.json" } } : {}),
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
  // The old single-product "Industries" section became two named products (Cyte Legal QA, Cyte Medical QA). These
  // keep every link and bookmark to the old paths working. Order matters: the specific slugs must be listed before
  // the catch-all, since Next.js redirects in array order and takes the first match.
  async redirects() {
    return [
      { source: "/industries/legal", destination: "/products/legal", permanent: true },
      { source: "/industries/healthcare", destination: "/products/medical", permanent: true },
      { source: "/industries/:slug", destination: "/product", permanent: true },
      { source: "/industries", destination: "/product", permanent: true },
      // The company page moved to /about; /products alone has no page of its own (the index is /product); /legal
      // opens its first document.
      { source: "/company", destination: "/about", permanent: true },
      // The careers page was removed; old links land on /about.
      { source: "/careers", destination: "/about", permanent: false },
      { source: "/products", destination: "/product", permanent: false },
      { source: "/legal", destination: "/legal/privacy", permanent: false },
    ];
  },
};

export default config;

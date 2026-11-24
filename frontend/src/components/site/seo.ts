import type { Metadata } from "next";

import { PRODUCTS } from "@/components/site/products";
import { SOLUTIONS } from "@/components/site/solutions";

/** The site's public origin, for absolute URLs in metadata, the sitemap and robots.txt. */
export const SITE_URL = (process.env.APP_BASE_URL ?? "http://localhost:3000").replace(/\/$/, "");

/** Every public marketing route, for app/sitemap.ts. Docs pages are added there from src/lib/docs.ts. */
export const PUBLIC_ROUTES: string[] = [
  "/",
  "/product",
  ...PRODUCTS.map((p) => `/products/${p.slug}`),
  "/solutions",
  ...SOLUTIONS.map((s) => `/solutions/${s.slug}`),
  "/security",
  "/pricing",
  "/faq",
  "/about",
  "/contact",
  "/docs",
  "/legal/privacy",
  "/legal/terms",
  "/legal/cookies",
];

const OG_IMAGE = { url: "/og-image.png", width: 1200, height: 630, alt: "Cyte by Onekami" };

/**
 * Metadata for one public page: title (the layout's template adds the brand), description, canonical URL and the
 * Open Graph and Twitter cards. Next.js replaces, not merges, a parent's `openGraph`, so the image is set here too.
 */
export function pageMeta(title: string, description: string, path: string): Metadata {
  const full = `${title} · Cyte by Onekami`;
  return {
    title,
    description,
    alternates: { canonical: path },
    openGraph: { type: "website", siteName: "Cyte by Onekami", title: full, description, url: path, images: [OG_IMAGE] },
    twitter: { card: "summary_large_image", title: full, description, images: [OG_IMAGE.url] },
  };
}

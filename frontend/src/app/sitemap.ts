import type { MetadataRoute } from "next";

import { PUBLIC_ROUTES, SITE_URL } from "@/components/site/seo";
import { docsNav } from "@/lib/docs";

// Served at /sitemap.xml: every public marketing page and every docs page (private docs pages show a sign-in wall
// to visitors, so only their titles are indexable).
export default function sitemap(): MetadataRoute.Sitemap {
  const docs = docsNav().flatMap((g) => g.items.map((i) => `/docs/${i.slug}`));
  return [...PUBLIC_ROUTES, ...docs].map((path) => ({
    url: `${SITE_URL}${path === "/" ? "" : path}`,
    changeFrequency: "monthly",
    priority: path === "/" ? 1 : path.startsWith("/docs/") || path.startsWith("/legal/") ? 0.4 : 0.8,
  }));
}

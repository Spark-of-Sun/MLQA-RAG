import type { MetadataRoute } from "next";

import { SITE_URL } from "@/components/site/seo";

// Served at /robots.txt. The public website and docs are open to crawlers; the signed-in app and auth routes are not.
export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      disallow: [
        "/auth/",
        "/api/",
        "/home",
        "/chat",
        "/library",
        "/audit",
        "/profile",
        "/onboarding",
        "/manage-admins",
        "/org-governance",
        "/governance",
        "/manage-tenants",
        "/matters",
        "/reviews",
      ],
    },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}

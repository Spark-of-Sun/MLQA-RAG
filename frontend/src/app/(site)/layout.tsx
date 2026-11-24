import type { Metadata } from "next";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { SiteShell } from "@/components/site/chrome";
import { SITE_URL } from "@/components/site/seo";
import { auth0 } from "@/lib/auth0";
import { publicSiteEnabled } from "@/lib/backend";
import { BRAND, COMPANY } from "@/lib/format";

// Titles and sharing cards for every public page. Each page sets its own `title` and `description`; the template
// adds the brand. Scoped to the website, so the app's own page titles are unchanged.
export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: { default: `${BRAND} by ${COMPANY}`, template: `%s · ${BRAND} by ${COMPANY}` },
  description: "Verified, cited answers from legal and medical documents.",
  openGraph: {
    type: "website",
    siteName: `${BRAND} by ${COMPANY}`,
    images: [{ url: "/og-image.png", width: 1200, height: 630, alt: `${BRAND} by ${COMPANY}` }],
  },
  twitter: { card: "summary_large_image", images: ["/og-image.png"] },
};

// The public website. No sign-in required; the header only switches its buttons when a session exists. `.site`
// scopes the website's typography and load animations (globals.css).
// Frozen MVP-only feature (DEV-21, pending Q-04): while `public_site` is off every page here, `/` included, sends
// the visitor to sign-in and their home screen instead.
export default async function SiteLayout({ children }: { children: ReactNode }) {
  if (!(await publicSiteEnabled())) redirect("/home");
  const signedIn = Boolean(await auth0.getSession());
  return <SiteShell signedIn={signedIn}>{children}</SiteShell>;
}

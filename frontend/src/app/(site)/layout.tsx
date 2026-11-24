import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { SiteFooter, SiteHeader } from "@/components/site/chrome";
import { Doors } from "@/components/site/blocks";
import { Reveal } from "@/components/site/reveal";
import { auth0 } from "@/lib/auth0";
import { publicSiteEnabled } from "@/lib/backend";

// The public website (home, product, industries, security, pricing, company, contact). No sign-in required; the
// header only switches its buttons when a session exists. `.site` scopes the website's animations (globals.css).
// Frozen MVP-only feature (DEV-21, pending Q-04): while `public_site` is off every page here, `/` included, sends
// the visitor to sign-in and their home screen instead.
export default async function SiteLayout({ children }: { children: ReactNode }) {
  if (!(await publicSiteEnabled())) redirect("/home");
  const signedIn = Boolean(await auth0.getSession());
  return (
    <div className="site atmosphere-grid min-h-full bg-page text-ink-900">
      <Reveal />
      <SiteHeader signedIn={signedIn} />
      <main id="main">
        {children}
        <Doors signedIn={signedIn} />
      </main>
      <SiteFooter />
    </div>
  );
}

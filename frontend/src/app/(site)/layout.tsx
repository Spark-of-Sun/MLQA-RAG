import type { ReactNode } from "react";

import { SiteFooter, SiteHeader } from "@/components/site/chrome";
import { Doors } from "@/components/site/blocks";
import { Reveal } from "@/components/site/reveal";
import { auth0 } from "@/lib/auth0";

// The public website (home, product, industries, security, pricing, company, contact). No sign-in required; the
// header only switches its buttons when a session exists. `.site` scopes the website's animations (globals.css).
export default async function SiteLayout({ children }: { children: ReactNode }) {
  const signedIn = Boolean(await auth0.getSession());
  return (
    <div className="site min-h-full bg-[#fcfcfc] text-ink-900">
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

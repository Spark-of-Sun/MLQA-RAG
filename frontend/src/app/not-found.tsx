import Link from "next/link";

import { NotFoundContent } from "@/components/site/blocks";
import { SiteShell } from "@/components/site/chrome";
import { auth0 } from "@/lib/auth0";
import { publicSiteEnabled } from "@/lib/backend";

// Unknown URLs anywhere (and routes a role may not open). With the public website on, the page uses the site's
// header and footer; with it off, a minimal page that leads to the workspace, as before.
export default async function NotFound() {
  const signedIn = Boolean(await auth0.getSession());
  if (await publicSiteEnabled()) {
    return (
      <SiteShell signedIn={signedIn}>
        <NotFoundContent signedIn={signedIn} />
      </SiteShell>
    );
  }
  return (
    <div className="flex min-h-full flex-col items-center justify-center gap-3 p-8 text-center">
      <p className="text-sm font-medium text-ink-500">404</p>
      <h1 className="text-2xl font-semibold text-ink-950">Page not found</h1>
      <Link href="/home" className="text-sm font-medium text-link hover:underline">
        Go to your workspace
      </Link>
    </div>
  );
}

import type { Metadata } from "next";

import { LegalDoc } from "@/components/site/legal";
import { pageMeta } from "@/components/site/seo";
import { BRAND, CONTACT_EMAIL } from "@/lib/format";
import { THEME_COOKIE } from "@/lib/theme";

export const metadata: Metadata = pageMeta("Cookie notice", `The cookies this website and ${BRAND} use, and why.`, "/legal/cookies");

export default function CookiesPage() {
  return (
    <LegalDoc title="Cookie notice" intro={`The cookies this website and ${BRAND} use. There are no analytics, advertising or tracking cookies, so there is nothing to opt out of.`}>
      <div className="mt-8 overflow-x-auto rounded-xl border border-ink-200 bg-surface">
        <table className="w-full min-w-[36rem] text-left text-sm">
          <caption className="sr-only">Cookies</caption>
          <thead className="border-b border-ink-200 text-ink-500">
            <tr>
              <th scope="col" className="px-5 py-3 font-medium">Cookie</th>
              <th scope="col" className="px-5 py-3 font-medium">Purpose</th>
              <th scope="col" className="px-5 py-3 font-medium">Lasts</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-ink-200 text-ink-800">
            <tr>
              <td className="px-5 py-3 font-mono text-xs">{THEME_COOKIE}</td>
              <td className="px-5 py-3">Remembers whether you chose the light or dark theme.</td>
              <td className="px-5 py-3">1 year</td>
            </tr>
            <tr>
              <td className="px-5 py-3">Sign-in session</td>
              <td className="px-5 py-3">Keeps you signed in. Encrypted; set only when you sign in.</td>
              <td className="px-5 py-3">Ends after 30 minutes without activity, 8 hours at most</td>
            </tr>
            <tr>
              <td className="px-5 py-3">Sign-in transaction</td>
              <td className="px-5 py-3">Protects the sign-in step against forgery while you sign in.</td>
              <td className="px-5 py-3">Minutes</td>
            </tr>
          </tbody>
        </table>
      </div>
      <h2>Strictly necessary</h2>
      <p>
        These cookies are needed for the site to work as you asked (your theme choice, signing in), so they do not need
        consent in most places. You can delete them in your browser at any time; you will be signed out and the theme
        will follow your system setting.
      </p>
      <h2>Contact</h2>
      <p>
        Questions: <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
      </p>
    </LegalDoc>
  );
}

import { ChevronDown, Menu, X } from "lucide-react";
import Link from "next/link";

import { Container } from "@/components/site/blocks";
import { DEMO_MAIL, INDUSTRY_LINKS, NAV, SIGN_IN, SIGN_UP, SUPPORT_MAIL } from "@/components/site/links";
import { CompanyMark, Logo } from "@/components/logo";
import { BRAND, COMPANY, CONTACT_EMAIL, SUPPORT_EMAIL } from "@/lib/format";

// The public site needs no client JavaScript: the Industries menu opens on hover or keyboard focus, and the
// mobile menu is a <details> element.

export function SiteHeader({ signedIn }: { signedIn: boolean }) {
  return (
    <header className="sticky top-0 z-40 border-b border-ink-200/70 bg-[#fcfcfc]/90 backdrop-blur">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:rounded focus:bg-white focus:px-3 focus:py-2">
        Skip to content
      </a>
      <Container className="flex h-16 items-center justify-between gap-6">
        <Link href="/" aria-label={`${BRAND} by ${COMPANY}, home`}>
          <Logo company />
        </Link>
        <nav className="hidden items-center gap-1 lg:flex" aria-label="Site">
          {NAV.map((n) =>
            n.children ? (
              <div key={n.href} className="group relative">
                <Link
                  href={n.href}
                  className="flex items-center gap-1 rounded-full px-3 py-2 text-sm text-ink-600 hover:text-ink-950"
                >
                  {n.label} <ChevronDown className="size-3.5 transition-transform group-hover:rotate-180" aria-hidden />
                </Link>
                <div className="invisible absolute top-full left-0 pt-2 opacity-0 transition group-focus-within:visible group-focus-within:opacity-100 group-hover:visible group-hover:opacity-100">
                  <div className="w-80 rounded-2xl border border-ink-200 bg-white p-2 shadow-xl shadow-ink-900/5">
                    {n.children.map((c) => (
                      <Link key={c.href} href={c.href} className="block rounded-xl px-4 py-3 hover:bg-ink-50">
                        <span className="block text-sm font-medium text-ink-950">{c.label}</span>
                        <span className="block text-xs text-ink-500">{c.body}</span>
                      </Link>
                    ))}
                    <Link href={n.href} className="block rounded-xl px-4 py-2 text-xs font-medium text-ink-600 hover:bg-ink-50">
                      All industries →
                    </Link>
                  </div>
                </div>
              </div>
            ) : (
              <Link key={n.href} href={n.href} className="rounded-full px-3 py-2 text-sm text-ink-600 hover:text-ink-950">
                {n.label}
              </Link>
            ),
          )}
        </nav>
        <div className="hidden items-center gap-2 lg:flex">
          <HeaderActions signedIn={signedIn} />
        </div>
        <details className="group relative lg:hidden">
          <summary className="flex cursor-pointer list-none items-center rounded-full p-2 text-ink-700 hover:bg-ink-100 [&::-webkit-details-marker]:hidden">
            <Menu className="size-5 group-open:hidden" aria-hidden />
            <X className="hidden size-5 group-open:block" aria-hidden />
            <span className="sr-only">Menu</span>
          </summary>
          <div className="absolute right-0 mt-2 w-72 rounded-2xl border border-ink-200 bg-white p-2 shadow-xl">
            {NAV.map((n) => (
              <div key={n.href}>
                <Link href={n.href} className="block rounded-xl px-4 py-2.5 text-sm font-medium text-ink-900 hover:bg-ink-50">
                  {n.label}
                </Link>
                {n.children?.map((c) => (
                  <Link key={c.href} href={c.href} className="block rounded-xl py-2 pr-4 pl-8 text-sm text-ink-600 hover:bg-ink-50">
                    {c.label}
                  </Link>
                ))}
              </div>
            ))}
            <div className="mt-2 flex flex-col gap-2 border-t border-ink-100 p-2">
              <HeaderActions signedIn={signedIn} />
            </div>
          </div>
        </details>
      </Container>
    </header>
  );
}

function HeaderActions({ signedIn }: { signedIn: boolean }) {
  if (signedIn) {
    return (
      <a href="/home" className="rounded-full bg-ink-950 px-4 py-2 text-center text-sm font-medium text-white hover:bg-ink-800">
        Open workspace
      </a>
    );
  }
  return (
    <>
      <a href={SIGN_IN} className="rounded-full px-4 py-2 text-center text-sm font-medium text-ink-700 hover:bg-ink-100">
        Sign in
      </a>
      <Link href="/contact" className="rounded-full border border-ink-300 px-4 py-2 text-center text-sm font-medium text-ink-900 hover:bg-ink-50">
        Talk to us
      </Link>
      <a href={SIGN_UP} className="rounded-full bg-ink-950 px-4 py-2 text-center text-sm font-medium text-white hover:bg-ink-800">
        Get started
      </a>
    </>
  );
}

const FOOTER: { title: string; links: { href: string; label: string }[] }[] = [
  {
    title: "Product",
    links: [
      { href: "/product", label: `${BRAND} overview` },
      { href: "/product#verification", label: "How answers are checked" },
      { href: "/product#teams", label: "Teams and roles" },
      { href: "/pricing", label: "Pricing" },
    ],
  },
  {
    title: "Industries",
    links: [...INDUSTRY_LINKS.map(({ href, label }) => ({ href, label })), { href: "/industries", label: "All industries" }],
  },
  {
    title: "Get started",
    links: [
      { href: SIGN_UP, label: "Create an organization" },
      { href: SIGN_IN, label: "Sign in" },
      { href: SIGN_IN, label: "Join with an invite code" },
      { href: DEMO_MAIL, label: "Book a demo" },
    ],
  },
  {
    title: "Company",
    links: [
      { href: "/company", label: `About ${COMPANY}` },
      { href: "/security", label: "Security" },
      { href: "/contact", label: "Contact" },
      { href: SUPPORT_MAIL, label: "Support" },
    ],
  },
];

export function SiteFooter() {
  const year = new Date().getFullYear();
  return (
    <footer className="bg-[#fcfcfc]">
      <Container className="grid gap-12 py-16 md:grid-cols-[1.3fr_repeat(4,1fr)]">
        <div>
          <CompanyMark className="h-9" />
          <p className="mt-5 max-w-xs text-sm leading-6 text-ink-600">
            {COMPANY} builds software for professionals who have to stand behind every answer. {BRAND} is our answer engine
            for legal and clinical documents.
          </p>
          <dl className="mt-6 space-y-1 text-sm">
            <div>
              <dt className="inline text-ink-500">Sales </dt>
              <dd className="inline">
                <a href={DEMO_MAIL} className="text-ink-900 hover:underline">
                  {CONTACT_EMAIL}
                </a>
              </dd>
            </div>
            <div>
              <dt className="inline text-ink-500">Support </dt>
              <dd className="inline">
                <a href={SUPPORT_MAIL} className="text-ink-900 hover:underline">
                  {SUPPORT_EMAIL}
                </a>
              </dd>
            </div>
          </dl>
        </div>
        {FOOTER.map((col) => (
          <nav key={col.title} aria-label={col.title}>
            <h2 className="font-mono text-xs tracking-wider text-ink-500 uppercase">{col.title}</h2>
            <ul className="mt-4 space-y-2.5">
              {col.links.map((l) => (
                <li key={l.label}>
                  {l.href.startsWith("/auth/") || l.href.startsWith("mailto:") ? (
                    <a href={l.href} className="text-sm text-ink-700 hover:text-ink-950">
                      {l.label}
                    </a>
                  ) : (
                    <Link href={l.href} className="text-sm text-ink-700 hover:text-ink-950">
                      {l.label}
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          </nav>
        ))}
      </Container>
      <div className="border-t border-ink-200/70">
        <Container className="flex flex-col gap-2 py-6 text-xs text-ink-500 sm:flex-row sm:items-center sm:justify-between">
          <p>
            © {year} {COMPANY}. All rights reserved. {BRAND} is a product of {COMPANY}.
          </p>
          <p>{BRAND} reports what your documents say. It does not give legal or medical advice.</p>
        </Container>
      </div>
    </footer>
  );
}

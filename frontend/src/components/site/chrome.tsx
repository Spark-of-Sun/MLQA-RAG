import { ArrowRight, ChevronDown, Menu, X } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { Container, CtaBand } from "@/components/site/blocks";
import { DEMO_MAIL, FOOTER, isExternal, NAV, SIGN_IN, SUPPORT_MAIL, type NavLink } from "@/components/site/links";
import { CompanyMark, Logo } from "@/components/logo";
import { ThemeSwitch } from "@/components/theme-switch";
import { BRAND, COMPANY, CONTACT_EMAIL, SUPPORT_EMAIL } from "@/lib/format";

// The public site's header and footer. No client JavaScript beyond the theme switch: the desktop menus open on
// hover or keyboard focus (CSS `group-focus-within`), and the mobile menu is a <details> element.

function A({ href, className, children }: { href: string; className: string; children: ReactNode }) {
  return isExternal(href) ? (
    <a href={href} className={className}>
      {children}
    </a>
  ) : (
    <Link href={href} className={className}>
      {children}
    </Link>
  );
}

function MenuLink({ link }: { link: NavLink }) {
  const Icon = link.icon;
  return (
    <Link href={link.href} className="group/item flex gap-3.5 rounded-lg p-3 hover:bg-surface-hover focus-visible:bg-surface-hover">
      {Icon && (
        <span className="flex size-9 shrink-0 items-center justify-center rounded-md border border-ink-200 bg-surface text-ink-800 group-hover/item:border-ink-400">
          <Icon className="size-4" strokeWidth={1.75} aria-hidden />
        </span>
      )}
      <span>
        <span className="block text-sm font-medium text-ink-950">{link.label}</span>
        {link.body && <span className="mt-0.5 block text-[13px] leading-5 text-ink-500">{link.body}</span>}
      </span>
    </Link>
  );
}

export function SiteHeader({ signedIn }: { signedIn: boolean }) {
  return (
    <header className="sticky top-0 z-40 border-b border-ink-200 bg-page/90 backdrop-blur-md">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:top-3 focus:left-3 focus:z-50 focus:rounded-md focus:bg-surface focus:px-3 focus:py-2 focus:text-sm"
      >
        Skip to content
      </a>
      <Container className="flex h-16 items-center justify-between gap-6">
        <Link href="/" aria-label={`${BRAND} by ${COMPANY}, home`} className="rounded-md">
          <Logo company />
        </Link>

        <nav className="hidden items-center lg:flex" aria-label="Main">
          {NAV.map((n) =>
            n.menu ? (
              <div key={n.label} className="group relative">
                <Link
                  href={n.href}
                  className="flex items-center gap-1 rounded-md px-3 py-2 text-sm text-ink-700 hover:text-ink-950 group-focus-within:text-ink-950 group-hover:text-ink-950"
                >
                  {n.label}
                  <ChevronDown className="size-3.5 text-ink-400 transition-transform group-focus-within:rotate-180 group-hover:rotate-180" aria-hidden />
                </Link>
                <div className="invisible absolute top-full left-1/2 -translate-x-1/2 pt-2 opacity-0 transition-[opacity,visibility] duration-150 group-focus-within:visible group-focus-within:opacity-100 group-hover:visible group-hover:opacity-100">
                  <div
                    className={`rounded-xl border border-ink-200 bg-raised p-2 shadow-[0_24px_48px_-16px_rgb(26_24_22/0.22)] dark:shadow-[0_24px_48px_-16px_rgb(0_0_0/0.7)] ${n.menu.wide ? "w-[40rem]" : "w-[22rem]"}`}
                  >
                    <div className={n.menu.wide ? "grid grid-cols-2 gap-1" : "grid gap-1"}>
                      {n.menu.links.map((l) => (
                        <MenuLink key={l.href} link={l} />
                      ))}
                    </div>
                    {n.menu.footer && (
                      <Link
                        href={n.menu.footer.href}
                        className="mt-1 flex items-center justify-between rounded-lg border-t border-ink-200 px-3 pt-3 pb-2 text-[13px] font-medium text-ink-700 hover:text-ink-950"
                      >
                        {n.menu.footer.label} <ArrowRight className="size-3.5" aria-hidden />
                      </Link>
                    )}
                  </div>
                </div>
              </div>
            ) : (
              <Link key={n.label} href={n.href} className="rounded-md px-3 py-2 text-sm text-ink-700 hover:text-ink-950">
                {n.label}
              </Link>
            ),
          )}
        </nav>

        <div className="flex items-center gap-2">
          <div className="hidden items-center gap-1.5 lg:flex">
            <HeaderActions signedIn={signedIn} />
          </div>
          <ThemeSwitch className="ml-1" />
          <details className="group lg:hidden">
            <summary className="flex cursor-pointer list-none items-center rounded-md p-2 text-ink-800 hover:bg-ink-100 [&::-webkit-details-marker]:hidden">
              <Menu className="size-5 group-open:hidden" aria-hidden />
              <X className="hidden size-5 group-open:block" aria-hidden />
              <span className="sr-only">Menu</span>
            </summary>
            {/* Absolute, not fixed: the header's backdrop blur makes it the containing block for fixed children too. */}
            <div className="absolute inset-x-0 top-full h-[calc(100dvh-4rem)] overflow-y-auto border-t border-ink-200 bg-page">
              <nav aria-label="Main" className="mx-auto max-w-6xl px-6 pt-4 pb-10">
                {NAV.map((n) => (
                  <div key={n.label} className="border-b border-ink-200 py-4">
                    <Link href={n.href} className="block py-1 text-lg font-medium text-ink-950">
                      {n.label}
                    </Link>
                    {n.menu && (
                      <ul className="mt-2 grid gap-x-6 sm:grid-cols-2">
                        {n.menu.links.map((l) => (
                          <li key={l.href}>
                            <Link href={l.href} className="block py-1.5 text-[15px] text-ink-600 hover:text-ink-950">
                              {l.label}
                            </Link>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                ))}
                <div className="mt-6 flex flex-col gap-2">
                  <HeaderActions signedIn={signedIn} stacked />
                </div>
              </nav>
            </div>
          </details>
        </div>
      </Container>
    </header>
  );
}

function HeaderActions({ signedIn, stacked = false }: { signedIn: boolean; stacked?: boolean }) {
  const primary = "rounded-md bg-inverse px-3.5 py-2 text-center text-sm font-medium text-on-inverse hover:bg-inverse-hover";
  const quiet = stacked
    ? "rounded-md border border-ink-300 px-3.5 py-2 text-center text-sm font-medium text-ink-900"
    : "rounded-md px-3 py-2 text-center text-sm font-medium text-ink-700 hover:text-ink-950";
  if (signedIn) {
    return (
      <a href="/home" className={primary}>
        Open workspace
      </a>
    );
  }
  return (
    <>
      <a href={SIGN_IN} className={quiet}>
        Sign in
      </a>
      <Link href="/contact" className={primary}>
        Book a demo
      </Link>
    </>
  );
}

export function SiteFooter() {
  const year = new Date().getFullYear();
  return (
    <footer className="bg-page" aria-labelledby="footer-title">
      <h2 id="footer-title" className="sr-only">
        Site
      </h2>
      <Container className="grid gap-12 pt-16 pb-12 lg:grid-cols-[1.4fr_repeat(5,1fr)] lg:gap-8">
        <div className="max-w-xs">
          {/* Always "Cyte by Onekami" here, the homepage included; only the header hides the byline on "/". */}
          <div className="flex flex-wrap items-center gap-2">
            <Logo size="lg" />
            <span className="flex items-center gap-1.5 text-sm font-medium text-ink-500">
              by <CompanyMark className="h-4" />
            </span>
          </div>
          <p className="mt-5 text-sm leading-6 text-ink-600">
            Verified, cited answers from legal and medical documents. {BRAND} is made by {COMPANY}.
          </p>
          <dl className="mt-6 space-y-1.5 text-sm">
            <div className="flex gap-2">
              <dt className="w-16 text-ink-500">Sales</dt>
              <dd>
                <a href={DEMO_MAIL} className="text-ink-900 underline-offset-4 hover:underline">
                  {CONTACT_EMAIL}
                </a>
              </dd>
            </div>
            <div className="flex gap-2">
              <dt className="w-16 text-ink-500">Support</dt>
              <dd>
                <a href={SUPPORT_MAIL} className="text-ink-900 underline-offset-4 hover:underline">
                  {SUPPORT_EMAIL}
                </a>
              </dd>
            </div>
          </dl>
        </div>
        {FOOTER.map((col) => (
          <nav key={col.title} aria-label={col.title}>
            <h3 className="font-mono text-[11px] font-medium tracking-[0.14em] text-ink-500 uppercase">{col.title}</h3>
            <ul className="mt-4 space-y-2.5">
              {col.links.map((l) => (
                <li key={l.label}>
                  <A href={l.href} className="text-sm text-ink-700 hover:text-ink-950">
                    {l.label}
                  </A>
                </li>
              ))}
            </ul>
          </nav>
        ))}
      </Container>
      <div className="border-t border-ink-200">
        <Container className="flex flex-col gap-4 py-7 text-xs leading-5 text-ink-500 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-3">
            <CompanyMark className="h-5" />
            <p>
              © {year} {COMPANY}. All rights reserved.
            </p>
          </div>
          <p className="max-w-md md:text-right">
            {BRAND} reports what your documents say. It does not give legal or medical advice.
          </p>
        </Container>
      </div>
    </footer>
  );
}

/** Header, page, closing band and footer. Used by the (site) layout and by the root not-found page. */
export function SiteShell({ signedIn, children }: { signedIn: boolean; children: ReactNode }) {
  return (
    <div className="site min-h-full bg-page text-ink-900">
      <SiteHeader signedIn={signedIn} />
      <main id="main">{children}</main>
      <CtaBand signedIn={signedIn} />
      <SiteFooter />
    </div>
  );
}

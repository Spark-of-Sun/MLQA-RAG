import { ArrowRight, BadgeCheck, ChevronDown, FileText } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { isExternal, SIGN_UP } from "@/components/site/links";
import type { SampleAnswer } from "@/components/site/products";
import { BRAND, COMPANY, CONTACT_EMAIL, SUPPORT_EMAIL } from "@/lib/format";

// Building blocks of the public website. Server components only, no client JavaScript: menus open on hover or
// focus, toggles are <details>. No style attributes either, so the strict CSP needs nothing extra; staggered
// load animations use the `d-1`…`d-5` classes from globals.css.

/** Stagger class for the n-th item of a group, for `.rise` (see globals.css). */
export function delay(i: number): string {
  return `d-${Math.max(0, Math.min(5, i))}`;
}

export function Container({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`mx-auto w-full max-w-6xl px-6 lg:px-8 ${className}`}>{children}</div>;
}

/** Small mono eyebrow with the red brush dot, as in "● SECURITY". */
export function Label({ children, dark = false }: { children: ReactNode; dark?: boolean }) {
  return (
    <p className={`inline-flex items-center gap-2.5 font-mono text-[11px] font-medium tracking-[0.14em] uppercase ${dark ? "text-on-band-subtle" : "text-ink-500"}`}>
      <span className="size-1.5 rounded-full bg-brush" aria-hidden />
      {children}
    </p>
  );
}

/** A link with an arrow, for "Read more" style actions. */
export function TextLink({ href, children, dark = false }: { href: string; children: ReactNode; dark?: boolean }) {
  const cls = `group inline-flex items-center gap-1.5 text-sm font-medium underline-offset-4 hover:underline ${dark ? "text-on-band" : "text-ink-950"}`;
  const body = (
    <>
      {children} <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden />
    </>
  );
  return isExternal(href) ? (
    <a href={href} className={cls}>
      {body}
    </a>
  ) : (
    <Link href={href} className={cls}>
      {body}
    </Link>
  );
}

export function ButtonLink({
  href,
  children,
  variant = "primary",
  size = "md",
}: {
  href: string;
  children: ReactNode;
  variant?: "primary" | "secondary" | "light" | "ghost-light";
  size?: "sm" | "md";
}) {
  const style = {
    primary: "bg-inverse text-on-inverse hover:bg-inverse-hover",
    secondary: "border border-ink-300 bg-surface text-ink-900 hover:border-ink-950",
    // The two below are only used on bands, which are dark in both themes.
    light: "bg-on-band text-band hover:bg-white",
    "ghost-light": "border border-white/25 text-on-band hover:border-white/60",
  }[variant];
  const pad = size === "sm" ? "px-3.5 py-2 text-sm" : "px-5 py-2.5 text-sm";
  const cls = `inline-flex items-center justify-center gap-2 rounded-md font-medium whitespace-nowrap transition-colors ${pad} ${style}`;
  // Auth routes and mailto links need a full navigation, not a client-side transition.
  return isExternal(href) ? (
    <a href={href} className={cls}>
      {children}
    </a>
  ) : (
    <Link href={href} className={cls}>
      {children}
    </Link>
  );
}

/** Opening block of an inner page, on the ruled-paper grid. Its parts rise in on load, one after another. */
export function PageHero({
  label,
  title,
  intro,
  actions,
  aside,
  children,
}: {
  label: string;
  title: ReactNode;
  intro: ReactNode;
  actions?: ReactNode;
  aside?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <section className="site-grid relative border-b border-ink-200">
      <Container className="pt-16 pb-16 md:pt-24 md:pb-24">
        <div className={aside ? "grid items-center gap-14 lg:grid-cols-[1.05fr_1fr]" : ""}>
          <div className="max-w-3xl">
            <div className="rise">
              <Label>{label}</Label>
            </div>
            <h1 className="rise d-1 mt-6 text-[2.6rem] leading-[1.05] font-medium text-balance text-ink-950 md:text-6xl md:leading-[1.03]">
              {title}
            </h1>
            <p className="rise d-2 mt-6 max-w-2xl text-lg leading-8 text-pretty text-ink-600">{intro}</p>
            {actions && <div className="rise d-3 mt-9 flex flex-wrap gap-3">{actions}</div>}
            {children}
          </div>
          {aside && <div className="rise d-3">{aside}</div>}
        </div>
      </Container>
    </section>
  );
}

export function Section({
  id,
  label,
  title,
  intro,
  action,
  tone = "plain",
  children,
}: {
  id?: string;
  label?: string;
  title: ReactNode;
  intro?: ReactNode;
  /** A link shown at the right of the heading on wide screens. */
  action?: ReactNode;
  tone?: "plain" | "muted" | "dark";
  children: ReactNode;
}) {
  const dark = tone === "dark";
  // A dark section is a band: ink in both themes (its own tokens in globals.css). In the dark theme it gets a
  // hairline on top so it still separates from the page.
  const bg = dark ? "bg-band text-on-band dark:border-t dark:border-white/10" : tone === "muted" ? "bg-page-muted" : "";
  return (
    <section id={id} className={`scroll-mt-20 border-b border-ink-200 ${bg}`}>
      <Container className="py-20 md:py-28">
        <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
          <div className="max-w-3xl">
            {label && (
              <div className="mb-5">
                <Label dark={dark}>{label}</Label>
              </div>
            )}
            <h2 className={`text-3xl leading-tight font-medium text-balance md:text-[2.75rem] md:leading-[1.08] ${dark ? "text-on-band" : "text-ink-950"}`}>
              {title}
            </h2>
            {intro && <p className={`mt-5 max-w-2xl text-base leading-7 text-pretty md:text-lg md:leading-8 ${dark ? "text-on-band-muted" : "text-ink-600"}`}>{intro}</p>}
          </div>
          {action && <div className="shrink-0">{action}</div>}
        </div>
        <div className="mt-14">{children}</div>
      </Container>
    </section>
  );
}

/** Numbered tiles in a ruled grid: "01 Upload", "02 Ask"… */
export function NumberedGrid({
  items,
  dark = false,
  columns = 4,
}: {
  items: { title: string; body: string; href?: string }[];
  dark?: boolean;
  columns?: 3 | 4;
}) {
  const line = dark ? "border-white/12" : "border-ink-200";
  return (
    <ol className={`grid border-t border-l sm:grid-cols-2 ${columns === 3 ? "lg:grid-cols-3" : "lg:grid-cols-4"} ${line}`}>
      {items.map((it, i) => {
        const inner = (
          <>
            <span className="absolute inset-x-0 top-0 h-0.5 origin-left scale-x-0 bg-brush transition-transform duration-500 group-hover:scale-x-100" aria-hidden />
            <span className={`font-mono text-xs ${dark ? "text-on-band-subtle" : "text-ink-400"}`}>{String(i + 1).padStart(2, "0")}</span>
            <h3 className={`mt-8 text-lg font-semibold tracking-tight ${dark ? "text-on-band" : "text-ink-950"}`}>{it.title}</h3>
            <p className={`mt-2 text-sm leading-6 ${dark ? "text-on-band-muted" : "text-ink-600"}`}>{it.body}</p>
            {it.href && <ArrowRight className="mt-5 size-4 text-ink-400 transition-transform group-hover:translate-x-1" aria-hidden />}
          </>
        );
        const cell = `group relative block h-full overflow-hidden border-r border-b p-6 transition-colors md:p-7 ${line} ${dark ? "hover:bg-white/5" : "hover:bg-surface"}`;
        return (
          <li key={it.title}>
            {it.href ? (
              <Link href={it.href} className={cell}>
                {inner}
              </Link>
            ) : (
              <div className={cell}>{inner}</div>
            )}
          </li>
        );
      })}
    </ol>
  );
}

/** Icon, title and one line, in a grid with a hairline above each item. */
export function PointGrid({
  items,
  dark = false,
  columns = 3,
}: {
  items: { title: string; body: string; icon?: typeof ArrowRight }[];
  dark?: boolean;
  columns?: 2 | 3 | 4;
}) {
  const cols = columns === 4 ? "lg:grid-cols-4" : columns === 2 ? "lg:grid-cols-2" : "lg:grid-cols-3";
  return (
    <div className={`grid gap-x-10 gap-y-12 sm:grid-cols-2 ${cols}`}>
      {items.map(({ title, body, icon: Icon }) => (
        <div key={title} className={`group relative border-t pt-6 ${dark ? "border-white/15" : "border-ink-200"}`}>
          <span className={`absolute -top-px left-0 h-px w-full origin-left scale-x-0 transition-transform duration-500 group-hover:scale-x-100 ${dark ? "bg-on-band" : "bg-ink-950"}`} aria-hidden />
          {Icon && <Icon className={`mb-5 size-5 ${dark ? "text-on-band-muted" : "text-ink-800"}`} strokeWidth={1.6} aria-hidden />}
          <h3 className={`font-semibold tracking-tight ${dark ? "text-on-band" : "text-ink-950"}`}>{title}</h3>
          <p className={`mt-2 text-sm leading-6 ${dark ? "text-on-band-muted" : "text-ink-600"}`}>{body}</p>
        </div>
      ))}
    </div>
  );
}

/** A checked list in two columns. */
export function CheckList({ items, columns = 2 }: { items: string[]; columns?: 1 | 2 }) {
  return (
    <ul className={`grid gap-x-10 ${columns === 2 ? "sm:grid-cols-2" : ""}`}>
      {items.map((i) => (
        <li key={i} className="flex items-start gap-3 border-b border-ink-200 py-3.5 text-sm text-ink-800">
          <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-brush" aria-hidden /> {i}
        </li>
      ))}
    </ul>
  );
}

/** FAQ: each question a <details>, so it opens without JavaScript. */
export function Questions({ items }: { items: { q: string; a: ReactNode }[] }) {
  return (
    <div className="divide-y divide-ink-200 border-y border-ink-200">
      {items.map(({ q, a }) => (
        <details key={q} className="group">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-6 py-5 text-base font-medium text-ink-950 hover:text-ink-700 [&::-webkit-details-marker]:hidden">
            {q}
            <ChevronDown className="size-4 shrink-0 text-ink-400 transition-transform group-open:rotate-180" aria-hidden />
          </summary>
          <div className="slide-in max-w-3xl pb-6 text-[15px] leading-7 text-ink-600">{a}</div>
        </details>
      ))}
    </div>
  );
}

/**
 * The product visual: a crafted, static answer as the Ask screen shows it, with numbered citations, the
 * verification line and the open source panel with its highlighted passage. Drawn from sample documents.
 */
export function AnswerCard({ sample, compact = false }: { sample: SampleAnswer; compact?: boolean }) {
  const source = sample.sources[0];
  return (
    <figure className="m-0">
      <div className="overflow-hidden rounded-xl border border-ink-200 bg-surface shadow-[0_1px_0_rgb(0_0_0/0.02),0_24px_48px_-24px_rgb(26_24_22/0.25)] dark:shadow-none">
        <div className="flex items-center justify-between border-b border-ink-200 px-4 py-2.5">
          <div className="flex items-center gap-1.5" aria-hidden>
            <span className="size-2 rounded-full bg-ink-200" />
            <span className="size-2 rounded-full bg-ink-200" />
            <span className="size-2 rounded-full bg-ink-200" />
          </div>
          <p className="font-mono text-[10px] tracking-[0.14em] text-ink-400 uppercase">Ask · sample documents</p>
        </div>
        <div className={`grid ${compact ? "" : "md:grid-cols-[1fr_15rem]"}`}>
          <div className="space-y-5 p-5 md:p-6">
            <p className="ml-auto w-fit max-w-[92%] rounded-xl rounded-br-sm bg-inverse px-4 py-2.5 text-sm leading-6 text-on-inverse">
              {sample.question}
            </p>
            <div>
              <p className="text-[15px] leading-7 text-ink-800">
                {sample.sentences.map((s, i) => (
                  <span key={i}>
                    {s.text}
                    <sup
                      className={`ml-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded-sm px-1 font-mono text-[10px] font-semibold ${
                        s.cite === 1 && i === 0 ? "bg-brand-600 text-white" : "bg-brand-50 text-brand-700 ring-1 ring-brand-200"
                      }`}
                    >
                      {s.cite}
                    </sup>{" "}
                  </span>
                ))}
              </p>
              <ul className="mt-4 flex flex-wrap gap-2">
                {sample.sources.map((src, i) => (
                  <li key={i} className="flex items-center gap-1.5 rounded-md border border-ink-200 px-2.5 py-1 text-xs text-ink-600">
                    <span className="font-mono text-[10px] font-semibold text-brand-700">{i + 1}</span>
                    {src.where}
                  </li>
                ))}
              </ul>
              <p className="mt-4 flex items-center gap-2 border-t border-ink-200 pt-3 text-xs text-ink-600">
                <BadgeCheck className="size-4 text-ink-950" strokeWidth={1.75} aria-hidden />
                {sample.sentences.length} sentences verified · 10 checks each
              </p>
            </div>
          </div>
          {!compact && source && (
            <div className="border-t border-ink-200 bg-page-muted p-5 md:border-t-0 md:border-l">
              <p className="flex items-center gap-1.5 font-mono text-[10px] font-semibold tracking-[0.14em] text-brand-700 uppercase">
                <FileText className="size-3.5" aria-hidden /> Source 1
              </p>
              <p className="mt-2 text-sm font-semibold text-ink-950">{source.title}</p>
              <p className="text-xs text-ink-500">{source.where}</p>
              <p className="mt-4 font-serif text-[15px] leading-7 text-ink-700">
                {source.before}
                <mark className="cite">{source.mark}</mark>
                {source.after}
              </p>
            </div>
          )}
        </div>
      </div>
      <figcaption className="mt-3 text-xs text-ink-500">Illustration of the Ask screen with a sample document.</figcaption>
    </figure>
  );
}

/** The ink band that closes every page: book a demo, or start. */
export function CtaBand({ signedIn }: { signedIn: boolean }) {
  return (
    <section className="bg-band text-on-band dark:border-t dark:border-white/10" aria-labelledby="cta-title">
      <Container className="grid gap-10 py-20 md:grid-cols-[1.4fr_1fr] md:items-end md:py-28">
        <div>
          <Label dark>Get started</Label>
          <h2 id="cta-title" className="mt-6 text-4xl leading-[1.06] font-medium text-balance md:text-[3.25rem]">
            See Cyte answer from documents like yours.
          </h2>
          <p className="mt-5 max-w-xl text-lg leading-8 text-on-band-muted">
            A demo on public documents from your field, then a pilot on your own, with our team on hand.
          </p>
        </div>
        <div className="flex flex-wrap gap-3 md:justify-end">
          <ButtonLink href="/contact" variant="light">
            Book a demo <ArrowRight className="size-4" aria-hidden />
          </ButtonLink>
          {signedIn ? (
            <ButtonLink href="/home" variant="ghost-light">
              Open your workspace
            </ButtonLink>
          ) : (
            <ButtonLink href={SIGN_UP} variant="ghost-light">
              Create your organization
            </ButtonLink>
          )}
        </div>
      </Container>
    </section>
  );
}

/** Long-form text (legal pages): headings and paragraphs with comfortable measure. */
export function Prose({ children }: { children: ReactNode }) {
  return (
    <div className="max-w-3xl text-[15px] leading-7 text-ink-700 [&_a]:font-medium [&_a]:text-link [&_a]:underline [&_a]:underline-offset-4 [&_h2]:mt-12 [&_h2]:mb-4 [&_h2]:text-2xl [&_h2]:font-medium [&_h2]:text-ink-950 [&_li]:mt-2 [&_p]:mt-4 [&_strong]:text-ink-950 [&_ul]:mt-4 [&_ul]:list-disc [&_ul]:pl-5">
      {children}
    </div>
  );
}

/** Company facts, for the About and Contact pages. Only what is true and public. */
export function CompanyFacts() {
  const facts: [string, ReactNode][] = [
    ["Company", COMPANY],
    ["Product", `${BRAND} Legal QA and ${BRAND} Medical QA`],
    ["Stage", "Early access"],
    ["Sales and demos", <a key="s" href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>],
    ["Support", <a key="h" href={`mailto:${SUPPORT_EMAIL}`}>{SUPPORT_EMAIL}</a>],
    ["Security reports", <a key="r" href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>],
  ];
  return (
    <dl className="grid gap-x-10 sm:grid-cols-2 lg:grid-cols-3">
      {facts.map(([k, v]) => (
        <div key={k} className="border-t border-ink-200 py-5">
          <dt className="font-mono text-[11px] tracking-[0.14em] text-ink-500 uppercase">{k}</dt>
          <dd className="mt-2 text-ink-950 [&_a]:underline-offset-4 [&_a:hover]:underline">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

/** The body of the 404 page, inside the site's header and footer. */
export function NotFoundContent({ signedIn }: { signedIn: boolean }) {
  return (
    <section className="site-grid border-b border-ink-200">
      <Container className="py-24 md:py-36">
        <Label>Error 404</Label>
        <h1 className="mt-6 max-w-4xl text-5xl leading-[1.02] font-medium text-balance text-ink-950 md:text-7xl">
          This page does not address that.
        </h1>
        <p className="mt-6 max-w-xl text-lg leading-8 text-ink-600">
          The link may be wrong, or the page is not available to your role. Like our answers, we would rather say so than
          guess.
        </p>
        <div className="mt-9 flex flex-wrap gap-3">
          <ButtonLink href={signedIn ? "/home" : "/"}>
            {signedIn ? "Go to your workspace" : "Back to the home page"} <ArrowRight className="size-4" aria-hidden />
          </ButtonLink>
          <ButtonLink href="/docs" variant="secondary">
            Documentation
          </ButtonLink>
          <ButtonLink href="/contact" variant="secondary">
            Contact us
          </ButtonLink>
        </div>
      </Container>
    </section>
  );
}

import { ArrowRight, BadgeCheck, Ban, FileSearch, Link2, Lock, ScrollText, Share2 } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { ButtonLink, Container, delay, Label, NumberedGrid, PointGrid, Section } from "@/components/site/blocks";
import { CountUp } from "@/components/site/count-up";
import { FlowSteps } from "@/components/site/flow-steps";
import { INDUSTRY_LINKS, SIGN_IN, SIGN_UP } from "@/components/site/links";
import { LiveDemo } from "@/components/site/live-demo";
import { auth0 } from "@/lib/auth0";
import { BRAND, COMPANY } from "@/lib/format";

export const metadata: Metadata = {
  title: { absolute: `${BRAND} by ${COMPANY} · verified, cited answers from legal and medical documents` },
  description: `${BRAND} answers questions about contracts, case files, drug labels and clinical documents. Every sentence cites its page and clause and is checked against the source before you see it.`,
};

const AUTH_ERRORS: Record<string, string> = {
  invalid_state: "That sign-in link was already used or has expired. Please sign in again.",
  missing_state: "That sign-in link was already used or has expired. Please sign in again.",
  access_denied: "Auth0 refused the sign-in. If this repeats, check that the API identifier matches AUTH0_AUDIENCE_MAIN.",
};

const DOCUMENT_TYPES = [
  "Contracts",
  "Case files",
  "Statutes",
  "US federal regulations (eCFR)",
  "FDA drug labels (SPL)",
  "Clinical guidelines",
  "Research articles (JATS)",
  "Policies and procedures",
  "Word documents",
  "Text PDFs",
];

const WHAT = [
  {
    icon: BadgeCheck,
    title: "Every sentence checked",
    body: "Quotes, numbers, dates and dosages are compared with the cited passage before anything is shown.",
  },
  { icon: FileSearch, title: "Page and clause citations", body: "Click a citation to see the exact passage, highlighted, with its section and page." },
  { icon: Ban, title: "No answer beats a wrong one", body: "When your documents do not support an answer, Cyte says so plainly." },
  { icon: Share2, title: "Sharing you control", body: "Private by default. Share with your admin, chosen colleagues or the whole team." },
  { icon: Lock, title: "Isolation in the database", body: "Each team's documents are separated by the database itself, not just the screens." },
  { icon: ScrollText, title: "A record you can verify", body: "Uploads, approvals and answers go into a hash-chained audit trail." },
];

const FACTS = [
  { value: 10, label: "checks on every sentence" },
  { value: 0, label: "unchecked sentences shown" },
  { value: 7, label: "file formats, from PDF to FDA drug labels" },
  { value: 3, label: "roles with clear limits" },
];

const WORK_WITH_US = [
  { title: "Demo", body: "We show Cyte on public documents like yours and answer your team's questions.", href: "/contact" },
  { title: "Pilot", body: "Your team uses Cyte on a chosen set of documents, with us on hand.", href: "/contact" },
  { title: "Roll out", body: "Workspaces for each team, admins approved, members invited.", href: "/contact" },
  { title: "Support", body: "Help by email for admins and members while you work.", href: "/contact" },
];

// Shown in the security band: each audit event carries the hash of the one before it.
const CHAIN = [
  ["Member approved", "9f2c41d0"],
  ["Document uploaded", "4be81a77"],
  ["Shared with admin", "c03d95e2"],
  ["Question answered", "71aa0f3b"],
  ["Chat renamed", "e5d2b8c4"],
  ["Document indexed", "2f6e0d19"],
];

const STATEMENT =
  "General AI writes fluent answers you cannot check. Cyte writes only what your documents say, and shows you exactly where they say it.";

export default async function Home({ searchParams }: { searchParams: Promise<{ auth_error?: string }> }) {
  const signedIn = Boolean(await auth0.getSession());
  const { auth_error: authError } = await searchParams;
  const words = STATEMENT.split(" ");
  const split = words.indexOf("Cyte");
  return (
    <>
      {authError && (
        <div role="alert" className="border-b border-amber-200 bg-amber-50 px-6 py-3 text-center text-sm text-amber-900">
          {AUTH_ERRORS[authError] ?? `Sign-in did not complete (${authError}). Please try again.`}{" "}
          <a href={SIGN_IN} className="font-semibold underline">
            Sign in
          </a>
        </div>
      )}

      <section className="relative overflow-hidden border-b border-ink-200/70">
        <div
          className="absolute inset-x-0 top-0 -z-10 h-[40rem] bg-[radial-gradient(60rem_30rem_at_75%_-10%,var(--color-brand-100),transparent)]"
          aria-hidden
        />
        <Container className="grid items-center gap-14 pt-20 pb-20 lg:grid-cols-[1fr_1.05fr] lg:pt-24">
          <div>
            <div className="rise">
              <Label>Early access · legal and clinical teams</Label>
            </div>
            <h1 className="rise mt-6 text-5xl font-semibold tracking-tight text-ink-950 md:text-6xl md:leading-[1.04]" {...delay(1, 120)}>
              Answers you can cite. <span className="text-ink-400">Or no answer at all.</span>
            </h1>
            <p className="rise mt-6 max-w-xl text-lg leading-8 text-ink-600" {...delay(2, 120)}>
              {BRAND} answers questions about your documents. Every sentence links to the page and clause it came from, and
              is checked against that passage before you see it.
            </p>
            <div className="rise mt-8 flex flex-wrap gap-3" {...delay(3, 120)}>
              <ButtonLink href={signedIn ? "/home" : SIGN_UP}>
                {signedIn ? "Open workspace" : "Create your organization"} <ArrowRight className="size-4" aria-hidden />
              </ButtonLink>
              <ButtonLink href="/contact" variant="secondary">
                Talk to us
              </ButtonLink>
            </div>
            {!signedIn && (
              <p className="rise mt-5 text-sm text-ink-500" {...delay(4, 120)}>
                Invited by your team?{" "}
                <a href={SIGN_IN} className="font-medium text-ink-900 underline underline-offset-4">
                  Sign in and enter your code
                </a>
              </p>
            )}
          </div>
          <div className="rise" {...delay(3, 140)}>
            <LiveDemo />
          </div>
        </Container>
      </section>

      <section className="marquee overflow-hidden border-b border-ink-200/70 bg-white py-5" aria-label="Documents Cyte reads">
        <div className="marquee-track flex w-max gap-10 pr-10">
          {[...DOCUMENT_TYPES, ...DOCUMENT_TYPES].map((d, i) => (
            <span key={i} className="flex items-center gap-10 font-mono text-sm whitespace-nowrap text-ink-500" aria-hidden={i >= DOCUMENT_TYPES.length}>
              {d}
              <span className="size-1 rounded-full bg-ink-300" aria-hidden />
            </span>
          ))}
        </div>
      </section>

      <section className="border-b border-ink-200/70">
        <Container className="py-24 md:py-32">
          <p className="max-w-4xl text-3xl leading-tight font-medium tracking-tight md:text-[2.75rem]">
            {words.map((w, i) => (
              <span key={i} data-reveal {...delay(i, 35)} className={`inline-block ${i < split ? "text-ink-950" : "text-ink-400"}`}>
                {w}&nbsp;
              </span>
            ))}
          </p>
        </Container>
      </section>

      <Section title="What Cyte does." intro="One workspace for searching, drafting and checking answers, with controls that match how firms and hospitals work.">
        <PointGrid items={WHAT} />
        <div className="mt-12" data-reveal>
          <ButtonLink href="/product" variant="secondary">
            Explore the product <ArrowRight className="size-4" aria-hidden />
          </ButtonLink>
        </div>
      </Section>

      <Section muted title="From document to cited answer." intro="Most answers arrive in 5 to 20 seconds. Nothing is shown until every sentence has passed.">
        <FlowSteps />
      </Section>

      <section className="border-b border-ink-200/70">
        <Container className="py-20 md:py-24">
          <h2 data-reveal className="text-3xl font-semibold tracking-tight text-ink-950 md:text-4xl">
            For work where every word matters.
          </h2>
          <ul className="mt-10 border-t border-ink-200">
            {INDUSTRY_LINKS.map((i, n) => (
              <li key={i.href} data-reveal {...delay(n, 120)} className="border-b border-ink-200">
                <Link href={i.href} className="group relative flex items-center justify-between gap-6 overflow-hidden py-8">
                  <span
                    className="absolute inset-0 -z-10 origin-left scale-x-0 bg-ink-50 transition-transform duration-500 group-hover:scale-x-100"
                    aria-hidden
                  />
                  <span className="transition-transform duration-500 group-hover:translate-x-4">
                    <span className="block text-3xl font-semibold tracking-tight text-ink-950 md:text-5xl">{i.label}</span>
                    <span className="mt-2 block text-sm text-ink-500">{i.body}</span>
                  </span>
                  <ArrowRight
                    className="mr-4 size-7 text-ink-300 transition-all duration-500 group-hover:translate-x-1 group-hover:text-ink-950"
                    aria-hidden
                  />
                </Link>
              </li>
            ))}
          </ul>
        </Container>
      </section>

      <section className="border-b border-ink-200/70 bg-ink-50">
        <Container className="py-20">
          <dl className="grid gap-10 sm:grid-cols-2 lg:grid-cols-4">
            {FACTS.map((f, i) => (
              <div key={f.label} data-reveal {...delay(i)} className="border-t border-ink-300 pt-5">
                <dt className="text-6xl font-semibold tracking-tight text-ink-950">
                  <CountUp to={f.value} />
                </dt>
                <dd className="mt-3 font-mono text-xs tracking-wide text-ink-500 uppercase">{f.label}</dd>
              </div>
            ))}
          </dl>
        </Container>
      </section>

      <Section
        dark
        title="Built to be trusted with privileged information."
        intro="Access rules live in the database. A member's private documents and chats stay private, even from their admin, and the organization owner never sees workspace content."
      >
        <div className="marquee -mx-6 overflow-hidden" aria-hidden>
          <div className="marquee-track flex w-max items-center" style={{ animationDuration: "30s" }}>
            {[...CHAIN, ...CHAIN].map(([event, hash], i) => (
              <div key={i} className="flex items-center">
                <div className="w-52 rounded-xl border border-white/10 bg-white/5 px-4 py-3">
                  <p className="text-sm font-medium text-white">{event}</p>
                  <p className="mt-1 font-mono text-[11px] text-ink-400">sha256 {hash}…</p>
                </div>
                <Link2 className="mx-3 size-4 text-ink-500" />
              </div>
            ))}
          </div>
        </div>
        <p data-reveal className="mt-6 text-sm text-ink-400">
          Every audit event carries the hash of the one before it, so any change to the history shows.
        </p>
        <div className="mt-10" data-reveal>
          <ButtonLink href="/security" variant="light">
            How we protect your data <ArrowRight className="size-4" aria-hidden />
          </ButtonLink>
        </div>
      </Section>

      <Section title="How we work with you." intro={`${COMPANY} works directly with each early customer.`}>
        <NumberedGrid items={WORK_WITH_US} />
      </Section>
    </>
  );
}

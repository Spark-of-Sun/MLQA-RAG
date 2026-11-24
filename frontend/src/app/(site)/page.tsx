import {
  ArrowRight,
  Ban,
  CircleMinus,
  Database,
  EyeOff,
  FileCheck2,
  FileUp,
  Fingerprint,
  KeyRound,
  MessageSquareText,
  Quote,
  ScrollText,
  ShieldCheck,
} from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { AnswerCard, ButtonLink, Container, Label, PointGrid, Questions, Section, TextLink } from "@/components/site/blocks";
import { VERIFICATION_CHECKS } from "@/components/site/checks";
import { faqGroup } from "@/components/site/faq";
import { SIGN_IN, SIGN_UP, SOLUTION_LINKS } from "@/components/site/links";
import { PRODUCTS } from "@/components/site/products";
import { auth0 } from "@/lib/auth0";
import { BRAND } from "@/lib/format";

export const metadata: Metadata = {
  title: { absolute: `${BRAND} · Verified, cited answers from legal and medical documents` },
  description: `${BRAND} Legal QA and ${BRAND} Medical QA answer questions about contracts, case files, drug labels and clinical documents. Every sentence cites its page and clause and is checked against the source before you see it.`,
  alternates: { canonical: "/" },
};

const AUTH_ERRORS: Record<string, string> = {
  invalid_state: "That sign-in link was already used or has expired. Please sign in again.",
  missing_state: "That sign-in link was already used or has expired. Please sign in again.",
  access_denied: "Auth0 refused the sign-in. If this repeats, check that the API identifier matches AUTH0_AUDIENCE_MAIN.",
};

const TRUST = [
  { icon: FileCheck2, title: "Every sentence checked", body: "against its source before you see it" },
  { icon: Quote, title: "Page and clause", body: "on every citation, one click to the passage" },
  { icon: Database, title: "Isolation in the database", body: "each team's documents kept apart" },
  { icon: ScrollText, title: "Hash-chained audit trail", body: "any change to the record shows" },
];

const STEPS = [
  {
    icon: FileUp,
    title: "Upload",
    body: "Contracts, case files, regulations, drug labels and guidelines. Cyte splits each one along its own sections, clauses and pages.",
  },
  {
    icon: MessageSquareText,
    title: "Ask",
    body: "Plain-language questions, with follow-ups in the same chat, over only the documents you are allowed to read.",
  },
  {
    icon: ShieldCheck,
    title: "Get a verified, cited answer",
    body: "Every sentence quotes its passage and passes ten checks. Click a citation to see the highlighted source.",
  },
];

const SECURITY = [
  {
    icon: Database,
    title: "Isolation in the database",
    body: "PostgreSQL row-level security decides what each person may read, for every document, passage and answer. It fails closed.",
  },
  { icon: Fingerprint, title: "Private by default", body: "A member's uploads and chats are theirs alone until they choose to share a document." },
  { icon: EyeOff, title: "Owner kept out of content", body: "The organization owner governs people and codes, and has no access to documents or questions." },
  { icon: KeyRound, title: "Codes and approvals", body: "People join with one-time codes, stored only as keyed hashes, and a person approves every join." },
  { icon: ShieldCheck, title: "Secure sign-in", body: "Sign-in through Auth0. Access tokens stay on the server, and every page runs under a strict content security policy." },
  { icon: ScrollText, title: "Verifiable audit", body: "Every event is chained to the one before it with SHA-256, and edits are blocked in the database." },
];

export default async function Home({ searchParams }: { searchParams: Promise<{ auth_error?: string }> }) {
  const signedIn = Boolean(await auth0.getSession());
  const { auth_error: authError } = await searchParams;
  const legal = PRODUCTS[0];
  const faq = [...faqGroup("product").slice(0, 3), ...faqGroup("verification").slice(0, 2), ...faqGroup("security").slice(0, 1)];
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

      {/* Hero */}
      <section className="site-grid border-b border-ink-200">
        <Container className="grid items-center gap-14 pt-16 pb-20 md:pt-24 lg:grid-cols-[1fr_1.08fr] lg:gap-16 lg:pb-28">
          <div>
            <div className="rise">
              <Label>{BRAND} Legal QA · {BRAND} Medical QA</Label>
            </div>
            <h1 className="rise d-1 mt-7 text-5xl leading-[1.02] font-medium text-balance text-ink-950 md:text-7xl md:leading-[0.98]">
              Answers you can cite.
              <span className="mt-1 block text-ink-400 italic">Or no answer at all.</span>
            </h1>
            <p className="rise d-2 mt-7 max-w-xl text-lg leading-8 text-ink-600">
              {BRAND} answers questions about your contracts, case files, drug labels and guidelines. Every sentence links
              to the page and clause it came from, and is checked against that passage before anyone reads it.
            </p>
            <div className="rise d-3 mt-9 flex flex-wrap gap-3">
              <ButtonLink href="/contact">
                Book a demo <ArrowRight className="size-4" aria-hidden />
              </ButtonLink>
              <ButtonLink href={signedIn ? "/home" : SIGN_UP} variant="secondary">
                {signedIn ? "Open your workspace" : "Create your organization"}
              </ButtonLink>
            </div>
            {!signedIn && (
              <p className="rise d-4 mt-6 text-sm text-ink-500">
                Invited by your team?{" "}
                <a href={SIGN_IN} className="font-medium text-ink-900 underline underline-offset-4">
                  Sign in and enter your code
                </a>
              </p>
            )}
          </div>
          <div className="rise d-3">
            {legal && <AnswerCard sample={legal.sample} />}
          </div>
        </Container>
      </section>

      {/* Trust strip: what the product does, not who uses it. */}
      <section aria-label="What every answer comes with" className="border-b border-ink-200 bg-surface">
        <Container>
          <ul className="grid sm:grid-cols-2 lg:grid-cols-4">
            {TRUST.map(({ icon: Icon, title, body }) => (
              <li
                key={title}
                className="flex items-start gap-3.5 border-t border-ink-200 py-6 first:border-t-0 sm:nth-2:border-t-0 lg:border-t-0 lg:border-l lg:px-6 lg:first:border-l-0 lg:first:pl-0"
              >
                <Icon className="mt-0.5 size-5 shrink-0 text-ink-950" strokeWidth={1.6} aria-hidden />
                <p className="text-sm leading-6">
                  <span className="block font-semibold text-ink-950">{title}</span>
                  <span className="text-ink-500">{body}</span>
                </p>
              </li>
            ))}
          </ul>
        </Container>
      </section>

      {/* The point of view */}
      <section className="border-b border-ink-200">
        <Container className="py-24 md:py-32">
          <p className="display max-w-4xl text-3xl leading-[1.2] font-normal text-ink-950 md:text-[2.75rem]">
            General AI writes fluent answers you cannot check.{" "}
            <span className="text-ink-400">
              {BRAND} writes only what your documents say, and shows you exactly where they say it.
            </span>
          </p>
        </Container>
      </section>

      {/* Two products */}
      <Section
        label="Products"
        title="Two products. One verification engine."
        intro={`${BRAND} Legal QA and ${BRAND} Medical QA read different documents, but every sentence of every answer goes through the same ten checks.`}
        action={<TextLink href="/product">Compare products</TextLink>}
      >
        <div className="grid gap-6 lg:grid-cols-2">
          {PRODUCTS.map((p) => {
            const Icon = p.icon;
            return (
              <Link
                key={p.slug}
                href={`/products/${p.slug}`}
                className="group flex flex-col rounded-xl border border-ink-200 bg-surface p-8 transition-colors hover:border-ink-950 md:p-10"
              >
                <div className="flex items-center justify-between">
                  <span className="flex size-11 items-center justify-center rounded-lg border border-ink-200 text-ink-950">
                    <Icon className="size-5" strokeWidth={1.6} aria-hidden />
                  </span>
                  <ArrowRight className="size-5 text-ink-400 transition-transform group-hover:translate-x-1 group-hover:text-ink-950" aria-hidden />
                </div>
                <h3 className="display mt-8 text-3xl font-medium text-ink-950 md:text-4xl">{p.fullName}</h3>
                <p className="mt-2 font-mono text-[11px] tracking-[0.14em] text-ink-500 uppercase">{p.who}</p>
                <p className="mt-5 max-w-md leading-7 text-ink-600">{p.intro}</p>
                <ul className="mt-7 flex flex-wrap gap-2">
                  {p.documents.map((d) => (
                    <li key={d} className="rounded-md border border-ink-200 bg-page px-2.5 py-1 text-xs text-ink-600">
                      {d}
                    </li>
                  ))}
                </ul>
                <div className="min-h-8 flex-1" aria-hidden />
                <p className="border-t border-ink-200 pt-5 text-sm text-ink-700">
                  <span className="text-ink-400">Ask: </span>“{p.questions[0]}”
                </p>
              </Link>
            );
          })}
        </div>
      </Section>

      {/* How it works */}
      <Section
        tone="muted"
        label="How it works"
        title="From document to cited answer."
        intro="Most answers arrive in 5 to 20 seconds. Nothing is shown until every sentence has passed."
      >
        <ol className="grid gap-px overflow-hidden rounded-xl border border-ink-200 bg-ink-200 lg:grid-cols-3">
          {STEPS.map(({ icon: Icon, title, body }, i) => (
            <li key={title} className="flex flex-col bg-surface p-7 md:p-8">
              <div className="flex items-center gap-3">
                <span className="font-mono text-xs text-ink-400">{String(i + 1).padStart(2, "0")}</span>
                <span className="h-px flex-1 bg-ink-200" aria-hidden />
                <Icon className="size-5 text-ink-950" strokeWidth={1.6} aria-hidden />
              </div>
              <h3 className="mt-8 text-xl font-semibold tracking-tight text-ink-950">{title}</h3>
              <p className="mt-3 text-sm leading-6 text-ink-600">{body}</p>
              <div className="mt-8 rounded-lg border border-ink-200 bg-page p-4 text-xs" aria-hidden>
                {i === 0 && (
                  <ul className="space-y-2">
                    {["Separation Agreement.pdf", "Lisinopril label.xml", "Sepsis protocol.docx"].map((f) => (
                      <li key={f} className="flex items-center justify-between gap-3">
                        <span className="truncate text-ink-700">{f}</span>
                        <span className="rounded bg-emerald-50 px-1.5 py-0.5 font-medium text-emerald-700">ready</span>
                      </li>
                    ))}
                  </ul>
                )}
                {i === 1 && (
                  <div className="space-y-2">
                    <p className="ml-auto w-fit rounded-lg rounded-br-sm bg-inverse px-3 py-1.5 text-on-inverse">What notice is required to terminate?</p>
                    <p className="text-ink-500">Searched as: What notice is required to terminate the agreement?</p>
                  </div>
                )}
                {i === 2 && (
                  <p className="leading-5 text-ink-800">
                    Either party may terminate on ninety (90) days&apos; written notice.
                    <sup className="ml-0.5 rounded-sm bg-brand-600 px-1 font-mono text-[9px] font-semibold text-white">1</sup>
                    <span className="mt-2 flex items-center gap-1.5 border-t border-ink-200 pt-2 text-ink-500">
                      <FileCheck2 className="size-3.5 text-ink-950" /> 1 sentence verified · §12.2 Termination · p. 9
                    </span>
                  </p>
                )}
              </div>
            </li>
          ))}
        </ol>
      </Section>

      {/* The differentiator */}
      <Section
        id="verification"
        tone="dark"
        label="Verification"
        title="Ten checks before you read a word."
        intro="A drafted sentence must quote its source. Before you see it, it has to pass every check below. If one fails, the sentence is removed and the answer says so. A check can only remove a sentence; nothing can approve one that another check rejected."
      >
        <div className="grid gap-12 lg:grid-cols-[1.3fr_1fr]">
          <ol className="grid gap-x-10 sm:grid-cols-2">
            {VERIFICATION_CHECKS.map(([title, body], i) => (
              <li key={title} className="flex gap-4 border-t border-white/12 py-4">
                <span className="w-5 shrink-0 font-mono text-xs leading-6 text-on-band-subtle">{String(i + 1).padStart(2, "0")}</span>
                <p className="text-sm leading-6">
                  <span className="block font-medium text-on-band">{title}</span>
                  <span className="text-on-band-muted">{body}</span>
                </p>
              </li>
            ))}
          </ol>
          <div className="space-y-4">
            <div className="rounded-xl border border-white/12 bg-white/[0.03] p-6">
              <p className="flex items-center gap-2 font-mono text-[11px] tracking-[0.14em] text-on-band-subtle uppercase">
                <CircleMinus className="size-3.5" aria-hidden /> When a check fails
              </p>
              <p className="mt-4 text-sm leading-6 text-on-band-muted">
                <span className="text-on-band line-through decoration-on-band-accent decoration-2">The fee is due within 45 days.</span>
              </p>
              <p className="mt-3 text-sm leading-6 text-on-band">
                A claim in this answer could not be verified and was removed: the number 45 does not appear in the cited passage.
              </p>
            </div>
            <div className="rounded-xl border border-white/12 bg-white/[0.03] p-6">
              <p className="flex items-center gap-2 font-mono text-[11px] tracking-[0.14em] text-on-band-subtle uppercase">
                <Ban className="size-3.5" aria-hidden /> When the documents are silent
              </p>
              <p className="mt-4 text-sm text-on-band-muted">Which court has jurisdiction over disputes under the lease?</p>
              <p className="mt-3 text-base text-on-band">The provided documents do not address this.</p>
            </div>
            <div className="pt-2">
              <TextLink href="/product#verification" dark>
                How verification works
              </TextLink>
            </div>
          </div>
        </div>
      </Section>

      {/* Security */}
      <Section
        label="Security"
        title="Designed for privileged and clinical documents."
        intro="Access rules live in the database, not only in the screens. A member's private documents and chats stay private, even from their admin."
        action={<TextLink href="/security">Security overview</TextLink>}
      >
        <PointGrid items={SECURITY} />
        <p className="mt-14 flex max-w-3xl gap-3 border-l-2 border-brush pl-5 text-sm leading-6 text-ink-600">
          {BRAND} has not completed an external audit or certification yet. During early access, document text is sent to
          Google to make it searchable and cited passages to the configured AI model. Talk to us about hosting and data
          agreements before you upload client or patient records.
        </p>
      </Section>

      {/* Solutions */}
      <Section
        tone="muted"
        label="Solutions"
        title="Built for the teams who sign their name to an answer."
        action={<TextLink href="/solutions">All solutions</TextLink>}
      >
        <ul className="grid gap-px overflow-hidden rounded-xl border border-ink-200 bg-ink-200 sm:grid-cols-2 lg:grid-cols-3">
          {SOLUTION_LINKS.map(({ href, label, body, icon: Icon }) => (
            <li key={href}>
              <Link href={href} className="group flex h-full flex-col bg-surface p-7 hover:bg-surface-hover">
                {Icon && <Icon className="size-5 text-ink-950" strokeWidth={1.6} aria-hidden />}
                <h3 className="mt-6 font-semibold text-ink-950">{label}</h3>
                <p className="mt-1.5 text-sm leading-6 text-ink-600">{body}</p>
                <span className="mt-6 flex items-center gap-1.5 text-sm font-medium text-ink-950">
                  Learn more <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden />
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </Section>

      {/* FAQ */}
      <section className="border-b border-ink-200">
        <Container className="grid gap-12 py-20 md:py-28 lg:grid-cols-[1fr_2fr]">
          <div>
            <Label>FAQ</Label>
            <h2 className="mt-5 text-3xl leading-tight font-medium text-ink-950 md:text-[2.75rem] md:leading-[1.08]">Questions teams ask first.</h2>
            <div className="mt-8">
              <TextLink href="/faq">Read the full FAQ</TextLink>
            </div>
          </div>
          <Questions items={faq} />
        </Container>
      </section>
    </>
  );
}

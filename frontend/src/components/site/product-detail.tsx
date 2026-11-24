import { ArrowRight, Database, EyeOff, Fingerprint, ScrollText } from "lucide-react";
import Link from "next/link";

import {
  AnswerCard,
  ButtonLink,
  CheckList,
  NumberedGrid,
  PageHero,
  PointGrid,
  Questions,
  Section,
  TextLink,
} from "@/components/site/blocks";
import { VerificationChecks } from "@/components/site/checks";
import { SIGN_UP } from "@/components/site/links";
import { PLANS } from "@/components/site/pricing";
import type { Product } from "@/components/site/products";
import { PRODUCTS } from "@/components/site/products";
import { SOLUTIONS } from "@/components/site/solutions";
import { BRAND } from "@/lib/format";

const SECURITY = [
  { icon: Database, title: "Isolation in the database", body: "Row-level security in PostgreSQL decides what each person may read. It fails closed." },
  { icon: Fingerprint, title: "Private by default", body: "Uploads and chats belong to the person who made them until they share a document." },
  { icon: EyeOff, title: "Owner kept out", body: "The organization owner manages people and codes, never documents or questions." },
  { icon: ScrollText, title: "Verifiable audit", body: "Every upload, share and answer is hash-chained; edits are blocked in the database." },
];

/** The full page for one product (Legal QA or Medical QA). Shared by app/(site)/products/legal and .../medical. */
export function ProductDetail({ product }: { product: Product }) {
  const other = PRODUCTS.find((p) => p.slug !== product.slug);
  const solutions = SOLUTIONS.filter((s) => s.product === product.slug);
  return (
    <>
      <PageHero
        label={product.fullName}
        title={product.title}
        intro={product.intro}
        actions={
          <>
            <ButtonLink href="/contact">
              Book a demo <ArrowRight className="size-4" aria-hidden />
            </ButtonLink>
            <ButtonLink href={SIGN_UP} variant="secondary">
              Create your organization
            </ButtonLink>
          </>
        }
        aside={<AnswerCard sample={product.sample} />}
      >
        <p className="rise d-4 mt-8 font-mono text-[11px] tracking-[0.14em] text-ink-500 uppercase">For {product.who.toLowerCase()}</p>
      </PageHero>

      <Section label="The problem" title="Why teams cannot use a general chatbot.">
        <div className="grid gap-px overflow-hidden rounded-xl border border-ink-200 bg-ink-200 md:grid-cols-3">
          {product.problems.map((p) => (
            <div key={p.title} className="bg-surface p-7 md:p-8">
              <h3 className="display text-xl font-medium text-ink-950">{p.title}</h3>
              <p className="mt-3 text-sm leading-6 text-ink-600">{p.body}</p>
            </div>
          ))}
        </div>
      </Section>

      <Section tone="muted" label="Capabilities" title={`What ${product.fullName} does.`}>
        <PointGrid items={product.capabilities} />
      </Section>

      <Section label="Example" title="An answer, sentence by sentence." intro="Each sentence carries a numbered citation. Click one and the source opens with the exact passage highlighted.">
        <div className="grid gap-12 lg:grid-cols-[1.4fr_1fr] lg:items-start">
          <div className="space-y-4">
            {product.sample.sources.map((src, i) => (
              <div key={i} className="rounded-xl border border-ink-200 bg-surface p-6">
                <p className="font-mono text-[11px] font-semibold tracking-[0.14em] text-brand-700 uppercase">Source {i + 1}</p>
                <p className="mt-2 font-semibold text-ink-950">{src.title}</p>
                <p className="text-sm text-ink-500">{src.where}</p>
                <p className="mt-4 font-serif text-base leading-7 text-ink-700">
                  {src.before}
                  <mark className="cite">{src.mark}</mark>
                  {src.after}
                </p>
              </div>
            ))}
            <p className="text-xs text-ink-500">Sample document, for illustration.</p>
          </div>
          <div>
            <h3 className="font-mono text-[11px] font-medium tracking-[0.14em] text-ink-500 uppercase">Questions teams ask</h3>
            <ul className="mt-4 space-y-3">
              {product.questions.map((q) => (
                <li key={q} className="border-l-2 border-ink-200 py-1 pl-4 text-ink-800">
                  “{q}”
                </li>
              ))}
            </ul>
          </div>
        </div>
      </Section>

      <Section tone="muted" label="Documents" title="Reads the documents you already have.">
        <div className="grid gap-12 lg:grid-cols-[1fr_1fr]">
          <CheckList items={product.documents} columns={1} />
          <p className="text-sm leading-7 text-ink-600">
            {BRAND} splits each document the way it is written: headings, sections, clauses and pages, so a citation says
            exactly where a passage is. PDFs need selectable text; scanned pages are reported and skipped, never guessed.
            Files can be up to 25 MB.{" "}
            <Link href="/docs/how-documents-are-read" className="font-medium text-ink-950 underline underline-offset-4">
              How documents are read
            </Link>
          </p>
        </div>
      </Section>

      <Section label="Workflow" title="From question to cited answer.">
        <NumberedGrid items={product.example} />
      </Section>

      <Section
        tone="muted"
        id="verification"
        label="Verification"
        title="Ten checks on every sentence."
        intro="The same verification engine behind both products: a drafted sentence must quote its source, or it is removed before you see it."
      >
        <VerificationChecks />
      </Section>

      <Section label="Security" title="Each team's documents stay with that team." action={<TextLink href="/security">Security overview</TextLink>}>
        <PointGrid items={SECURITY} columns={4} />
      </Section>

      <Section
        tone="muted"
        label="Pricing"
        title="Start with one team."
        intro={`The same plans cover ${BRAND} Legal QA and ${BRAND} Medical QA. Every plan includes the full product.`}
        action={<TextLink href="/pricing">See pricing</TextLink>}
      >
        <div className="grid gap-px overflow-hidden rounded-xl border border-ink-200 bg-ink-200 md:grid-cols-3">
          {PLANS.map((p) => (
            <div key={p.id} className="bg-surface p-7">
              <p className="font-mono text-[11px] tracking-[0.14em] text-ink-500 uppercase">{p.audience}</p>
              <h3 className="mt-4 text-xl font-semibold tracking-tight text-ink-950">{p.name}</h3>
              <p className="mt-1 text-ink-600">{p.price}</p>
            </div>
          ))}
        </div>
      </Section>

      <section className="border-b border-ink-200">
        <div className="mx-auto grid w-full max-w-6xl gap-12 px-6 py-20 md:py-28 lg:grid-cols-[1fr_2fr] lg:px-8">
          <div>
            <h2 className="text-3xl leading-tight font-medium text-ink-950 md:text-[2.75rem] md:leading-[1.08]">Questions.</h2>
            <div className="mt-8">
              <TextLink href="/faq">All questions</TextLink>
            </div>
          </div>
          <Questions items={product.faq} />
        </div>
      </section>

      <Section label="Related" title="Also see.">
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[
            ...solutions.map((s) => ({ href: `/solutions/${s.slug}`, label: s.name })),
            ...(other ? [{ href: `/products/${other.slug}`, label: other.fullName }] : []),
          ].map((l) => (
            <li key={l.href}>
              <Link
                href={l.href}
                className="group flex items-center justify-between rounded-xl border border-ink-200 bg-surface px-5 py-4 font-medium text-ink-900 hover:border-ink-950"
              >
                {l.label} <ArrowRight className="size-4 transition-transform group-hover:translate-x-1" aria-hidden />
              </Link>
            </li>
          ))}
        </ul>
      </Section>
    </>
  );
}

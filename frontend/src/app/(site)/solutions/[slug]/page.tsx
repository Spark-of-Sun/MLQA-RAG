import { ArrowRight } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { AnswerCard, ButtonLink, CheckList, NumberedGrid, PageHero, PointGrid, Section, TextLink } from "@/components/site/blocks";
import { SIGN_UP } from "@/components/site/links";
import { getProduct } from "@/components/site/products";
import { pageMeta } from "@/components/site/seo";
import { getSolution, SOLUTIONS } from "@/components/site/solutions";

export function generateStaticParams() {
  return SOLUTIONS.map((s) => ({ slug: s.slug }));
}

export const dynamicParams = false;

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const s = getSolution((await params).slug);
  return s ? pageMeta(s.name, s.intro, `/solutions/${s.slug}`) : {};
}

export default async function SolutionPage({ params }: { params: Promise<{ slug: string }> }) {
  const solution = getSolution((await params).slug);
  const product = solution && getProduct(solution.product);
  if (!solution || !product) notFound();
  const siblings = SOLUTIONS.filter((s) => s.slug !== solution.slug);
  return (
    <>
      <PageHero
        label={`${solution.name} · ${product.fullName}`}
        title={solution.title}
        intro={solution.intro}
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
      />

      <Section label="What teams do with it" title={`What ${product.fullName} does for ${solution.name.toLowerCase()}.`}>
        <PointGrid items={solution.jobs} columns={4} />
      </Section>

      <Section tone="muted" label="Questions" title="Questions they ask.">
        <ul className="grid gap-4 md:grid-cols-3">
          {solution.questions.map((q) => (
            <li key={q} className="rounded-xl border border-ink-200 bg-surface p-6 font-serif text-lg leading-7 text-ink-900">
              “{q}”
            </li>
          ))}
        </ul>
        <p className="mt-6 text-sm text-ink-500">
          Every answer cites its page and section, or says the documents do not address the question.
        </p>
      </Section>

      <Section label="Setup" title="How it is set up." intro={solution.setup}>
        <NumberedGrid
            columns={3}
            items={[
              { title: "Organization", body: "Your firm, hospital or practice, run by one Super Admin." },
              { title: "Workspaces", body: "One per team, each run by its own admin, invisible to the others." },
              { title: "Members", body: "Join with a one-time code and an admin's approval." },
          ]}
        />
        <div className="mt-14 grid gap-10 lg:grid-cols-[1fr_2fr]">
          <div>
            <h3 className="font-mono text-[11px] font-medium tracking-[0.14em] text-ink-500 uppercase">Documents</h3>
            <div className="mt-6">
              <TextLink href={`/products/${product.slug}`}>About {product.fullName}</TextLink>
            </div>
          </div>
          <CheckList items={product.documents} />
        </div>
      </Section>

      <Section tone="muted" label="More solutions" title="Other teams.">
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          {siblings.map((s) => (
            <li key={s.slug}>
              <Link
                href={`/solutions/${s.slug}`}
                className="group flex h-full items-center justify-between gap-3 rounded-xl border border-ink-200 bg-surface px-5 py-4 text-sm font-medium text-ink-900 hover:border-ink-950"
              >
                {s.name} <ArrowRight className="size-4 shrink-0 transition-transform group-hover:translate-x-1" aria-hidden />
              </Link>
            </li>
          ))}
        </ul>
      </Section>
    </>
  );
}

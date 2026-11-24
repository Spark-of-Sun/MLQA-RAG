import { ArrowRight } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { ButtonLink, PageHero, Section } from "@/components/site/blocks";
import { getProduct, PRODUCTS } from "@/components/site/products";
import { pageMeta } from "@/components/site/seo";
import { SOLUTIONS } from "@/components/site/solutions";
import { BRAND } from "@/lib/format";

export const metadata: Metadata = pageMeta(
  "Solutions",
  `How law firms, in-house legal, compliance, hospitals, pharmacy and research teams use ${BRAND} to get verified, cited answers from their own documents.`,
  "/solutions",
);

export default function SolutionsPage() {
  return (
    <>
      <PageHero
        label="Solutions"
        title="For the teams who sign their name to an answer."
        intro={`${BRAND} answers from your own documents and shows the passage behind every sentence. Here is how legal and clinical teams put it to work.`}
        actions={
          <ButtonLink href="/contact">
            Book a demo <ArrowRight className="size-4" aria-hidden />
          </ButtonLink>
        }
      />
      {PRODUCTS.map((p, i) => {
        const items = SOLUTIONS.filter((s) => s.product === p.slug);
        return (
          <Section
            key={p.slug}
            tone={i % 2 ? "muted" : "plain"}
            label={`On ${p.fullName}`}
            title={p.slug === "legal" ? "Legal teams." : "Healthcare teams."}
            intro={p.tagline}
          >
            <ul className="grid gap-px overflow-hidden rounded-xl border border-ink-200 bg-ink-200 md:grid-cols-3">
              {items.map((s) => {
                const Icon = s.icon;
                return (
                  <li key={s.slug}>
                    <Link href={`/solutions/${s.slug}`} className="group flex h-full flex-col bg-surface p-8 hover:bg-surface-hover">
                      <Icon className="size-5 text-ink-950" strokeWidth={1.6} aria-hidden />
                      <h2 className="mt-8 text-2xl font-medium text-ink-950">{s.name}</h2>
                      <p className="mt-2 flex-1 text-sm leading-6 text-ink-600">{s.summary}</p>
                      <p className="mt-6 border-t border-ink-200 pt-4 text-sm text-ink-700">
                        <span className="text-ink-400">Ask: </span>“{s.questions[0]}”
                      </p>
                      <span className="mt-6 flex items-center gap-1.5 text-sm font-medium text-ink-950">
                        {s.name} with {getProduct(s.product)?.fullName}
                        <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden />
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </Section>
        );
      })}
    </>
  );
}

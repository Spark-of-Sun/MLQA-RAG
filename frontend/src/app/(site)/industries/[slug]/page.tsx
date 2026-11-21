import { ArrowRight, Check } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ButtonLink, NumberedGrid, PageHero, PointGrid, Section } from "@/components/site/blocks";
import { INDUSTRIES } from "@/components/site/industries";

type Params = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { slug } = await params;
  const industry = INDUSTRIES.find((i) => i.slug === slug);
  return industry ? { title: industry.name, description: industry.intro } : {};
}

export default async function IndustryPage({ params }: Params) {
  const { slug } = await params;
  const industry = INDUSTRIES.find((i) => i.slug === slug);
  if (!industry) notFound();
  const others = INDUSTRIES.filter((i) => i.slug !== industry.slug);
  return (
    <>
      <PageHero
        label={industry.name}
        title={industry.title}
        intro={industry.intro}
        actions={
          <>
            <ButtonLink href="/contact">Talk to us</ButtonLink>
            <ButtonLink href="/industries" variant="secondary">
              All industries
            </ButtonLink>
          </>
        }
      />

      <Section title="How it fits." intro={industry.who}>
        <PointGrid items={industry.fits} columns={4} />
      </Section>

      <Section muted title="An example.">
        <NumberedGrid items={industry.example} />
      </Section>

      <Section title="Documents and questions.">
        <div className="grid gap-12 lg:grid-cols-2">
          <div>
            <h3 className="font-mono text-xs tracking-wider text-ink-500 uppercase">Documents</h3>
            <ul className="mt-4 space-y-3">
              {industry.documents.map((d) => (
                <li key={d} className="flex items-start gap-3 border-b border-ink-200 pb-3 text-ink-800">
                  <Check className="mt-0.5 size-4 shrink-0" aria-hidden /> {d}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h3 className="font-mono text-xs tracking-wider text-ink-500 uppercase">Questions teams ask</h3>
            <ul className="mt-4 space-y-3">
              {industry.questions.map((q) => (
                <li key={q} className="rounded-2xl border border-ink-200 bg-surface px-5 py-4 text-ink-800">
                  “{q}”
                </li>
              ))}
            </ul>
          </div>
        </div>
      </Section>

      <Section muted title="Also see.">
        <div className="grid gap-4 sm:grid-cols-3">
          {[
            ...others.map((o) => ({ href: `/industries/${o.slug}`, label: o.name })),
            { href: "/product", label: "Product" },
            { href: "/security", label: "Security" },
          ].map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className="group flex items-center justify-between rounded-2xl border border-ink-200 bg-surface px-5 py-4 font-medium text-ink-900 hover:border-ink-400"
            >
              {l.label} <ArrowRight className="size-4 transition-transform group-hover:translate-x-1" aria-hidden />
            </Link>
          ))}
        </div>
      </Section>
    </>
  );
}

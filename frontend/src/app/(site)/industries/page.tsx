import { ArrowRight } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { PageHero, Section } from "@/components/site/blocks";
import { INDUSTRIES } from "@/components/site/industries";
import { BRAND } from "@/lib/format";

export const metadata: Metadata = {
  title: "Industries",
  description: `${BRAND} for legal and healthcare teams.`,
};

export default function IndustriesPage() {
  return (
    <>
      <PageHero
        label="Industries"
        title="For work where every word matters."
        intro={`${BRAND} is built for teams who must show where every statement comes from. Choose legal, medical or both when you create your organization.`}
      />
      <Section title="Who it is for.">
        <div className="grid gap-6 lg:grid-cols-2">
          {INDUSTRIES.map((i) => (
            <Link key={i.slug} href={`/industries/${i.slug}`} className="group rounded-3xl border border-ink-200 bg-white p-8 hover:border-ink-400">
              <p className="font-mono text-xs tracking-wider text-ink-500 uppercase">{i.who}</p>
              <h3 className="mt-6 text-3xl font-semibold tracking-tight text-ink-950">{i.name}</h3>
              <p className="mt-3 text-ink-600">{i.intro}</p>
              <ul className="mt-6 flex flex-wrap gap-2">
                {i.documents.map((d) => (
                  <li key={d} className="rounded-full border border-ink-200 px-3 py-1 text-xs text-ink-600">
                    {d}
                  </li>
                ))}
              </ul>
              <p className="mt-8 flex items-center gap-2 text-sm font-medium text-ink-950">
                Learn more <ArrowRight className="size-4 transition-transform group-hover:translate-x-1" aria-hidden />
              </p>
            </Link>
          ))}
        </div>
      </Section>
    </>
  );
}

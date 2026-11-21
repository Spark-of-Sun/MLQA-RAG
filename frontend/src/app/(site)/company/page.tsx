import { ArrowRight } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { ButtonLink, PageHero, PointGrid, Section } from "@/components/site/blocks";
import { BRAND, COMPANY } from "@/lib/format";

export const metadata: Metadata = {
  title: "Company",
  description: `${COMPANY} builds software for professionals who have to stand behind every answer.`,
};

const BELIEFS = [
  { title: "Show the source", body: "An answer is only as good as the passage behind it, so every sentence links to one." },
  { title: "Silence beats a guess", body: "When the documents do not say it, the right answer is to say so." },
  { title: "Check before showing", body: "Verification happens before anyone reads the answer, not after a mistake." },
  { title: "Privacy is the default", body: "People choose what to share. Nobody gets access by accident or by rank." },
  { title: "Keep a record anyone can check", body: "Every action is written down, and anyone with access can verify the record." },
  { title: "Say what's real", body: "We describe what our product does today, plainly, including what isn't built yet." },
];

export default function CompanyPage() {
  return (
    <>
      <PageHero
        label="Company"
        title="Make AI answers safe to rely on."
        intro={`Professionals in law and medicine cannot use an answer they cannot prove. ${COMPANY} builds tools that show their work, so people can trust what they read and check it in a click.`}
        actions={
          <>
            <ButtonLink href="/contact">Contact us</ButtonLink>
            <ButtonLink href="/security" variant="secondary">
              Security
            </ButtonLink>
          </>
        }
      />
      <Section title="What we build.">
        <Link href="/product" className="group block rounded-3xl border border-ink-200 bg-surface p-8 hover:border-ink-400">
          <p className="font-mono text-xs tracking-wider text-ink-500 uppercase">Product</p>
          <h3 className="mt-4 text-3xl font-semibold tracking-tight text-ink-950">{BRAND}</h3>
          <p className="mt-3 max-w-2xl text-ink-600">
            Verified, cited answers from legal and medical documents. Every sentence links to its page and clause and is
            checked against that passage before anyone sees it.
          </p>
          <p className="mt-6 flex items-center gap-2 text-sm font-medium text-ink-950">
            Explore {BRAND} <ArrowRight className="size-4 transition-transform group-hover:translate-x-1" aria-hidden />
          </p>
        </Link>
      </Section>
      <Section dark title="What we believe.">
        <PointGrid items={BELIEFS} dark />
      </Section>
    </>
  );
}

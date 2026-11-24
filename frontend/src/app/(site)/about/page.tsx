import { ArrowRight } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { ButtonLink, CompanyFacts, NumberedGrid, PageHero, PointGrid, Section } from "@/components/site/blocks";
import { PRODUCTS } from "@/components/site/products";
import { pageMeta } from "@/components/site/seo";
import { BRAND, COMPANY } from "@/lib/format";

export const metadata: Metadata = pageMeta(
  "About",
  `${COMPANY} builds ${BRAND}, software for professionals who have to stand behind every answer.`,
  "/about",
);

const VALUES = [
  { title: "Show the source", body: "An answer is only as good as the passage behind it, so every sentence links to one." },
  { title: "Silence beats a guess", body: "When the documents do not say it, the right answer is to say so." },
  { title: "Check before showing", body: "Verification happens before anyone reads the answer, not after a mistake." },
  { title: "Privacy is the default", body: "People choose what to share. Nobody gets access by accident or by rank." },
  { title: "Keep a record anyone can check", body: "Every action is written down, and anyone with access can verify the record." },
  { title: "Say what's real", body: "We describe what our product does today, plainly, including what isn't built yet." },
];

const HOW_WE_WORK = [
  { title: "Demo", body: "We show Cyte on public documents like yours and answer your team's questions." },
  { title: "Pilot", body: "Your team uses Cyte on a chosen set of documents, with us on hand." },
  { title: "Roll out", body: "Workspaces for each team, admins approved, members invited." },
  { title: "Support", body: "Help by email for admins and members while you work." },
];

export default function AboutPage() {
  return (
    <>
      <PageHero
        label={`About ${COMPANY}`}
        title="Make AI answers safe to rely on."
        intro={`Professionals in law and medicine cannot use an answer they cannot prove. ${COMPANY} builds tools that show their work, so people can trust what they read and check it in a click.`}
        actions={
          <ButtonLink href="/contact">
            Contact us <ArrowRight className="size-4" aria-hidden />
          </ButtonLink>
        }
      />

      <section className="border-b border-ink-200">
        <div className="mx-auto grid w-full max-w-6xl gap-12 px-6 py-20 md:py-28 lg:grid-cols-[1fr_2fr] lg:px-8">
          <p className="font-mono text-[11px] font-medium tracking-[0.14em] text-ink-500 uppercase">Our mission</p>
          <div className="space-y-6 text-lg leading-8 text-ink-700">
            <p className="display text-3xl leading-tight text-ink-950 md:text-4xl">
              A lawyer cites the clause. A pharmacist checks the label. Software that helps them should do the same.
            </p>
            <p>
              Language models are good at writing. They are not, on their own, good at being right, and in a contract
              review or on a ward the difference matters. We built {BRAND} around one rule: a sentence is shown only if
              the passage it cites supports it, word for word and number for number.
            </p>
            <p>
              That rule shapes everything else: answers that refuse instead of guessing, access decided by the database
              rather than by the screens, and an audit trail that anyone with access can verify.
            </p>
          </div>
        </div>
      </section>

      <Section tone="muted" label="What we build" title={`${BRAND}, in two products.`}>
        <div className="grid gap-6 lg:grid-cols-2">
          {PRODUCTS.map((p) => (
            <Link key={p.slug} href={`/products/${p.slug}`} className="group block rounded-xl border border-ink-200 bg-surface p-8 hover:border-ink-950">
              <p className="font-mono text-[11px] tracking-[0.14em] text-ink-500 uppercase">{p.who}</p>
              <h3 className="display mt-4 text-2xl font-medium text-ink-950">{p.fullName}</h3>
              <p className="mt-3 text-ink-600">{p.tagline}</p>
              <p className="mt-6 flex items-center gap-2 text-sm font-medium text-ink-950">
                Explore {p.name} <ArrowRight className="size-4 transition-transform group-hover:translate-x-1" aria-hidden />
              </p>
            </Link>
          ))}
        </div>
      </Section>

      <Section tone="dark" label="Values" title="What we believe.">
        <PointGrid items={VALUES} dark />
      </Section>

      <Section label="Working with us" title="How we work with customers." intro={`${COMPANY} works directly with each early customer.`}>
        <NumberedGrid items={HOW_WE_WORK} />
      </Section>

      <Section tone="muted" label="Company" title="The details.">
        <CompanyFacts />
      </Section>
    </>
  );
}

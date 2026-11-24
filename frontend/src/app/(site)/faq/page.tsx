import type { Metadata } from "next";
import Link from "next/link";

import { Container, PageHero, Questions } from "@/components/site/blocks";
import { FAQ } from "@/components/site/faq";
import { PRODUCTS } from "@/components/site/products";
import { pageMeta } from "@/components/site/seo";
import { BRAND, SUPPORT_EMAIL } from "@/lib/format";

export const metadata: Metadata = pageMeta(
  "Help and FAQ",
  `Answers about ${BRAND}: how answers are checked, which files it reads, where data is processed, plans and getting started.`,
  "/faq",
);

// Every shared FAQ group, then each product's own questions, from products.ts.
const GROUPS = [...FAQ, ...PRODUCTS.map((p) => ({ id: p.slug, title: p.fullName, items: p.faq }))];

export default function FaqPage() {
  return (
    <>
      <PageHero
        label="Help and FAQ"
        title="Questions, answered plainly."
        intro={
          <>
            The questions teams ask before and after they start. For step-by-step help, read the{" "}
            <Link href="/docs" className="font-medium text-ink-950 underline underline-offset-4">
              documentation
            </Link>{" "}
            or email {SUPPORT_EMAIL}.
          </>
        }
      />
      <Container className="grid gap-12 py-16 md:py-24 lg:grid-cols-[14rem_1fr]">
        <nav aria-label="FAQ sections" className="lg:sticky lg:top-24 lg:self-start">
          <ul className="flex flex-wrap gap-2 lg:flex-col lg:gap-1">
            {GROUPS.map((g) => (
              <li key={g.id}>
                <a href={`#${g.id}`} className="block rounded-md px-3 py-1.5 text-sm text-ink-600 hover:bg-ink-100 hover:text-ink-950">
                  {g.title}
                </a>
              </li>
            ))}
          </ul>
        </nav>
        <div className="space-y-16">
          {GROUPS.map((g) => (
            <section key={g.id} id={g.id} className="scroll-mt-24" aria-labelledby={`${g.id}-title`}>
              <h2 id={`${g.id}-title`} className="mb-6 text-2xl font-medium text-ink-950 md:text-3xl">
                {g.title}
              </h2>
              <Questions items={g.items} />
            </section>
          ))}
        </div>
      </Container>
    </>
  );
}

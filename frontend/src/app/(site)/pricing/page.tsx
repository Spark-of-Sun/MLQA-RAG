import { ArrowRight, Check, Minus } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { ButtonLink, CheckList, PageHero, Questions, Section } from "@/components/site/blocks";
import { faqGroup } from "@/components/site/faq";
import { SIGN_UP } from "@/components/site/links";
import { INCLUDED, PLANS } from "@/components/site/pricing";
import { PRODUCTS } from "@/components/site/products";
import { pageMeta } from "@/components/site/seo";
import { BRAND } from "@/lib/format";

export const metadata: Metadata = pageMeta(
  "Pricing",
  `Plans for ${BRAND} Legal QA and ${BRAND} Medical QA: a pilot for one team, an organization plan, or enterprise terms.`,
  "/pricing",
);

type Cell = string | boolean;
const COMPARE: { row: string; cells: [Cell, Cell, Cell] }[] = [
  { row: "Products", cells: ["Legal QA or Medical QA", "One or both", "One or both"] },
  { row: "Workspaces", cells: ["One", "One per team", "One per team"] },
  { row: "Billing", cells: ["Monthly, for the pilot", "Annual", "Annual, terms agreed"] },
  { row: "Verified, cited answers", cells: [true, true, true] },
  { row: "Private chats and library", cells: [true, true, true] },
  { row: "Hash-chained audit trail", cells: [true, true, true] },
  { row: "Guided setup on your documents", cells: [true, true, true] },
  { row: "Rollout help for admins", cells: [false, true, true] },
  { row: "Hosting and data agreements", cells: [false, false, true] },
  { row: "Your own AI provider", cells: [false, false, "On request"] },
  { row: "Support", cells: ["Email", "Email", "Email"] },
];

function CellView({ c }: { c: Cell }) {
  if (c === true) return <Check className="mx-auto size-4 text-ink-950" aria-label="Included" />;
  if (c === false) return <Minus className="mx-auto size-4 text-ink-300" aria-label="Not included" />;
  return <span className="text-ink-700">{c}</span>;
}

export default function PricingPage() {
  return (
    <>
      <PageHero
        label="Pricing"
        title="Start with one team. Grow from there."
        intro={`The same plans cover ${BRAND} Legal QA and ${BRAND} Medical QA, and every plan includes the full product. During early access we agree the price with you and confirm it in writing before you commit.`}
      />

      <section className="border-b border-ink-200">
        <div className="mx-auto w-full max-w-6xl px-6 py-16 md:py-20 lg:px-8">
          <div className="grid gap-6 lg:grid-cols-3">
            {PLANS.map((p) => (
              <div
                key={p.id}
                className={`relative flex flex-col rounded-xl border bg-surface p-8 ${p.featured ? "border-ink-950 ring-1 ring-ink-950" : "border-ink-200"}`}
              >
                {p.featured && (
                  <p className="absolute -top-3 left-8 rounded-md bg-inverse px-2.5 py-1 font-mono text-[10px] tracking-[0.14em] text-on-inverse uppercase">
                    For rollout
                  </p>
                )}
                <p className="font-mono text-[11px] tracking-[0.14em] text-ink-500 uppercase">{p.audience}</p>
                <h2 className="mt-5 text-3xl font-medium text-ink-950">{p.name}</h2>
                <p className="mt-2 text-lg text-ink-900">{p.price}</p>
                <p className="text-sm text-ink-500">Billing: {p.billing.toLowerCase()}</p>
                <p className="mt-5 text-sm leading-6 text-ink-600">{p.body}</p>
                <dl className="mt-6 space-y-2 border-t border-ink-200 pt-5 text-sm">
                  <div className="flex justify-between gap-4">
                    <dt className="text-ink-500">Products</dt>
                    <dd className="text-right text-ink-900">{p.products}</dd>
                  </div>
                  <div className="flex justify-between gap-4">
                    <dt className="text-ink-500">Workspaces</dt>
                    <dd className="text-right text-ink-900">{p.workspaces}</dd>
                  </div>
                </dl>
                <ul className="mt-6 flex-1 space-y-2.5">
                  {p.highlights.map((h) => (
                    <li key={h} className="flex items-start gap-2.5 text-sm text-ink-800">
                      <Check className="mt-0.5 size-4 shrink-0 text-ink-950" aria-hidden /> {h}
                    </li>
                  ))}
                </ul>
                <div className="mt-8">
                  <ButtonLink href={p.cta.href} variant={p.featured ? "primary" : "secondary"}>
                    {p.cta.label} <ArrowRight className="size-4" aria-hidden />
                  </ButtonLink>
                </div>
              </div>
            ))}
          </div>
          <p className="mt-6 text-sm text-ink-500">
            Prefer to start on your own? You can{" "}
            <a href={SIGN_UP} className="font-medium text-ink-900 underline underline-offset-4">
              create an organization
            </a>{" "}
            and invite your team today.
          </p>
        </div>
      </section>

      <Section tone="muted" label="By product" title="Pick the product for your documents.">
        <div className="grid gap-6 lg:grid-cols-2">
          {PRODUCTS.map((p) => {
            const Icon = p.icon;
            return (
              <div key={p.slug} className="rounded-xl border border-ink-200 bg-surface p-8">
                <div className="flex items-center gap-3">
                  <Icon className="size-5 text-ink-950" strokeWidth={1.6} aria-hidden />
                  <h3 className="text-xl font-semibold tracking-tight text-ink-950">{p.fullName}</h3>
                </div>
                <p className="mt-3 text-sm leading-6 text-ink-600">{p.tagline} Available on every plan.</p>
                <ul className="mt-5 flex flex-wrap gap-2">
                  {p.documents.map((d) => (
                    <li key={d} className="rounded-md border border-ink-200 bg-page px-2.5 py-1 text-xs text-ink-600">
                      {d}
                    </li>
                  ))}
                </ul>
                <Link href={`/products/${p.slug}`} className="mt-6 inline-flex items-center gap-1.5 text-sm font-medium text-ink-950 underline-offset-4 hover:underline">
                  About {p.fullName} <ArrowRight className="size-3.5" aria-hidden />
                </Link>
              </div>
            );
          })}
        </div>
      </Section>

      <Section label="Compare plans" title="What each plan includes.">
        <div className="overflow-x-auto rounded-xl border border-ink-200 bg-surface">
          <table className="w-full min-w-[40rem] text-sm">
            <caption className="sr-only">Plan comparison</caption>
            <thead className="border-b border-ink-200">
              <tr>
                <th scope="col" className="px-5 py-4 text-left font-medium text-ink-500">
                  Feature
                </th>
                {PLANS.map((p) => (
                  <th key={p.id} scope="col" className="px-4 py-4 text-center font-semibold text-ink-950">
                    {p.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-200">
              {COMPARE.map((r) => (
                <tr key={r.row}>
                  <th scope="row" className="px-5 py-3.5 text-left font-normal text-ink-700">
                    {r.row}
                  </th>
                  {r.cells.map((c, i) => (
                    <td key={i} className="px-4 py-3.5 text-center">
                      <CellView c={c} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section tone="muted" label="Every plan" title="The full product, on every plan.">
        <CheckList items={INCLUDED} />
      </Section>

      <Section label="FAQ" title="Questions about plans.">
        <Questions items={faqGroup("buying")} />
      </Section>
    </>
  );
}

import { ArrowRight, Check } from "lucide-react";
import type { Metadata } from "next";

import { ButtonLink, PageHero, Questions, Section } from "@/components/site/blocks";
import { DEMO_MAIL, SIGN_UP } from "@/components/site/links";
import { BRAND } from "@/lib/format";

export const metadata: Metadata = {
  title: "Pricing",
  description: `${BRAND} plans for teams and organizations.`,
};

const INCLUDED = [
  "Organization, workspaces and member roles",
  "Verified answers with page and clause citations",
  "Private chats with follow-up questions",
  "Library with private, shared and workspace documents",
  "Member profiles and usage counts for admins",
  "Hash-chained audit trail with filters and verification",
  "Email support",
];

const PLANS = [
  {
    name: "Pilot",
    price: "Set with you",
    note: "For one team",
    body: "Try Cyte on your own documents with a small group, with us on hand to help.",
    cta: { href: "/contact", label: "Start a pilot" },
  },
  {
    name: "Organization",
    price: "Annual agreement",
    note: "For firms and hospitals",
    body: "Roll Cyte out across teams, with a workspace for each and direct help from our team.",
    cta: { href: DEMO_MAIL, label: "Contact sales" },
  },
];

const QUESTIONS = [
  {
    q: "Why are there no prices on this page?",
    a: `${BRAND} is in early access. We agree plans with each early customer and share them before you commit.`,
  },
  {
    q: "Can we try it first?",
    a: "Yes. You can create an organization and invite your team today. For a guided pilot on your own documents, talk to us.",
  },
  {
    q: "Can we use our own AI provider?",
    a: "Cyte works with several model providers. Ask us about using the provider and plan your organization already has.",
  },
];

export default function PricingPage() {
  return (
    <>
      <PageHero
        center
        label="Pricing"
        title="Start with one team. Grow from there."
        intro="Every plan includes the full product. We set the terms with you during early access."
        actions={
          <ButtonLink href={SIGN_UP}>
            Create your organization <ArrowRight className="size-4" aria-hidden />
          </ButtonLink>
        }
      />
      <Section title="Plans.">
        <div className="grid gap-6 lg:grid-cols-2">
          {PLANS.map((p) => (
            <div key={p.name} className="flex flex-col rounded-3xl border border-ink-200 bg-white p-8">
              <p className="font-mono text-xs tracking-wider text-ink-500 uppercase">{p.note}</p>
              <h3 className="mt-4 text-2xl font-semibold tracking-tight text-ink-950">{p.name}</h3>
              <p className="mt-1 text-lg text-ink-600">{p.price}</p>
              <p className="mt-4 flex-1 text-sm leading-6 text-ink-600">{p.body}</p>
              <div className="mt-8">
                <ButtonLink href={p.cta.href} variant={p.name === "Pilot" ? "primary" : "secondary"}>
                  {p.cta.label}
                </ButtonLink>
              </div>
            </div>
          ))}
        </div>
      </Section>
      <Section muted title="Included in every plan.">
        <ul className="grid gap-x-10 gap-y-3 sm:grid-cols-2">
          {INCLUDED.map((i) => (
            <li key={i} className="flex items-start gap-3 border-b border-ink-200 pb-3 text-ink-800">
              <Check className="mt-0.5 size-4 shrink-0" aria-hidden /> {i}
            </li>
          ))}
        </ul>
      </Section>
      <Section title="Questions.">
        <Questions items={QUESTIONS} />
      </Section>
    </>
  );
}

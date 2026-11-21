import { BookOpen, LifeBuoy, Mail, ShieldAlert } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { NumberedGrid, PageHero, Section } from "@/components/site/blocks";
import { mailto } from "@/components/site/links";
import { BRAND, COMPANY, CONTACT_EMAIL, SUPPORT_EMAIL } from "@/lib/format";

export const metadata: Metadata = {
  title: "Contact",
  description: `Talk to the ${COMPANY} team about ${BRAND}.`,
};

const CHANNELS = [
  {
    icon: Mail,
    title: "Sales and demos",
    email: CONTACT_EMAIL,
    href: mailto(CONTACT_EMAIL, `${BRAND} demo request`),
    body: "Demos, pilots, plans and anything else about working with us.",
  },
  {
    icon: LifeBuoy,
    title: "Support",
    email: SUPPORT_EMAIL,
    href: mailto(SUPPORT_EMAIL, `${BRAND} support`),
    body: "Help with your account, your workspace or an answer.",
  },
  {
    icon: ShieldAlert,
    title: "Security",
    email: CONTACT_EMAIL,
    href: mailto(CONTACT_EMAIL, `${BRAND} security`),
    body: "Report a vulnerability or start a security review.",
  },
];

const NEXT = [
  { title: "You write", body: "Tell us about your team, your documents and the questions you need answered." },
  { title: "We reply", body: "A person from our team reads every message and answers it." },
  { title: "A demo", body: "We show Cyte on public documents like yours." },
  { title: "Your pilot", body: "Your team tries Cyte on its own documents, with our help." },
];

export default function ContactPage() {
  return (
    <>
      <PageHero
        center
        label="Contact"
        title="Talk to the team."
        intro="Tell us about the documents you work with and what you need to find in them. We read every message."
      />
      <Section title="How to reach us.">
        <div className="grid gap-6 md:grid-cols-3">
          {CHANNELS.map(({ icon: Icon, title, email, href, body }) => (
            <a key={title} href={href} className="group rounded-3xl border border-ink-200 bg-surface p-7 hover:border-ink-400">
              <Icon className="size-5 text-ink-700" aria-hidden />
              <h3 className="mt-5 font-semibold text-ink-950">{title}</h3>
              <p className="mt-2 text-sm leading-6 text-ink-600">{body}</p>
              <p className="mt-5 text-sm font-medium text-ink-950 underline-offset-4 group-hover:underline">{email}</p>
            </a>
          ))}
        </div>
        <p className="mt-8 flex items-center gap-2 text-sm text-ink-600">
          <BookOpen className="size-4" aria-hidden /> Already a customer? Read the{" "}
          <Link href="/docs" className="font-medium text-link underline underline-offset-4">
            {BRAND} docs
          </Link>
          , or email {SUPPORT_EMAIL}.
        </p>
      </Section>
      <Section muted title="What happens next.">
        <NumberedGrid items={NEXT} />
      </Section>
    </>
  );
}

import { ArrowRight, BookOpen, LifeBuoy, Mail, ShieldAlert } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { Container, Label, NumberedGrid, Section } from "@/components/site/blocks";
import { DEMO_MAIL, mailto, SECURITY_MAIL, SUPPORT_MAIL } from "@/components/site/links";
import { pageMeta } from "@/components/site/seo";
import { BRAND, COMPANY, CONTACT_EMAIL, SUPPORT_EMAIL } from "@/lib/format";

export const metadata: Metadata = pageMeta(
  "Contact",
  `Book a demo of ${BRAND}, ask about plans, get support or report a security issue. We read every message.`,
  "/contact",
);

const CHANNELS = [
  { icon: Mail, title: "Sales and demos", email: CONTACT_EMAIL, href: DEMO_MAIL, body: "Demos, pilots, plans and anything else about working with us." },
  { icon: LifeBuoy, title: "Support", email: SUPPORT_EMAIL, href: SUPPORT_MAIL, body: "Help with your account, your workspace or an answer." },
  { icon: ShieldAlert, title: "Security", email: CONTACT_EMAIL, href: SECURITY_MAIL, body: "Report a vulnerability or start a security review." },
];

const NEXT = [
  { title: "You write", body: "Tell us about your team, your documents and the questions you need answered." },
  { title: "We reply", body: "A person from our team reads every message and answers it." },
  { title: "A demo", body: "We show Cyte on public documents like yours." },
  { title: "Your pilot", body: "Your team tries Cyte on its own documents, with our help." },
];

const TOPICS = {
  demo: { label: "Book a demo", to: CONTACT_EMAIL },
  pilot: { label: "Start a pilot", to: CONTACT_EMAIL },
  pricing: { label: "Plans and pricing", to: CONTACT_EMAIL },
  support: { label: "Support for an existing account", to: SUPPORT_EMAIL },
  security: { label: "Security review or report", to: CONTACT_EMAIL },
} as const;
type Topic = keyof typeof TOPICS;

const PRODUCT_CHOICES = ["Cyte Legal QA", "Cyte Medical QA", "Both", "Not sure yet"];

type Params = Record<string, string | string[] | undefined>;

function field(p: Params, key: string, max: number): string {
  const v = p[key];
  return (typeof v === "string" ? v : "").trim().slice(0, max);
}

/**
 * The form has no backend: it submits to this page (GET, same origin, so the strict CSP's `form-action 'self'`
 * allows it), and the page turns the answers into an email the visitor sends from their own mail app. Nothing is
 * stored or sent by the server. The answers do pass through the URL once (as with any GET form), which the
 * site's `Referrer-Policy: no-referrer` keeps from leaking to other sites.
 */
function draft(p: Params): { to: string; topic: string; href: string } | null {
  const key = field(p, "topic", 20);
  if (!(key in TOPICS)) return null;
  const topic = TOPICS[key as Topic];
  const name = field(p, "name", 120);
  const email = field(p, "email", 200);
  const org = field(p, "organization", 200);
  const product = field(p, "product", 40);
  const message = field(p, "message", 3000);
  const details = [
    name && `Name: ${name}`,
    email && `Email: ${email}`,
    org && `Organization: ${org}`,
    product && `Product: ${product}`,
  ].filter((l): l is string => Boolean(l));
  const body = [message, "", "—", ...details].join("\n");
  const subject = `${BRAND}: ${topic.label}${org ? ` (${org})` : ""}`;
  return { to: topic.to, topic: topic.label, href: `${mailto(topic.to, subject)}&body=${encodeURIComponent(body)}` };
}

const input =
  "mt-1.5 block w-full rounded-md border border-ink-300 bg-surface px-3 py-2.5 text-sm text-ink-950 placeholder:text-ink-400 focus:border-ink-950 focus:outline-none focus-visible:outline-2 focus-visible:outline-brand-500";

export default async function ContactPage({ searchParams }: { searchParams: Promise<Params> }) {
  const params = await searchParams;
  const ready = draft(params);
  const preset = field(params, "topic", 20);
  return (
    <>
      <section className="site-grid border-b border-ink-200">
        <Container className="grid gap-14 pt-16 pb-20 md:pt-24 md:pb-24 lg:grid-cols-[1fr_1.1fr]">
          <div>
            <div className="rise">
              <Label>Contact</Label>
            </div>
            <h1 className="rise d-1 mt-6 text-[2.6rem] leading-[1.05] font-medium text-balance text-ink-950 md:text-6xl md:leading-[1.03]">
              Talk to the team.
            </h1>
            <p className="rise d-2 mt-6 max-w-xl text-lg leading-8 text-ink-600">
              Tell us about the documents you work with and what you need to find in them. A person at {COMPANY} reads
              every message.
            </p>
            <ul className="rise d-3 mt-10 space-y-3">
              {CHANNELS.map(({ icon: Icon, title, email, href, body }) => (
                <li key={title}>
                  <a href={href} className="group flex gap-4 rounded-xl border border-ink-200 bg-surface p-5 hover:border-ink-950">
                    <Icon className="mt-0.5 size-5 shrink-0 text-ink-950" strokeWidth={1.6} aria-hidden />
                    <span>
                      <span className="block font-semibold text-ink-950">{title}</span>
                      <span className="mt-0.5 block text-sm leading-6 text-ink-600">{body}</span>
                      <span className="mt-2 block text-sm font-medium text-ink-950 underline-offset-4 group-hover:underline">{email}</span>
                    </span>
                  </a>
                </li>
              ))}
            </ul>
          </div>

          <div className="rise d-2 rounded-xl border border-ink-200 bg-surface p-6 shadow-[0_24px_48px_-28px_rgb(26_24_22/0.25)] md:p-8 dark:shadow-none">
            {ready ? (
              <div role="status" className="mb-8 rounded-lg border border-ink-950 bg-page p-5">
                <p className="font-semibold text-ink-950">Your message is ready to send.</p>
                <p className="mt-1 text-sm leading-6 text-ink-600">
                  It opens in your email app, addressed to {ready.to}. Nothing has been sent or stored yet.
                </p>
                <a
                  href={ready.href}
                  className="mt-4 inline-flex items-center gap-2 rounded-md bg-inverse px-4 py-2.5 text-sm font-medium text-on-inverse hover:bg-inverse-hover"
                >
                  Open in your email app <ArrowRight className="size-4" aria-hidden />
                </a>
              </div>
            ) : null}
            <h2 className="text-2xl font-medium text-ink-950">Send us a message</h2>
            <p className="mt-1 text-sm text-ink-500">All fields except organization are required.</p>
            <form action="/contact" method="get" className="mt-6 grid gap-5 sm:grid-cols-2">
              <label className="block text-sm font-medium text-ink-800">
                Name
                <input name="name" required maxLength={120} autoComplete="name" className={input} defaultValue={field(params, "name", 120)} />
              </label>
              <label className="block text-sm font-medium text-ink-800">
                Work email
                <input name="email" type="email" required maxLength={200} autoComplete="email" className={input} defaultValue={field(params, "email", 200)} />
              </label>
              <label className="block text-sm font-medium text-ink-800">
                Organization <span className="font-normal text-ink-500">(optional)</span>
                <input name="organization" maxLength={200} autoComplete="organization" className={input} defaultValue={field(params, "organization", 200)} />
              </label>
              <label className="block text-sm font-medium text-ink-800">
                Product
                <select name="product" className={input} defaultValue={field(params, "product", 40) || PRODUCT_CHOICES[0]}>
                  {PRODUCT_CHOICES.map((p) => (
                    <option key={p}>{p}</option>
                  ))}
                </select>
              </label>
              <label className="block text-sm font-medium text-ink-800 sm:col-span-2">
                What can we help with?
                <select name="topic" required className={input} defaultValue={preset in TOPICS ? preset : "demo"}>
                  {Object.entries(TOPICS).map(([k, t]) => (
                    <option key={k} value={k}>
                      {t.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block text-sm font-medium text-ink-800 sm:col-span-2">
                Message
                <textarea
                  name="message"
                  required
                  rows={5}
                  maxLength={3000}
                  placeholder="Your team, the documents you work with, and the questions you need answered."
                  className={input}
                  defaultValue={field(params, "message", 3000)}
                />
              </label>
              <div className="flex flex-col gap-3 sm:col-span-2 sm:flex-row sm:items-center sm:justify-between">
                <p className="text-xs leading-5 text-ink-500">
                  This form prepares an email in your own mail app; our server does not store it. See the{" "}
                  <Link href="/legal/privacy" className="underline underline-offset-4">
                    privacy notice
                  </Link>
                  .
                </p>
                <button
                  type="submit"
                  className="inline-flex shrink-0 items-center justify-center gap-2 rounded-md bg-inverse px-5 py-2.5 text-sm font-medium text-on-inverse hover:bg-inverse-hover"
                >
                  Prepare email <ArrowRight className="size-4" aria-hidden />
                </button>
              </div>
            </form>
          </div>
        </Container>
      </section>

      <Section tone="muted" label="What happens next" title="From first message to pilot.">
        <NumberedGrid items={NEXT} />
        <p className="mt-10 flex items-center gap-2 text-sm text-ink-600">
          <BookOpen className="size-4" aria-hidden /> Already a customer? Read the{" "}
          <Link href="/docs" className="font-medium text-ink-950 underline underline-offset-4">
            {BRAND} docs
          </Link>
          , or email {SUPPORT_EMAIL}.
        </p>
      </Section>
    </>
  );
}

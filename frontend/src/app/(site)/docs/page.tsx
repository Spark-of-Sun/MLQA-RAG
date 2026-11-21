import { ArrowRight, Mail } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { mailto } from "@/components/site/links";
import { docsNav } from "@/lib/docs";
import { BRAND, SUPPORT_EMAIL } from "@/lib/format";

export const metadata: Metadata = {
  title: "Docs",
  description: `How to use ${BRAND}: getting started, asking questions, documents, people and access, and the audit trail.`,
};

const START = [
  { slug: "introduction", label: "What Cyte is and how an answer is made" },
  { slug: "sign-up-and-join", label: "Create an organization or join one" },
  { slug: "who-can-see-what", label: "Who can see what" },
];

export default function DocsHome() {
  const nav = docsNav();
  return (
    <div>
      <p className="font-mono text-xs tracking-wider text-ink-500 uppercase">Documentation</p>
      <h1 className="mt-3 text-4xl font-semibold tracking-tight text-ink-950 md:text-5xl">{BRAND} docs</h1>
      <p className="mt-4 max-w-2xl text-lg leading-8 text-ink-600">
        Everything you need to set up your organization, invite your team, and get verified, cited answers from your
        documents.
      </p>

      <div className="mt-10 grid gap-3 sm:grid-cols-3">
        {START.map((s, i) => (
          <Link
            key={s.slug}
            href={`/docs/${s.slug}`}
            className="group rounded-2xl border border-ink-200 bg-surface p-5 shadow-edge transition-colors hover:border-ink-400"
          >
            <span className="font-mono text-xs text-ink-400">{String(i + 1).padStart(2, "0")}</span>
            <span className="mt-3 block font-medium text-ink-950">{s.label}</span>
            <ArrowRight className="mt-4 size-4 text-ink-400 transition-transform group-hover:translate-x-1" aria-hidden />
          </Link>
        ))}
      </div>

      <div className="mt-16 space-y-12">
        {nav.map((g) => (
          <section key={g.group}>
            <h2 className="text-xl font-semibold tracking-tight text-ink-950">{g.group}</h2>
            <ul className="mt-4 grid gap-x-8 sm:grid-cols-2">
              {g.items.map((it) => (
                <li key={it.slug} className="border-b border-ink-200">
                  <Link href={`/docs/${it.slug}`} className="group flex items-start justify-between gap-4 py-4">
                    <span>
                      <span className="block font-medium text-ink-950 group-hover:text-link">{it.title}</span>
                      <span className="mt-1 block text-sm text-ink-500">{it.summary}</span>
                    </span>
                    <ArrowRight
                      className="mt-1 size-4 shrink-0 text-ink-300 transition-transform group-hover:translate-x-1 group-hover:text-ink-700"
                      aria-hidden
                    />
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>

      <div className="mt-16 flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-ink-200 bg-surface px-6 py-5 shadow-edge">
        <div>
          <p className="font-medium text-ink-950">Can&apos;t find what you need?</p>
          <p className="text-sm text-ink-500">Our team answers every message.</p>
        </div>
        <a
          href={mailto(SUPPORT_EMAIL, `${BRAND} question`)}
          className="inline-flex items-center gap-2 rounded-full bg-inverse px-5 py-2.5 text-sm font-medium text-on-inverse hover:bg-inverse-hover"
        >
          <Mail className="size-4" aria-hidden /> {SUPPORT_EMAIL}
        </a>
      </div>
    </div>
  );
}

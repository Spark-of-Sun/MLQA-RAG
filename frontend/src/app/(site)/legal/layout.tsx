import type { ReactNode } from "react";
import Link from "next/link";

import { Container } from "@/components/site/blocks";

const PAGES = [
  { href: "/legal/privacy", label: "Privacy notice" },
  { href: "/legal/terms", label: "Terms of use" },
  { href: "/legal/cookies", label: "Cookie notice" },
];

// The legal pages: a short menu and the document. The texts are placeholders until counsel reviews them.
export default function LegalLayout({ children }: { children: ReactNode }) {
  return (
    <Container className="grid gap-12 py-16 md:py-24 lg:grid-cols-[14rem_1fr]">
      <nav aria-label="Legal" className="lg:sticky lg:top-24 lg:self-start">
        <p className="font-mono text-[11px] font-medium tracking-[0.14em] text-ink-500 uppercase">Legal</p>
        <ul className="mt-4 flex flex-wrap gap-2 lg:flex-col lg:gap-1">
          {PAGES.map((p) => (
            <li key={p.href}>
              <Link href={p.href} className="block rounded-md px-3 py-1.5 text-sm text-ink-700 hover:bg-ink-100 hover:text-ink-950 lg:-mx-3">
                {p.label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
      <article>{children}</article>
    </Container>
  );
}

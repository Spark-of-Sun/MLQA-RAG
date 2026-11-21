"use client";

import { ChevronDown } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

// The documentation menu. It receives titles and links only (lib/docs.ts docsNav), never page content or access
// levels, and lists every page the same way: whether a page is open to the reader is shown only on the page itself.

export interface NavGroup {
  group: string;
  items: { slug: string; title: string }[];
}

function Links({ nav, active }: { nav: NavGroup[]; active: string | null }) {
  return (
    <div className="space-y-6">
      <Link
        href="/docs"
        aria-current={active === null ? "page" : undefined}
        className={`block rounded-lg px-3 py-1.5 text-sm font-medium ${
          active === null ? "bg-brand-50 text-brand-700" : "text-ink-700 hover:bg-surface-hover hover:text-ink-950"
        }`}
      >
        Overview
      </Link>
      {nav.map((g) => (
        <div key={g.group}>
          <p className="px-3 font-mono text-[11px] tracking-wider text-ink-400 uppercase">{g.group}</p>
          <ul className="mt-2 space-y-0.5">
            {g.items.map((it) => {
              const on = it.slug === active;
              return (
                <li key={it.slug}>
                  <Link
                    href={`/docs/${it.slug}`}
                    aria-current={on ? "page" : undefined}
                    className={`block rounded-lg px-3 py-1.5 text-sm ${
                      on ? "bg-brand-50 font-medium text-brand-700" : "text-ink-600 hover:bg-surface-hover hover:text-ink-950"
                    }`}
                  >
                    {it.title}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </div>
  );
}

export function DocsNav({ nav }: { nav: NavGroup[] }) {
  const pathname = usePathname();
  const active = pathname.startsWith("/docs/") ? pathname.slice("/docs/".length) : null;
  const current = nav.flatMap((g) => g.items).find((it) => it.slug === active);
  return (
    <>
      <aside className="hidden w-60 shrink-0 lg:block" aria-label="Documentation">
        <nav className="sticky top-24 max-h-[calc(100vh-7rem)] overflow-y-auto pr-2 pb-10">
          <Links nav={nav} active={active} />
        </nav>
      </aside>
      {/* Small screens: the same menu behind a button above the page. */}
      <details key={pathname} className="group mb-6 rounded-xl border border-ink-200 bg-surface lg:hidden">
        <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-3 text-sm font-medium text-ink-900 [&::-webkit-details-marker]:hidden">
          {current ? current.title : "Documentation"}
          <ChevronDown className="size-4 text-ink-400 transition-transform group-open:rotate-180" aria-hidden />
        </summary>
        <nav className="border-t border-ink-100 p-3" aria-label="Documentation">
          <Links nav={nav} active={active} />
        </nav>
      </details>
    </>
  );
}
